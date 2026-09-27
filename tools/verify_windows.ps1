# Static parsing + isolated tests. Does not switch a real desktop account.
param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
foreach ($file in @('src/switch_account.ps1','src/continue_in_desktop.ps1')) {
    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile(
        (Join-Path $PWD $file), [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        $parseErrors | ForEach-Object { Write-Host $_.Message }
        throw "PowerShell parse failed: $file"
    }
    Write-Host "Parsed: $file"
}
& (Join-Path $PSScriptRoot 'test_composer_policy.ps1')
& (Join-Path $PSScriptRoot 'test_automatic_resume.ps1')
& (Join-Path $PSScriptRoot 'test_window_selection.ps1')
& (Join-Path $PSScriptRoot 'test_resume_location.ps1')
& $Python tools/build.py
if ($LASTEXITCODE -ne 0) { throw 'Resource build failed' }
& $Python -m unittest discover -s tests -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Python regression failed' }
Write-Host 'Static and isolated checks passed. Native UIA/account integration still needs manual acceptance.'
