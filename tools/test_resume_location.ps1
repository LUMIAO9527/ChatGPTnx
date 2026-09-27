# Pure production decision functions. No desktop, UIA or native input calls.
$ErrorActionPreference='Stop'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../src/continue_in_desktop.ps1'),[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'Parse failed'}
foreach($name in @('Select-ResumeCandidate','Get-LocationFailure')) {
    $f=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
    Invoke-Expression $f.Extent.Text
}
function Candidate($hwnd,$documents,$entries) {
    return [pscustomobject]@{Hwnd=[IntPtr]$hwnd;DocumentMatches=$documents;EntryMatches=$entries}
}
$empty=@((Candidate 1 0 0),(Candidate 2 0 0))
if($null -ne (Select-ResumeCandidate $empty ([IntPtr]1))){throw 'Absent target selected'}
if((Get-LocationFailure $empty 0) -ne 'target_not_visible'){throw 'Multiple empty windows mislabeled ambiguous'}
if((Get-LocationFailure $empty 1) -ne 'desktop_location_unreadable'){throw 'Read error mislabeled absent'}
$entries=@((Candidate 1 0 1),(Candidate 2 0 1))
if($null -ne (Select-ResumeCandidate $entries ([IntPtr]3))){throw 'Ambiguous entries selected'}
if((Get-LocationFailure $entries 0) -ne 'desktop_window_ambiguous'){throw 'Entry collision not classified'}
if((Select-ResumeCandidate $entries ([IntPtr]2)).Hwnd -ne [IntPtr]2){throw 'Foreground target not selected'}
$document=@((Candidate 1 1 0),(Candidate 2 0 1))
if((Select-ResumeCandidate $document ([IntPtr]2)).Hwnd -ne [IntPtr]1){throw 'Open task document must outrank sidebar'}
if($null -ne (Select-ResumeCandidate @((Candidate 1 2 0)) ([IntPtr]1))){throw 'Two documents in one window accepted'}
Write-Output '8 location decision checks passed; no desktop actions'
