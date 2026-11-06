# Synthetic UIA control tests only; never operate on a real desktop.
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '..\src\continue_in_desktop.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Parse failed'}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName WindowsBase
foreach($name in @('Resume-Task','Wait-ResumeReady','Runtime-Key','Invoke-NativeClick')) {
    $f=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
    Invoke-Expression $f.Extent.Text
}
function Native-Continue {
    $script:checks++
    if ($script:appearAfter -and $script:checks -lt $script:appearAfter) { return @() }
    return $script:buttons
}
function Assert-Account {}
function Focus-ResumeWindow {
    $script:focusChecks++
    if ($script:focusFails) { Skip 'native_continue_not_ready' }
    if ($script:remountOnFocus) {
        $script:document=Control 10
        $script:buttons=@(Control 11)
    }
}
function Native-ClickPoint($document,$button) {
    if ($script:occluded) { Skip 'native_continue_not_ready' }
    if ((Runtime-Key $button) -ne $script:expectedButtonKey) { throw 'Wrong click target' }
    return [pscustomobject]@{X=120;Y=240}
}
function Send-ContinueClick($point) {
    if ($point.X -ne 120 -or $point.Y -ne 240) { throw 'Click escaped the revalidated point' }
    $script:clickCalls++
    if ($script:sent -gt 1) { $script:clicked++ }
    return $script:sent
}
function Find-Target { return $script:document }
function Assert-Target {
    $script:targetChecks++
    if ($script:changeTarget -and $script:targetChecks -gt 1) { Skip 'target_changed' }
    if ($script:remountBeforeVerification -and $script:targetChecks -eq 2) {
        $script:document=Control 12
        $script:buttons=@(Control 13)
    }
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
$script:pattern | Add-Member ScriptMethod Invoke {$script:virtualInvokes++}
$script:document=Control 1
$button=Control 3
$script:clicked=0;$script:checks=0;$script:targetChecks=0
$script:virtualInvokes=0;$script:focusChecks=0;$script:clickCalls=0;$script:sent=3
$script:focusFails=$false;$script:occluded=$false
$script:remountOnFocus=$false;$script:remountBeforeVerification=$false;$script:expectedButtonKey='3'
$script:changeTarget=$false;$script:appearAfter=0;$script:buttons=@($button)
Resume-Task
if($script:clicked -ne 1){throw 'Native button not clicked exactly once'}
$script:buttons=@()
try {Resume-Task;throw 'Missing button accepted'}catch{if($_.Exception.Message -ne 'native_continue_unavailable'){throw}}
if($script:clicked -ne 1){throw 'Missing button caused a click'}
$script:buttons=@($button,$button)
try {Resume-Task;throw 'Ambiguous buttons accepted'}catch{if($_.Exception.Message -ne 'native_continue_ambiguous'){throw}}
$script:buttons=@((Control 4 $false))
try {Resume-Task;throw 'Disabled button accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
$script:buttons=@($button);$script:checks=0;$script:appearAfter=3
Resume-Task
if($script:clicked -ne 2 -or $script:checks -lt 3){throw 'Late button must be invoked once'}
$script:appearAfter=0;$script:changeTarget=$true;$script:targetChecks=0
try {Resume-Task;throw 'Changed task accepted'}catch{if($_.Exception.Message -ne 'target_changed'){throw}}
if($script:clicked -ne 2){throw 'Changed task was clicked'}
$script:changeTarget=$false
$unreadable=Control 5
$unreadable | Add-Member ScriptMethod GetRuntimeId {throw 'synthetic unreadable identity'} -Force
$script:buttons=@($unreadable)
try {Resume-Task;throw 'Unknown button identity accepted'}catch{if($_.Exception.Message -ne 'target_changed'){throw}}
if($script:clicked -ne 2){throw 'Unknown button identity was clicked'}
if($script:virtualInvokes -ne 0){throw 'Continue must use pointer input rather than a provider acknowledgement'}
$script:buttons=@($button)
$script:focusFails=$true
try {Resume-Task;throw 'Unfocused task accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
$script:focusFails=$false;$script:occluded=$true
try {Resume-Task;throw 'Occluded task accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
if($script:clickCalls -ne 2){throw 'Focus or hit-test failure dispatched input'}
$script:occluded=$false;$script:sent=0
try {Resume-Task;throw 'Rejected input accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
if($script:actionStarted){throw 'Zero inserted inputs must remain a pre-dispatch failure'}
$script:sent=2
try {Resume-Task;throw 'Partial input accepted'}catch{if($_.Exception.Message -ne 'native_continue'){throw}}
if(-not $script:actionStarted -or $script:clickCalls -ne 4){throw 'Partial input outcome must remain uncertain without replay'}
$script:sent=3;$DryRun=$true
Resume-Task
if($script:clickCalls -ne 4){throw 'Dry run dispatched input'}
$DryRun=$false
# Raising the same task can rebuild its accessibility document and button.
$script:remountOnFocus=$true
$script:expectedButtonKey='11'
Resume-Task
if($script:clickCalls -ne 5){throw 'Focus remount did not click the current Continue button exactly once'}
$script:remountOnFocus=$false
# A render between the two reads may replace the control again before any click.
$script:remountBeforeVerification=$true
$script:targetChecks=0
$script:expectedButtonKey='13'
Resume-Task
if($script:clickCalls -ne 6){throw 'Same-task remount after focus was not revalidated and clicked exactly once'}
$script:remountBeforeVerification=$false
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
$resume=[pscustomobject]@{Current=[pscustomobject]@{Name='Resume'}}
$start=[pscustomobject]@{Current=[pscustomobject]@{Name='Start'}}
$script:documentButtons=@($action,$start)
$found=@(Native-Continue 'document')
if($found.Count -ne 1 -or $found[0] -ne $action){throw 'Exact task-owned Continue not selected'}
$script:documentButtons=@($resume,$start)
$found=@(Native-Continue 'document')
if($found.Count -ne 1 -or $found[0] -ne $resume){throw 'English Resume button not selected'}
$script:documentButtons=@($start)
if(@(Native-Continue 'document').Count -ne 0){throw 'Generic Start button selected'}
$script:documentButtons=@()
if(@(Native-Continue 'document').Count -ne 0){throw 'Sibling fallback is forbidden'}
# Exercise the actual point/bounds validation against synthetic controls. The
# fake hit-test provider cannot read a real window or dispatch an input event.
Add-Type 'public static class NXResumeFakeHit { public static object Hit; public static object FromPoint(object point) { return Hit; } }'
$element = [NXResumeFakeHit]
$pointFunction=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Native-ClickPoint'},$true)
Invoke-Expression $pointFunction.Extent.Text
$script:pointAvailable=$true;$script:pointX=120;$script:pointY=240
$pointButton=Control 3
$pointButton.Current | Add-Member NoteProperty BoundingRectangle ([System.Windows.Rect]::new(100,200,80,80))
$pointButton | Add-Member ScriptMethod TryGetClickablePoint {
    param($outPoint)
    $outPoint.Value=[System.Windows.Point]::new($script:pointX,$script:pointY)
    return $script:pointAvailable
}
$pointDocument=Control 1
$pointDocument.Current | Add-Member NoteProperty BoundingRectangle ([System.Windows.Rect]::new(0,0,1000,1000))
[NXResumeFakeHit]::Hit=$pointButton
$point=Native-ClickPoint $pointDocument $pointButton
if($point.X -ne 120 -or $point.Y -ne 240){throw 'Clickable point was not preserved'}
$script:pointAvailable=$false
try {Native-ClickPoint $pointDocument $pointButton;throw 'Unavailable point accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
$script:pointAvailable=$true;$script:pointX=181
try {Native-ClickPoint $pointDocument $pointButton;throw 'Point outside button accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
$script:pointX=120
$pointDocument.Current.BoundingRectangle=[System.Windows.Rect]::new(0,0,100,100)
try {Native-ClickPoint $pointDocument $pointButton;throw 'Point outside task accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
$pointDocument.Current.BoundingRectangle=[System.Windows.Rect]::new(0,0,1000,1000)
[NXResumeFakeHit]::Hit=Control 99
try {Native-ClickPoint $pointDocument $pointButton;throw 'Different hit target accepted'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
Write-Output '23 synthetic native continuation cases passed; no desktop actions'
