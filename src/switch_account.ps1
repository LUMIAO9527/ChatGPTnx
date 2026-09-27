# Local credential transactions only. No remote session revocation.
# All dry runs are read-only. All target matches are exact.
param(
    [string]$To,
    [switch]$Snapshot,
    [switch]$Park,
    [switch]$List,
    [switch]$DryRun,
    [string]$AuthFile = (Join-Path $env:USERPROFILE '.codex\auth.json'),
    [Parameter(Mandatory=$true)]
    [string]$SnapshotDir,
    [string]$AppAumid = 'OpenAI.Codex_2p2nqsd0c76g0!App'
)
$ErrorActionPreference = 'Stop'
$DataDir = Join-Path $SnapshotDir 'recovery'
$Utf8 = New-Object Text.UTF8Encoding($false)

function Read-Identity([string]$Path) {
    $j = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $raw = $j.tokens.id_token
    if (-not $raw) { throw 'id_token missing; no changes made' }
    $parts = $raw.Split('.')
    if ($parts.Length -lt 2) { throw 'invalid credential format' }
    $p = $parts[1].Replace('-', '+').Replace('_', '/')
    switch ($p.Length % 4) { 2 { $p += '==' } 3 { $p += '=' } }
    $claim = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($p)) | ConvertFrom-Json
    $email = [string]$claim.email
    if ($email -notmatch '^[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+$') { throw 'unsafe or missing email' }
    $account = $j.tokens.account_id
    if (-not $account) { $account = $j.account_id }
    if (-not $account) { $account = $claim.'https://api.openai.com/auth'.chatgpt_account_id }
    if (-not $account) { throw 'account id missing' }
    [pscustomobject]@{ Email=$email; AccountId=$account }
}
function Atomic-Copy([string]$From, [string]$ToPath) {
    $dir = Split-Path -Parent $ToPath
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    $tmp = Join-Path $dir ('.nx-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [IO.File]::Copy($From, $tmp, $false)
        # PS 5.1 binds $null to "" for .NET string params; File.Replace rejects
        # an empty backup path. [NullString]::Value is a true null.
        if (Test-Path -LiteralPath $ToPath) { [IO.File]::Replace($tmp, $ToPath, [NullString]::Value) }
        else { [IO.File]::Move($tmp, $ToPath) }
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
}
function Save-Snapshot {
    $who = Read-Identity $AuthFile
    Atomic-Copy $AuthFile (Join-Path $SnapshotDir ($who.Email + '.json'))
    $who
}
function Session-AppProcesses {
    # Other Windows sessions may belong to another signed-in user.
    $session = (Get-Process -Id $PID).SessionId
    @(Get-Process -Name ChatGPT -ErrorAction SilentlyContinue |
        Where-Object { $_.SessionId -eq $session })
}
function Stop-App {
    # Stop only the packaged desktop processes.  Do not explicitly kill codex
    # workers: one of them may own the task whose UI is being restarted.
    @(Session-AppProcesses) | Stop-Process -Force
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    while (@(Session-AppProcesses).Count -gt 0) {
        if ([DateTime]::UtcNow -ge $deadline) { throw 'ChatGPT did not stop in time' }
        Start-Sleep -Milliseconds 150
    }
}
function Wait-AppWindow([int]$TimeoutSeconds = 25) {
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $window = @(Session-AppProcesses |
                    Where-Object { $_.MainWindowHandle -ne 0 -and $_.Responding } |
                    Select-Object -First 1)
        if ($window.Count -gt 0) { return }
        Start-Sleep -Milliseconds 250
    }
    throw 'ChatGPT window did not appear after launch'
}
function Start-App {
    # Resolve the real AUMID from Start Apps so other install channels work;
    # the packaged default stays as a fallback for locked-down machines.
    $aumid = $AppAumid
    try {
        $entry = @(Get-StartApps -ErrorAction Stop | Where-Object { $_.Name -eq 'ChatGPT' } | Select-Object -First 1)
        if ($entry.Count -gt 0 -and $entry[0].AppID) { $aumid = [string]$entry[0].AppID }
    } catch { }
    $neutralDir = if ($env:WINDIR) { $env:WINDIR } else { $env:SystemRoot }
    # Explorer is the application broker: ChatGPT neither inherits this helper's
    # lifetime nor keeps the ChatGPTnx project directory as its working directory.
    Start-Process -FilePath explorer.exe -ArgumentList ('shell:AppsFolder\' + $aumid) `
        -WorkingDirectory $neutralDir -ErrorAction Stop
    Wait-AppWindow
}
function Resolve-Target([string]$Name) {
    if ($Name -notmatch '^[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+$') { throw 'invalid target' }
    $path = Join-Path $SnapshotDir ($Name + '.json')
    if (-not (Test-Path -LiteralPath $path)) { throw 'snapshot not found' }
    $id = Read-Identity $path
    if ($id.Email -ine $Name) { throw 'target email does not match snapshot' }
    $path
}

if ($List -or (-not $To -and -not $Snapshot -and -not $Park)) {
    if (Test-Path -LiteralPath $AuthFile) { (Read-Identity $AuthFile).Email }
    Get-ChildItem -LiteralPath $SnapshotDir -Filter '*.json' -ErrorAction SilentlyContinue |
        ForEach-Object { $_.BaseName }
    exit 0
}
$target = $null
if ($To) { $target = Resolve-Target $To }
if ($DryRun) {
    Write-Output 'Dry run: validated arguments; no files, processes, or credentials changed.'
    exit 0
}
if ($Snapshot) { $null = Save-Snapshot; Write-Output 'Snapshot saved.'; exit 0 }

# Back up original auth in snapshots/recovery before closing the app. It is removed only
# after a successful transaction. On rollback failure it remains for recovery.
[IO.Directory]::CreateDirectory($DataDir) | Out-Null
$backup = Join-Path $DataDir ('auth-recovery-' + [guid]::NewGuid().ToString('N') + '.json')
$hadAuth = Test-Path -LiteralPath $AuthFile
$committed = $false
try {
    if ($hadAuth) {
        $null = Read-Identity $AuthFile  # refuse destructive operations if unreadable
        Atomic-Copy $AuthFile $backup
    }
    Stop-App
    # Refresh snapshot only after the desktop process has stopped writing.
    if (Test-Path -LiteralPath $AuthFile) {
        $null = Save-Snapshot
        Atomic-Copy $AuthFile $backup
        $hadAuth = $true
    }
    if ($Park) {
        if (Test-Path -LiteralPath $AuthFile) { Remove-Item -LiteralPath $AuthFile -Force }
    } else {
        Atomic-Copy $target $AuthFile
        $actual = Read-Identity $AuthFile
        $wanted = Read-Identity $target
        if ($actual.AccountId -ne $wanted.AccountId -or $actual.Email -ine $wanted.Email) {
            throw 'identity verification failed'
        }
    }
    Start-App
    $committed = $true
} catch {
    $failure = $_
    try {
        if ($hadAuth -and (Test-Path -LiteralPath $backup)) {
            try { Stop-App } catch { }
            Atomic-Copy $backup $AuthFile
            Start-App
            Remove-Item -LiteralPath $backup -Force
        } elseif (-not $hadAuth) {
            Stop-App
            if (Test-Path -LiteralPath $AuthFile) { Remove-Item -LiteralPath $AuthFile -Force }
            Start-App
        }
    } catch {
        Write-Error 'Rollback incomplete. Keep snapshots/recovery/auth-recovery-*.json private for manual recovery.' -ErrorAction Continue
    }
    throw $failure
} finally {
    if ($committed -and (Test-Path -LiteralPath $backup)) { Remove-Item -LiteralPath $backup -Force }
}
Write-Output 'Local credential operation completed; application launch requested.'
