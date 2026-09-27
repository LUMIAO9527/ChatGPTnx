$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '..\src\continue_in_desktop.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Parse failed'}
Add-Type -AssemblyName UIAutomationClient
$f=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Resume-Task'},$true)
Invoke-Expression $f.Extent.Text
function Native-Continue {
    $script:checks++
    if ($script:appearAfter -and $script:checks -lt $script:appearAfter) { return @() }
    return $script:buttons
}
function Assert-Account {}
function Assert-Target { return $null }
function Skip($reason) { throw $reason }
$pattern=New-Object PSObject
$pattern | Add-Member ScriptMethod Invoke {$script:clicked++}
$button=New-Object PSObject
$button | Add-Member NoteProperty Current ([pscustomobject]@{IsEnabled=$true})
$button | Add-Member ScriptMethod GetCurrentPattern {param($p) return $script:pattern}
$script:clicked=0;$script:checks=0;$script:buttons=@($button)
Resume-Task $null
if($script:clicked -ne 1){throw 'Native button not clicked exactly once'}
$script:buttons=@()
try {Resume-Task $null;throw 'Missing button accepted'}catch{if($_.Exception.Message -ne 'native_continue_unavailable'){throw}}
if($script:clicked -ne 1){throw 'Missing button caused a click'}
$script:buttons=@($button,$button)
try {Resume-Task $null;throw 'Ambiguous buttons accepted'}catch{if($_.Exception.Message -ne 'native_continue_ambiguous'){throw}}
$disabled=New-Object PSObject
$disabled | Add-Member NoteProperty Current ([pscustomobject]@{IsEnabled=$false})
$script:buttons=@($disabled)
try {Resume-Task $null;throw 'Disabled native button sent text'}catch{if($_.Exception.Message -ne 'native_continue_not_ready'){throw}}
$script:buttons=@($button);$script:checks=0;$script:appearAfter=3
Resume-Task $null
if($script:clicked -ne 2 -or $script:checks -lt 3){throw 'Late native button must take priority'}
$native=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Native-Continue'},$true)
Invoke-Expression $native.Extent.Text
function Pinned-Window { return 'window' }
function Find-Controls {
    param($root,$Names,$Type,$IncludeDisabled)
    if($root -eq 'document'){return @()}
    return @($script:windowButtons | Where-Object {$_.Current.Name -in $Names})
}
function Visible-Controls { return @($script:editor) }
$script:editor=[pscustomobject]@{Current=[pscustomobject]@{BoundingRectangle=[pscustomobject]@{Left=1000;Right=1800;Top=1500}}}
$sidebar=[pscustomobject]@{Current=[pscustomobject]@{Name='继续';BoundingRectangle=[pscustomobject]@{Left=200;Width=90;Bottom=1140}}}
$action=[pscustomobject]@{Current=[pscustomobject]@{Name='继续生成';BoundingRectangle=[pscustomobject]@{Left=1200;Width=90;Bottom=1140}}}
$script:windowButtons=@($sidebar,$action)
$found=@(Native-Continue 'document')
if($found.Count -ne 1 -or $found[0] -ne $action){throw 'Conversation Continue sibling was not selected'}
$script:windowButtons=@($sidebar)
if(@(Native-Continue 'document').Count -ne 0){throw 'Sidebar button selected'}
Write-Output '7 native continuation routing and lookup cases passed; no desktop actions'
