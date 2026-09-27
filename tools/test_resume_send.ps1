$ErrorActionPreference='Stop'
# Load only the production send function; all desktop boundaries are simulated.
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '..\src\continue_in_desktop.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Parse failed'}
Add-Type -AssemblyName UIAutomationClient
Add-Type @'
public static class NXResumeWindow {
    public static int Writes;
    public static string Message;
    public static System.IntPtr GetForegroundWindow() { return new System.IntPtr(1); }
    public static bool SetForegroundWindow(System.IntPtr hwnd) { return true; }
    public static bool AppendUnicode(string text, System.IntPtr hwnd) { Writes++; Message=text; return true; }
}
'@
$f=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Send-ResumeMessage'},$true)
Invoke-Expression $f.Extent.Text
function Get-ResumeMessage { return 'continue-test' }
function Assert-Account {}
function Assert-Target { if($script:targetChanged){Skip 'target_changed'}; return $null }
function Skip($reason) { if($script:writeStarted){throw "uncertain:$reason"}; throw "skip:$reason" }
function Find-Send {
    param($document,$composer,$IncludeDisabled)
    $script:checks++
    if([NXResumeWindow]::Writes -gt 0 -and $script:checks -ge 3 -and -not $script:missing){return $script:button}
}
$editor=[pscustomobject]@{Current=[pscustomobject]@{HasKeyboardFocus=$true}}
$editor | Add-Member ScriptMethod SetFocus {}
$composer=[pscustomobject]@{Editor=$editor}
$pattern=New-Object PSObject
$pattern | Add-Member ScriptMethod Invoke {$script:clicked++}
$script:button=New-Object PSObject
$script:button | Add-Member ScriptMethod GetCurrentPattern {param($p) return $script:pattern}
$script:pin=[pscustomobject]@{Hwnd=[IntPtr]1}
$script:checks=0;$script:clicked=0;$script:writeStarted=$false
Send-ResumeMessage $null $composer
if([NXResumeWindow]::Writes -ne 1 -or $script:clicked -ne 1 -or [NXResumeWindow]::Message -ne 'continue-test'){throw 'Delayed send must insert exact message and click once'}
$script:targetChanged=$true;$script:writeStarted=$false
try {Send-ResumeMessage $null $composer;throw 'Target change accepted'}catch{if($_.Exception.Message -ne 'uncertain:target_changed'){throw}}
if([NXResumeWindow]::Writes -ne 2 -or $script:clicked -ne 1){throw 'Target change must not send again'}
$script:targetChanged=$false;$script:missing=$true;$script:writeStarted=$false
try {Send-ResumeMessage $null $composer;throw 'Missing send accepted'}catch{if($_.Exception.Message -ne 'uncertain:send_unavailable'){throw}}
if([NXResumeWindow]::Writes -ne 3 -or $script:clicked -ne 1){throw 'Timeout must not repeat text or click'}
Write-Output '3 send scenarios passed; no desktop actions'
