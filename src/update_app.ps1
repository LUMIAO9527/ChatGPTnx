# Bundled helper only. All update paths are confined to the running app directory.
param([Parameter(Mandatory=$true)][string]$Plan)
$ErrorActionPreference = 'Stop'
$candidate = $null
$replaced = $false
$phase = 'plan'
$batch = [IO.Path]::GetFullPath((Split-Path -Parent $Plan))
$result = Join-Path $batch 'result.json'
function Record-Result([string]$Status, [string]$Message, [string]$Reason='') {
    @{status=$Status;message=$Message;phase=$phase;reason=$Reason} | ConvertTo-Json | Set-Content -LiteralPath $result -Encoding UTF8
}
function Assert-PlainPath([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'unsafe_path' }
}
function File-Digest([string]$Path) {
    # Use the framework directly; inherited PSModulePath may belong to PowerShell 7.
    $stream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $sha.Dispose(); $stream.Dispose() }
}
function Start-App([string[]]$Arguments) {
    # PowerShell Start-Process joins arguments: quote paths explicitly, without a shell.
    $quoted = @($Arguments | ForEach-Object { '"' + $_.Replace('"','') + '"' })
    if ($quoted.Count) {
        Start-Process -FilePath $target -ArgumentList ($quoted -join ' ') -WorkingDirectory $root -WindowStyle Hidden -PassThru
    } else {
        Start-Process -FilePath $target -WorkingDirectory $root -WindowStyle Hidden -PassThru
    }
}
try {
    Assert-PlainPath $batch
    Assert-PlainPath $Plan
    $p = Get-Content -LiteralPath $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
    $root = [IO.Path]::GetFullPath($p.root).TrimEnd('\')
    $target = [IO.Path]::GetFullPath($p.executable)
    $updates = Join-Path $root '_wip\update'
    if ((Split-Path -Parent $batch) -ne $updates -or (Split-Path -Parent $target) -ne $root -or
        [IO.Path]::GetExtension($target) -ne '.exe' -or
        $p.token -notmatch '^[0-9a-f]{32}$' -or $p.sha256 -notmatch '^[0-9a-f]{64}$' -or
        $p.version -notmatch '^\d{1,5}\.\d{1,5}(?:\.\d{1,5})?$' -or [long]$p.size -lt 1024) { throw 'unsafe_plan' }
    foreach ($path in @($root,(Join-Path $root '_wip'),$updates,$target)) { Assert-PlainPath $path }
    $stage = Join-Path $batch 'ChatGPTnx.new.exe'
    $backup = Join-Path $batch 'previous.exe'
    $ack = Join-Path $batch 'started.json'
    Assert-PlainPath $stage
    if (Test-Path -LiteralPath $backup) { throw 'backup_exists' }
    if ((Get-Item -LiteralPath $stage).Length -ne [long]$p.size -or
        (File-Digest $stage) -ne $p.sha256) { throw 'checksum_failed' }
    if ([int]$p.parent_pid -le 0 -or [int]$p.parent_pid -eq $PID) { throw 'invalid_parent' }
    $phase = 'wait-parent'
    $parent = Get-Process -Id ([int]$p.parent_pid) -ErrorAction SilentlyContinue
    if ($parent -and -not $parent.WaitForExit(45000)) { throw 'parent_still_running' }
    $deadline = [DateTime]::UtcNow.AddSeconds(12)
    $phase = 'replace'
    do {
        try {
            [IO.File]::Replace($stage,$target,$backup,$true)
            $replaced = $true
            break
        } catch {
            if ([DateTime]::UtcNow -ge $deadline) { throw 'replacement_failed' }
            Start-Sleep -Milliseconds 250
        }
    } while ($true)
    $candidate = Start-App @('--update-ack',$ack,'--update-token',$p.token)
    $phase = 'start'
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    do {
        if (Test-Path -LiteralPath $ack) {
            try {
                $ready = Get-Content -LiteralPath $ack -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($ready.ready -eq $true -and $ready.token -eq $p.token -and $ready.version -eq $p.version) {
                    Record-Result 'complete' '更新完成'
                    exit 0
                }
            } catch { }
        }
        if ($candidate.HasExited) { break }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'startup_failed'
} catch {
    if ($replaced) {
        try {
            if ($candidate -and -not $candidate.HasExited) {
                # Only the exact child launched above, including its one-file loader.
                & "$env:SystemRoot\System32\taskkill.exe" /PID $candidate.Id /T /F 2>&1 | Out-Null
                $null = $candidate.WaitForExit(10000)
            }
            $failed = Join-Path $batch 'failed.exe'
            [IO.File]::Replace($backup,$target,$failed,$true)
            Record-Result 'rolled_back' '新版未能正常启动，已恢复原版本'
            $null = Start-App @()
            exit 2
        } catch {
            Record-Result 'recovery_needed' '更新未完成，旧程序保留在本次更新目录'
            exit 3
        }
    }
    Record-Result 'failed' '更新未完成，原程序未被替换' $_.Exception.GetType().Name
    exit 1
}
