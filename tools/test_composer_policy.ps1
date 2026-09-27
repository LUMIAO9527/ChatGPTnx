# Extract and run the ACTUAL pure functions. This touches no UIA, accounts,
# clipboard, keystrokes or window handles. Runs on PowerShell 5.1 and 7.
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '..\src\continue_in_desktop.ps1'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($scriptPath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw "Helper parse failed: $($errors[0].Message)" }
foreach ($name in @('Composer-Trim','Composer-TextState','Resolve-ComposerState')) {
    $func=$ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
    if ($null -eq $func) { throw "Classifier missing: $name" }
    Invoke-Expression $func.Extent.Text
}
$cases=@(
    @{text='';expected='empty'},
    @{text="`r`n";expected='empty'},
    @{text=" `t ";expected='empty'},
    @{text=([string][char]0x200B + [char]0xFEFF);expected='empty'},
    @{text=([string][char]0x2063 + [char]0x200E);expected='empty'},
    @{text=([string][char]0x00A0 + [char]0x3000);expected='empty'},
    @{text='Ask anything';expected='unknown'},
    @{text=" `r`nAsk anything`t ";expected='unknown'},
    @{text=([string][char]0x200B+'Ask anything'+[char]0xFEFF);expected='unknown'},
    @{text='随心输入';expected='unknown'},
    @{text="`r`n随心输入`r`n";expected='unknown'},
    @{text='Message ChatGPT';expected='unknown'},
    @{text='an actual unsent draft';expected='present'},
    @{text=("`r`n"+'x');expected='present'},
    @{text=([string][char]0x200B + 'x');expected='present'},
    @{text='Ask anything about this report';expected='present'},
    @{text='不要删除随心输入这些文字';expected='present'},
    @{text='继续';expected='present'}
)
foreach($case in $cases) {
    $actual=Composer-TextState $case.text 'Ask anything'
    if($actual -ne $case.expected) { throw "Text classifier mismatch: expected $($case.expected), got $actual" }
}
$combinations=@(
    @('empty','empty','empty'),@('empty','unknown','empty'),@('empty','unavailable','empty'),
    @('empty','present','unknown'),@('present','empty','unknown'),@('present','present','present'),
    @('present','unknown','present'),@('present','unavailable','present'),
    @('unknown','empty','unknown'),@('unknown','unknown','unknown'),@('unknown','present','present'),
    @('unknown','unavailable','unknown'),@('unavailable','empty','empty'),
    @('unavailable','present','present'),@('unavailable','unknown','unknown'),@('unavailable','unavailable','unknown')
)
foreach($case in $combinations) {
    $actual=Resolve-ComposerState $case[0] $case[1]
    if($actual -ne $case[2]) { throw "Evidence resolution mismatch: $($case[0]) / $($case[1])" }
}
Write-Output "$($cases.Count + $combinations.Count) classifier cases passed; native desktop not exercised."
