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

function Assert-SafePath([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        try {
            $attributes = [IO.File]::GetAttributes($cursor)
            if (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Credential path contains a link or reparse point'
            }
            if (($attributes -band [IO.FileAttributes]::Directory) -eq 0 -and
                (Get-Item -LiteralPath $cursor -Force).LinkType -eq 'HardLink') {
                throw 'Credential path has multiple hard links'
            }
        } catch [IO.FileNotFoundException] { } catch [IO.DirectoryNotFoundException] { }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}
function Protect-Path([string]$Path) {
    Assert-SafePath $Path
    $item = Get-Item -LiteralPath $Path -Force
    $acl = if ($item.PSIsContainer) { New-Object Security.AccessControl.DirectorySecurity }
           else { New-Object Security.AccessControl.FileSecurity }
    $acl.SetAccessRuleProtection($true, $false)
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $principals = @($user, (New-Object Security.Principal.SecurityIdentifier('S-1-5-18')),
                    (New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    foreach ($principal in $principals) {
        if ($item.PSIsContainer) {
            $rule = New-Object Security.AccessControl.FileSystemAccessRule($principal, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        } else {
            $rule = New-Object Security.AccessControl.FileSystemAccessRule($principal, 'FullControl', 'Allow')
        }
        $acl.AddAccessRule($rule)
    }
    # Direct .NET calls do not depend on inherited PSModulePath. The helper is
    # deliberately run by Windows PowerShell 5.1 even when its parent is PS7.
    if ($item.PSIsContainer) { [IO.Directory]::SetAccessControl($Path, $acl) }
    else { [IO.File]::SetAccessControl($Path, $acl) }
}
function Decode-CredentialBytes([byte[]]$Bytes) {
    try { $document = $Utf8.GetString($Bytes).TrimStart([char]0xFEFF) | ConvertFrom-Json }
    catch { throw 'Invalid credential document' }
    if ($document.PSObject.Properties.Name -contains 'chatgptnx_credential') {
        if ($document.chatgptnx_credential -ne 1 -or $document.protection -ne 'dpapi-current-user') {
            throw 'Unsupported credential protection format'
        }
        Add-Type -AssemblyName System.Security
        try {
            $encrypted = [Convert]::FromBase64String([string]$document.data)
            $plain = [Security.Cryptography.ProtectedData]::Unprotect($encrypted,
                $Utf8.GetBytes('ChatGPTnx credentials v1'), [Security.Cryptography.DataProtectionScope]::CurrentUser)
            return ,$plain
        } catch { throw 'Cannot decrypt credential for this Windows user' }
    }
    return ,$Bytes
}
function Read-CredentialBytes([string]$Path) {
    Assert-SafePath $Path
    return ,(Decode-CredentialBytes ([IO.File]::ReadAllBytes($Path)))
}
function Atomic-WriteBytes([byte[]]$Bytes, [string]$ToPath) {
    Assert-SafePath $ToPath
    $dir = Split-Path -Parent $ToPath
    [IO.Directory]::CreateDirectory($dir) | Out-Null
    # Only the portable store's directories get private directory ACLs. Never
    # change the official application's home directory or its other files.
    if ([IO.Path]::GetFullPath($ToPath).StartsWith([IO.Path]::GetFullPath($SnapshotDir).TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Protect-Path $dir
    }
    $tmp = Join-Path $dir ('.nx-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        # Set permissions while the file is empty, before plaintext auth bytes.
        $stream = [IO.File]::Open($tmp, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $stream.Dispose()
        Protect-Path $tmp
        $stream = [IO.File]::Open($tmp, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
        if ([Convert]::ToBase64String([IO.File]::ReadAllBytes($tmp)) -cne [Convert]::ToBase64String($Bytes)) {
            throw 'Credential file verification failed'
        }
        $delays = @(0, 10, 20, 40, 80, 160)
        for ($attempt = 0; $attempt -lt $delays.Count; $attempt++) {
            if ($delays[$attempt]) { Start-Sleep -Milliseconds $delays[$attempt] }
            Assert-SafePath $ToPath
            try {
                if (Test-Path -LiteralPath $ToPath) {
                    Protect-Path $ToPath
                    [IO.File]::Replace($tmp, $ToPath, [NullString]::Value)
                } else { [IO.File]::Move($tmp, $ToPath) }
                break
            } catch [IO.IOException] {
                $code = $_.Exception.GetBaseException().HResult -band 0xffff
                if ($attempt -eq $delays.Count - 1 -or $code -notin @(5, 32, 33)) { throw }
            } catch [UnauthorizedAccessException] {
                if ($attempt -eq $delays.Count - 1) { throw }
            }
        }
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
}
function Write-ProtectedCredential([byte[]]$Bytes, [string]$ToPath) {
    Add-Type -AssemblyName System.Security
    try {
        $cipher = [Security.Cryptography.ProtectedData]::Protect($Bytes,
            $Utf8.GetBytes('ChatGPTnx credentials v1'), [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $envelope = @{chatgptnx_credential=1; protection='dpapi-current-user'; data=[Convert]::ToBase64String($cipher)} | ConvertTo-Json -Compress
        $encoded = $Utf8.GetBytes($envelope)
        $decoded = Decode-CredentialBytes $encoded
        if ([Convert]::ToBase64String($decoded) -cne [Convert]::ToBase64String($Bytes)) { throw 'Verification failed' }
    } catch { throw 'Credential encryption verification failed' }
    Atomic-WriteBytes $encoded $ToPath
}
function Read-Identity([string]$Path) {
    $j = $Utf8.GetString((Read-CredentialBytes $Path)).TrimStart([char]0xFEFF) | ConvertFrom-Json
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
    Atomic-WriteBytes (Read-CredentialBytes $From) $ToPath
}
function Save-Snapshot {
    $who = Read-Identity $AuthFile
    Write-ProtectedCredential (Read-CredentialBytes $AuthFile) (Join-Path $SnapshotDir ($who.Email + '.json'))
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
Assert-SafePath $SnapshotDir
Assert-SafePath $AuthFile
[IO.Directory]::CreateDirectory($SnapshotDir) | Out-Null
Protect-Path $SnapshotDir
$lockPath = Join-Path $SnapshotDir '.credentials.lock'
Assert-SafePath $lockPath
try { $storeLock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
catch { throw 'Credential store is busy; retry after the current operation finishes' }
try {
if ($Snapshot) { $null = Save-Snapshot; Write-Output 'Snapshot saved.'; exit 0 }

# Recovery copies stay encrypted and are never automatically deleted.
Assert-SafePath $DataDir
[IO.Directory]::CreateDirectory($DataDir) | Out-Null
Protect-Path $DataDir
$backup = Join-Path $DataDir ('auth-recovery-' + [guid]::NewGuid().ToString('N') + '.json')
$hadAuth = Test-Path -LiteralPath $AuthFile
$authChanged = $false
$appStopped = $false
$launchAttempted = $false
try {
    if ($hadAuth) {
        $null = Read-Identity $AuthFile  # refuse destructive operations if unreadable
        Write-ProtectedCredential (Read-CredentialBytes $AuthFile) $backup
    }
    Stop-App
    $appStopped = $true
    # Refresh snapshot only after the desktop process has stopped writing.
    if (Test-Path -LiteralPath $AuthFile) {
        $null = Save-Snapshot
        Write-ProtectedCredential (Read-CredentialBytes $AuthFile) $backup
        $hadAuth = $true
    }
    if ($Park) {
        if (Test-Path -LiteralPath $AuthFile) {
            Assert-SafePath $AuthFile
            Remove-Item -LiteralPath $AuthFile -Force
            $authChanged = $true
        }
    } else {
        Atomic-Copy $target $AuthFile
        $authChanged = $true
        $actual = Read-Identity $AuthFile
        $wanted = Read-Identity $target
        if ($actual.AccountId -ne $wanted.AccountId -or $actual.Email -ine $wanted.Email) {
            throw 'identity verification failed'
        }
    }
    $launchAttempted = $true
    Start-App
} catch {
    $failure = $_
    try {
        if ($authChanged) {
            # A failed stop must never be swallowed: a running desktop could
            # have renewed its token, making a backup stale at this moment.
            Stop-App
            if ($hadAuth -and (Test-Path -LiteralPath $backup)) {
                Atomic-Copy $backup $AuthFile
            } elseif (-not $hadAuth) {
                Assert-SafePath $AuthFile
                if (Test-Path -LiteralPath $AuthFile) { Remove-Item -LiteralPath $AuthFile -Force }
            } else { throw 'Recovery credential missing' }
            Start-App
        } elseif ($appStopped -and -not $launchAttempted) {
            # Snapshot/encryption failed before auth mutation; restart with the
            # untouched original bytes, without any rollback write.
            Start-App
        }
    } catch {
        Write-Error 'Rollback incomplete. Keep snapshots/recovery/auth-recovery-*.json private for manual recovery.' -ErrorAction Continue
    }
    throw $failure
}
Write-Output 'Local credential operation completed; application launch requested.'
} finally { $storeLock.Dispose() }
