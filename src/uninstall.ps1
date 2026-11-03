param([Parameter(Mandatory=$true)][string]$Plan)
$ErrorActionPreference='Stop'
function Full([string]$value) { [System.IO.Path]::GetFullPath($value).TrimEnd('\') }
function Plain([string]$path) {
    $current=Full $path
    while($current) {
        if(Test-Path -LiteralPath $current) {
            $item=Get-Item -LiteralPath $current -Force
            if($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw 'redirected_path' }
        }
        if($current -eq $script:root) { break }
        $parent=[System.IO.Path]::GetDirectoryName($current)
        if($parent -eq $current) { break }
        $current=$parent
    }
}
function RemoveOwned([string]$path) {
    $resolved=Full $path
    if(-not $resolved.StartsWith($script:root+'\',[System.StringComparison]::OrdinalIgnoreCase)) { throw 'outside_application' }
    Plain $path
    if(-not (Test-Path -LiteralPath $path)) { return }
    $item=Get-Item -LiteralPath $path -Force
    if($item.PSIsContainer) {
        foreach($child in Get-ChildItem -LiteralPath $path -Force) { RemoveOwned $child.FullName }
    }
    Remove-Item -LiteralPath $path -Force
}
try {
    $stage='validate'
    $document=Get-Content -LiteralPath $Plan -Raw -Encoding UTF8 | ConvertFrom-Json
    if($document.schema -ne 1 -or $document.keep -isnot [bool]) { throw 'invalid_plan' }
    $script:root=Full $document.root
    if($script:root -eq [System.IO.Path]::GetPathRoot($script:root).TrimEnd('\')) { throw 'invalid_root' }
    $executable=Full $document.executable
    if($executable -ne (Join-Path $script:root 'ChatGPTnx.exe')) { throw 'invalid_executable' }
    $allowed=@($executable,(Join-Path $script:root '_wip\runtime'),(Join-Path $script:root '_wip\run'),(Join-Path $script:root '_wip\update'))
    if(-not $document.keep) { $allowed+=@((Join-Path $script:root 'snapshots'),(Join-Path $script:root '_data'),(Join-Path $script:root 'accounts.txt'),(Join-Path $script:root '.chatgptnx-location')) }
    if($document.targets.Count -ne $allowed.Count) { throw 'invalid_targets' }
    for($i=0;$i -lt $allowed.Count;$i++) { if((Full $document.targets[$i]) -ne (Full $allowed[$i])) { throw 'invalid_target' } }
    $batch=Full (Split-Path -Parent $Plan)
    if(-not $batch.StartsWith((Join-Path $script:root '_wip\uninstall\'),[System.StringComparison]::OrdinalIgnoreCase)) { throw 'invalid_worker' }
    Plain $script:root
    $stage='wait'
    foreach($processId in $document.pids) {
        $process=Get-Process -Id $processId -ErrorAction SilentlyContinue
        if($process) { $process.WaitForExit(60000) | Out-Null; if(-not $process.HasExited) { throw 'application_still_running' } }
    }
    Plain $executable
    $sha=[System.Security.Cryptography.SHA256]::Create()
    $stream=[System.IO.File]::OpenRead($executable)
    try { $digest=[System.BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','') }
    finally { $stream.Dispose();$sha.Dispose() }
    if($digest -ne $document.sha256) { throw 'program_changed' }
    $stage='files'
    foreach($target in $allowed) { RemoveOwned $target }
    $stage='registration'
    $key='HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\ChatGPTnx'
    if(Test-Path -LiteralPath $key) {
        $registered=Get-ItemProperty -LiteralPath $key
        if((Full $registered.InstallLocation) -eq $script:root) { Remove-Item -LiteralPath $key -Force }
    }
    $run='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $command=(Get-ItemProperty -LiteralPath $run -Name ChatGPTnx -ErrorAction SilentlyContinue).ChatGPTnx
    if($command -eq ('"'+$executable+'"')) { Remove-ItemProperty -LiteralPath $run -Name ChatGPTnx -Force }
    if(-not $document.quiet) {
        Add-Type -AssemblyName System.Windows.Forms
        $message=if($document.keep){'ChatGPTnx 已卸载，账号与数据已保留。'}else{'ChatGPTnx 及此设备保存的账号与数据已卸载。'}
        [System.Windows.Forms.MessageBox]::Show($message,'ChatGPTnx') | Out-Null
    }
    $stage='worker'
    $uninstall=Split-Path -Parent $batch
    RemoveOwned $batch
    foreach($folder in @($uninstall,(Join-Path $script:root '_wip'),$script:root)) {
        if((Test-Path -LiteralPath $folder) -and -not (Get-ChildItem -LiteralPath $folder -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $folder -Force }
    }
} catch {
    $failure=Join-Path (Split-Path -Parent $Plan) 'result.json'
    $reason=if($_.Exception.Message -match '^[a-z_]+$'){$_.Exception.Message}else{$_.Exception.GetType().Name}
    @{ok=$false;stage=$stage;reason=$reason} | ConvertTo-Json | Set-Content -LiteralPath $failure -Encoding UTF8
    if(-not $document.quiet) {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show('卸载未完成，请重新打开 ChatGPTnx 后重试。','ChatGPTnx') | Out-Null
    }
    exit 1
}
