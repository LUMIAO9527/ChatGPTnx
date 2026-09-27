$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../src/continue_in_desktop.ps1'),[ref]$tokens,[ref]$errors)
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Find-Composer'},$true)
Invoke-Expression $fn.Extent.Text
$editType='Edit'
function Visible-Controls {return $script:editors}
function Skip($reason){throw $reason}
function Editor($name){[pscustomobject]@{Current=[pscustomobject]@{Name=$name;ControlType='Edit';IsEnabled=$true;IsOffscreen=$false}}}
$script:editors=@((Editor 'different placeholder'))
if((Find-Composer $null).Editor -ne $script:editors[0]){throw 'Single editor not found'}
$script:editors=@((Editor 'search'),(Editor 'another edit'))
try{Find-Composer $null;throw 'Ambiguous editor accepted'}catch{if($_.Exception.Message -ne 'composer_unavailable'){throw}}
$script:editors=@()
try{Find-Composer $null;throw 'Missing editor accepted'}catch{if($_.Exception.Message -ne 'composer_unavailable'){throw}}
Write-Output '3 composer lookup cases passed without reading editor contents'
