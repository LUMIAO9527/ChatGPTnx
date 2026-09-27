# Synthetic UIA control tests only; never operate on a real desktop.
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '..\src\continue_in_desktop.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Parse failed'}
Add-Type -AssemblyName UIAutomationClient
foreach($name in @('Resume-Task','Runtime-Key')) {
    $f=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
    Invoke-Expression $f.Extent.Text
}
function Native-Continue {
    $script:checks++
    if ($script:appearAfter -and $script:checks -lt $script:appearAfter) { return @() }
    return $script:buttons
}
function Assert-Account {}
function Assert-Target {
    $script:targetChecks++
    if ($script:changeTarget -and $script:targetChecks -gt 1) { return $script:otherDocument }
    return $script:document
}
function Skip($reason) { throw $reason }
function Control([int]$id, [bool]$enabled=$true) {
    $control=New-Object PSObject
    $control | Add-Member NoteProperty Key $id
    $control | Add-Member NoteProperty Current ([pscustomobject]@{IsEnabled=$enabled})
    $control | Add-Member ScriptMethod GetRuntimeId { return @($this.Key) }
    $control | Add-Member ScriptMethod GetCurrentPattern {param($p) return $script:pattern}
    return $control
}
$script:pattern=New-Object PSObject
$script:pattern | Add-Member ScriptMethod Invoke {$script:clicked++}
$script:document=Control 1
$script:otherDocument=Control 2
$button=Control 3
$script:clicked=0;$script:checks=0;$script:targetChecks=0
$script:changeTarget=$false;$script:appearAfter=0;$script:buttons=@($button)
Resume-Task $script:document
if($script:clicked -ne 1){throw 'Native button not clicked exactly once'}
$script:buttons=@()
try {Resume-Task $script:document;throw 'Missing button accepted'}catch{if($_.Exception.Message -ne 'native_continue_unavailable'){throw}}
if($script:clicked -ne 1){throw 'Missing button caused a click'}
$script:buttons=@($button,$button)
try {Resume-Task $script:document;throw 'Ambiguous buttons accepted'}catch{if($_.Exception.Message -ne 'native_continue_ambiguous'){throw}}
$script:buttons=@((Control 4 $false))
try {Resume-Task $script:document;throw 'Disabled button accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
$script:buttons=@($button);$script:checks=0;$script:appearAfter=3
Resume-Task $script:document
if($script:clicked -ne 2 -or $script:checks -lt 3){throw 'Late button must be invoked once'}
$script:appearAfter=0;$script:changeTarget=$true;$script:targetChecks=0
try {Resume-Task $script:document;throw 'Changed task accepted'}catch{if($_.Exception.Message -ne 'target_changed'){throw}}
if($script:clicked -ne 2){throw 'Changed task was clicked'}
$script:changeTarget=$false
$unreadable=Control 5
$unreadable | Add-Member ScriptMethod GetRuntimeId {throw 'synthetic unreadable identity'} -Force
$script:buttons=@($unreadable)
try {Resume-Task $script:document;throw 'Unknown button identity accepted'}catch{if($_.Exception.Message -ne 'target_changed'){throw}}
if($script:clicked -ne 2){throw 'Unknown button identity was clicked'}
$native=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Native-Continue'},$true)
Invoke-Expression $native.Extent.Text
function Pinned-Window { throw 'Native lookup must not inspect sibling controls' }
function Visible-Controls { throw 'Native lookup must not inspect the editor' }
function Find-Controls {
    param($root,$Names,$Type,$IncludeDisabled)
    if($root -ne 'document'){throw 'Lookup escaped the target document'}
    return @($script:documentButtons | Where-Object {$_.Current.Name -in $Names})
}
$action=[pscustomobject]@{Current=[pscustomobject]@{Name='继续生成'}}
$start=[pscustomobject]@{Current=[pscustomobject]@{Name='Start'}}
$script:documentButtons=@($action,$start)
$found=@(Native-Continue 'document')
if($found.Count -ne 1 -or $found[0] -ne $action){throw 'Exact task-owned Continue not selected'}
$script:documentButtons=@($start)
if(@(Native-Continue 'document').Count -ne 0){throw 'Generic Start button selected'}
$script:documentButtons=@()
if(@(Native-Continue 'document').Count -ne 0){throw 'Sibling fallback is forbidden'}
Write-Output '10 synthetic native continuation cases passed; no desktop actions'
