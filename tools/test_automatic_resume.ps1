# Parse actual helper + run only pure message validation and C# structure checks.
# This does NOT call BlockInput, SendInput, UIA, or touch any desktop/account.
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\src\continue_in_desktop.ps1'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($scriptPath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw "Helper parse failed: $($errors[0].Message)" }
$func=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Valid-ResumeMessage'},$true)
if ($null -eq $func) { throw 'Missing message validator' }
Invoke-Expression $func.Extent.Text
$smile=[char]::ConvertFromUtf32(0x1F642)
$cases=@(
 @{value='继续'; valid=$true},@{value='Continue the task';valid=$true},
 @{value=$smile;valid=$true},@{value=('a'*200);valid=$true},
 @{value=($smile*200);valid=$true},@{value=('a'*201);valid=$false},
 @{value=($smile*201);valid=$false},@{value='';valid=$false},
 @{value=' ';valid=$false},@{value=' continue';valid=$false},
 @{value="continue`n";valid=$false},@{value="a`ttext";valid=$false},
 @{value=('a'+[char]0x200B);valid=$false},@{value=('a'+[char]0xA0+'b');valid=$false},
 @{value=([string][char]0xD800);valid=$false},@{value=([string][char]0xDC00);valid=$false},
 @{value=$null;valid=$false},@{value=42;valid=$false}
)
foreach($case in $cases) {
 if((Valid-ResumeMessage $case.value) -ne $case.valid) { throw 'Message validation mismatch' }
}
$source=Get-Content -LiteralPath $scriptPath -Raw -Encoding UTF8
$match=[regex]::Match($source,"(?s)Add-Type @'\r?\n(.*?)\r?\n'@")
if(-not $match.Success) { throw 'Missing embedded native source' }
# Compilation resolves declarations only. No NXInputGuard instance is created.
Add-Type -TypeDefinition $match.Groups[1].Value
$inputType=[NXResumeWindow].GetNestedType('INPUT',[Reflection.BindingFlags]::NonPublic)
if($null -eq $inputType) { throw 'INPUT structure missing' }
$expected=if([IntPtr]::Size -eq 8){40}else{28}
if([Runtime.InteropServices.Marshal]::SizeOf([Activator]::CreateInstance($inputType)) -ne $expected) { throw 'Wrong native INPUT layout' }
if([Runtime.InteropServices.Marshal]::OffsetOf($inputType,'data').ToInt32() -ne [IntPtr]::Size) { throw 'Wrong INPUT union offset' }
Write-Output "$($cases.Count) message cases and native source compilation/layout passed; no desktop calls executed."
