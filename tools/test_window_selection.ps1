$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../src/continue_in_desktop.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw $errors[0].Message}
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Select-ResumeCandidate'},$true)
Invoke-Expression $fn.Extent.Text
function C($h,$d,$e){[pscustomobject]@{Hwnd=[IntPtr]$h;DocumentMatches=$d;EntryMatches=$e}}
$cases=@(
 @{items=@((C 1 0 0),(C 2 1 0));fg=9;want=2},
 @{items=@((C 1 0 0),(C 2 1 0));fg=1;want=2},
 @{items=@((C 1 0 1),(C 2 1 0));fg=1;want=2},
 @{items=@((C 1 1 0),(C 2 1 0));fg=9;want=1},
 @{items=@((C 1 1 0),(C 2 1 0));fg=2;want=2},
 @{items=@((C 1 0 0),(C 2 0 1));fg=9;want=2},
 @{items=@((C 1 0 1),(C 2 0 1));fg=9;want=0},
 @{items=@((C 1 0 0));fg=1;want=0},
 @{items=@((C 1 2 0));fg=1;want=0},
 @{items=@((C 1 0 2));fg=1;want=0},
 @{items=@((C 1 2 0),(C 2 1 0));fg=9;want=2}
)
foreach($case in $cases){$result=Select-ResumeCandidate $case.items ([IntPtr]$case.fg);$actual=if($null -eq $result){0}else{$result.Hwnd.ToInt64()};if($actual -ne $case.want){throw "Expected $($case.want), got $actual"}}
Write-Output "$($cases.Count) target-window selection cases passed; no desktop actions."
