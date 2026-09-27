# Parse the native Continue helper and compile its focus declarations only.
# No desktop action or account switch is performed.
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\src\continue_in_desktop.ps1'
$tokens=$null; $errors=$null
$null=[System.Management.Automation.Language.Parser]::ParseFile($scriptPath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw "Helper parse failed: $($errors[0].Message)" }
$source=Get-Content -LiteralPath $scriptPath -Raw -Encoding UTF8
foreach($forbidden in @('SendInput','AppendUnicode','Send-ResumeMessage','Find-Composer')) {
    if($source.Contains($forbidden)) { throw "Obsolete editor action remains: $forbidden" }
}
if(-not $source.Contains('bridge_required')) {
    throw 'Quota failure must not enter the native helper'
}
$match=[regex]::Match($source,"(?s)Add-Type @'\r?\n(.*?)\r?\n'@")
if(-not $match.Success) { throw 'Missing embedded native source' }
Add-Type -TypeDefinition $match.Groups[1].Value
Write-Output 'Native Continue helper parsed and compiled; no desktop actions'
