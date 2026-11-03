# Parse the native Continue helper and compile its focus declarations only.
# No desktop action or account switch is performed.
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\src\continue_in_desktop.ps1'
$tokens=$null; $errors=$null
$null=[System.Management.Automation.Language.Parser]::ParseFile($scriptPath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw "Helper parse failed: $($errors[0].Message)" }
$source=Get-Content -LiteralPath $scriptPath -Raw -Encoding UTF8
foreach($forbidden in @('AppendUnicode','Send-ResumeMessage','Find-Composer','KEYBDINPUT','SendKeys')) {
    if($source.Contains($forbidden)) { throw "Obsolete editor action remains: $forbidden" }
}
if(-not $source.Contains('bridge_required')) {
    throw 'Quota failure must not enter the native helper'
}
$match=[regex]::Match($source,"(?s)Add-Type @'\r?\n(.*?)\r?\n'@")
if(-not $match.Success) { throw 'Missing embedded native source' }
Add-Type -TypeDefinition $match.Groups[1].Value
$inputType = [NXResumeWindow].GetNestedType('Input', [Reflection.BindingFlags]::NonPublic)
$expectedSize = if ([IntPtr]::Size -eq 8) { 40 } else { 28 }
if ([Runtime.InteropServices.Marshal]::SizeOf([Activator]::CreateInstance($inputType)) -ne $expectedSize) {
    throw 'Native mouse input layout does not match this Windows architecture'
}
if ([NXResumeWindow]::NormalizeCoordinate(-1920,-1920,3840) -ne 0 -or
    [NXResumeWindow]::NormalizeCoordinate(1919,-1920,3840) -ne 65535 -or
    [NXResumeWindow]::NormalizeCoordinate(0,0,1920) -ne 0 -or
    [NXResumeWindow]::NormalizeCoordinate(1919,0,1920) -ne 65535) {
    throw 'Mouse coordinates must cover the complete virtual desktop'
}
foreach ($caseValues in @(@(-1921,-1920,3840),@(1920,-1920,3840),@(0,0,1))) {
    try { $null=[NXResumeWindow]::NormalizeCoordinate($caseValues[0],$caseValues[1],$caseValues[2]); throw 'Invalid coordinate accepted' }
    catch { if ($_.Exception.Message -eq 'Invalid coordinate accepted') { throw } }
}
Write-Output 'Native Continue helper parsed and compiled; no desktop actions'
