# Click Continue only in the already-running, pinned ChatGPT task window.
# Quota failures use the desktop bridge and never call this helper.
param(
    [Parameter(Mandatory=$true)][string]$ThreadId,
    [Parameter(Mandatory=$true)][string]$TitlePrefix,
    [Parameter(Mandatory=$true)][ValidateSet('failed','interrupted')][string]$Action,
    [Parameter(Mandatory=$true)][string]$AuthFile,
    [Parameter(Mandatory=$true)][string]$ExpectedAuthHash,
    [string]$SettingsFile,
    [switch]$NavigateOnly,
    [switch]$DryRun,
    [switch]$WaitForTarget
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
if ($ThreadId -notmatch '^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$' -or
    [string]::IsNullOrWhiteSpace($TitlePrefix) -or
    $ExpectedAuthHash -notmatch '^[0-9a-f]{64}$') { throw 'Invalid action identity' }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Threading;
public static class NXResumeWindow {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);

}

'@
$tree = [System.Windows.Automation.TreeScope]
$element = [System.Windows.Automation.AutomationElement]
$buttonType = [System.Windows.Automation.ControlType]::Button
$documentType = [System.Windows.Automation.ControlType]::Document
$linkType = [System.Windows.Automation.ControlType]::Hyperlink
$script:actionStarted = $false

function Skip([string]$Reason) {
    # An error after Invoke cannot be retried automatically: the click may
    # have taken effect even when the UIA call did not return.
    if ($script:actionStarted) { Write-Output ('uncertain:' + $Reason) }
    else { Write-Output ('skip:' + $Reason) }
    exit 2
}
function Assert-Account {
    $stage = 'auth_hash'
    try {
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $hash = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($AuthFile))).Replace('-', '')
        } finally { $sha.Dispose() }
        if ($hash -ine $ExpectedAuthHash) { Skip 'account_changed' }
        if ($SettingsFile -and -not $NavigateOnly) {
            $stage = 'settings_read'
            if (-not (Test-Path -LiteralPath $SettingsFile)) { Skip 'account_guard_unavailable' }
            $settings = (Get-Content -LiteralPath $SettingsFile -Raw -Encoding UTF8 | ConvertFrom-Json).settings
            if ($settings.task_continuation -ne $true) { Skip 'continuation_disabled' }
        }
    } catch {
        Write-Output ('guard:' + (@{stage=$stage;type=$_.Exception.GetType().Name;
            code=($_.FullyQualifiedErrorId -replace '[^a-zA-Z0-9_.,-]','')} | ConvertTo-Json -Compress))
        Skip 'account_guard_unavailable'
    }
}
function Existing-Windows {
    $result = @()
    foreach ($window in $element::RootElement.FindAll($tree::Children,
                         [System.Windows.Automation.Condition]::TrueCondition)) {
        try {
            if ($window.Current.ClassName -ne 'Chrome_WidgetWin_1' -or $window.Current.IsOffscreen) { continue }
            $process = Get-Process -Id $window.Current.ProcessId -ErrorAction Stop
            # A web browser/PWA with a ChatGPT title is not the desktop client.
            if ([IO.Path]::GetFileName($process.Path) -ine 'ChatGPT.exe' -or
                $process.SessionId -ne (Get-Process -Id $PID).SessionId) { continue }
            $result += [pscustomobject]@{Window=$window; Process=$process;
                Hwnd=[IntPtr]$window.Current.NativeWindowHandle; Started=$process.StartTime.Ticks}
        } catch { }
    }
    return $result
}
function Pinned-Window {
    try {
        if (-not [NXResumeWindow]::IsWindow($script:pin.Hwnd)) { return $null }
        $process = Get-Process -Id $script:pin.Process.Id -ErrorAction Stop
        if ($process.StartTime.Ticks -ne $script:pin.Started -or
            [IO.Path]::GetFileName($process.Path) -ine 'ChatGPT.exe') { return $null }
        $window = $element::FromHandle($script:pin.Hwnd)
        if ($window.Current.ProcessId -ne $process.Id -or $window.Current.IsOffscreen) { return $null }
        return $window
    } catch { return $null }
}
function Select-ResumeCandidate($Candidates, [IntPtr]$Foreground) {
    # Prefer an already-open target document over a sidebar navigation entry.
    # A foreground window is a tie-breaker only when it contains the target.
    $documents = @($Candidates | Where-Object { $_.DocumentMatches -gt 0 })
    if ($documents.Count -gt 0) { $pool = $documents }
    else { $pool = @($Candidates | Where-Object { $_.EntryMatches -gt 0 }) }
    $valid = @($pool | Where-Object {
        if ($documents.Count -gt 0) { $_.DocumentMatches -eq 1 }
        else { $_.EntryMatches -eq 1 }
    })
    if ($pool.Count -eq 1 -and $valid.Count -eq 1) { return $valid[0] }
    $focused = @($valid | Where-Object { $_.Hwnd -eq $Foreground })
    if ($focused.Count -eq 1) { return $focused[0] }
    return $null
}
function Resolve-ResumeWindow($Windows, [IntPtr]$Foreground) {
    $candidates = @()
    $readErrors = 0
    foreach ($candidate in $Windows) {
        try {
            $documents = @(Visible-Controls $candidate.Window $documentType $true | Where-Object {
                $_.Current.Name.StartsWith($TitlePrefix,[StringComparison]::Ordinal)
            })
            $entries = @()
            if ($documents.Count -eq 0) {
                $entries = @((@(Visible-Controls $candidate.Window $buttonType) + @(Visible-Controls $candidate.Window $linkType)) | Where-Object {
                    $_.Current.Name.StartsWith($TitlePrefix,[StringComparison]::Ordinal)
                })
            }
            $candidates += [pscustomobject]@{Hwnd=$candidate.Hwnd; Candidate=$candidate;
                DocumentMatches=$documents.Count; EntryMatches=$entries.Count}
        } catch { $readErrors++ }
    }
    $script:locationEvidence = @{windows=$Windows.Count;
        document_windows=@($candidates | Where-Object {$_.DocumentMatches -gt 0}).Count;
        entry_windows=@($candidates | Where-Object {$_.EntryMatches -gt 0}).Count;
        read_errors=$readErrors}
    $script:locationReason = Get-LocationFailure $candidates $readErrors
    if ($readErrors -gt 0) { return $null }
    $selected = Select-ResumeCandidate $candidates $Foreground
    if ($null -ne $selected) { return $selected.Candidate }
    return $null
}
function Get-LocationFailure($Candidates, [int]$ReadErrors) {
    if ($ReadErrors -gt 0) { return 'desktop_location_unreadable' }
    $matches = @($Candidates | Where-Object {$_.DocumentMatches -gt 0 -or $_.EntryMatches -gt 0})
    if ($matches.Count -eq 0) { return 'target_not_visible' }
    return 'desktop_window_ambiguous'
}
function Visible-Controls($root,$Type,[bool]$IncludeDisabled=$false) {
    # Filter inside the UIA provider, rather than fetching every text node from
    # a long conversation and crossing COM for each property in PowerShell.
    $condition=[System.Windows.Automation.AndCondition]::new(
        [System.Windows.Automation.PropertyCondition]::new($element::ControlTypeProperty,$Type),
        [System.Windows.Automation.PropertyCondition]::new($element::IsOffscreenProperty,$false))
    if (-not $IncludeDisabled) {
        $condition=[System.Windows.Automation.AndCondition]::new($condition,
            [System.Windows.Automation.PropertyCondition]::new($element::IsEnabledProperty,$true))
    }
    return $root.FindAll($tree::Descendants,$condition)
}
function Find-Controls($root, [string[]]$Names, $Type, [bool]$IncludeDisabled=$false) {
    $result = @()
    foreach ($item in (Visible-Controls $root $Type $IncludeDisabled)) {
        try {
            if ($item.Current.ControlType -eq $Type -and $item.Current.Name -in $Names -and
                -not $item.Current.IsOffscreen -and ($IncludeDisabled -or $item.Current.IsEnabled)) { $result += $item }
        } catch { }
    }
    return $result
}
function Find-Target {
    $window = Pinned-Window
    if ($null -eq $window) { return $null }
    $matches = @()
    foreach ($item in (Visible-Controls $window $documentType $true)) {
        try {
            if ($item.Current.ControlType -eq $documentType -and -not $item.Current.IsOffscreen -and
                $item.Current.Name.StartsWith($TitlePrefix, [StringComparison]::Ordinal)) { $matches += $item }
        } catch { }
    }
    if ($matches.Count -eq 1) { return $matches[0] }
    return $null
}
function Runtime-Key($control) {
    try { return (($control.GetRuntimeId()) -join '.') } catch { return '' }
}
function Wait-ResumeReady([int]$TimeoutMs=6000) {
    # Navigation and Chromium UIA updates are asynchronous. Observe the same
    # task document twice before looking for its native Continue button.
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMs)
    $last = ''
    $stable = 0
    do {
        $document = Find-Target
        $key = if ($null -ne $document) { Runtime-Key $document } else { '' }
        if ($key -and $key -eq $last) { $stable++ } elseif ($key) { $last = $key; $stable = 1 } else { $stable = 0 }
        if ($stable -ge 2) {
            return [pscustomobject]@{Document=$document; Key=$key}
        }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    Skip 'target_not_visible'
}
function Assert-Target {
    Assert-Account
    $document = Find-Target
    if ($null -eq $document) { Skip 'target_changed' }
    if (@(Find-Controls $document @('停止','Stop') $buttonType).Count -gt 0) { Skip 'task_already_running' }
    return $document
}
function Native-Continue($document) {
    # Only actions owned by this task document; never infer ownership from an
    # editor's position or choose a generic Start button in the surrounding UI.
    $names = @('继续','继续生成','继续回答','继续响应','继续对话',
        'Continue','Continue generating','Continue response','Continue conversation')
    return @(Find-Controls $document $names $buttonType $true)
}

function Resume-Task($document) {
    $document = Assert-Target
    $originalKey = Runtime-Key $document
    if (-not $originalKey) { Skip 'target_changed' }
    # The button can render just after the task document.
    $deadline = [DateTime]::UtcNow.AddMilliseconds(1500)
    do {
        $buttons = @(Native-Continue $document)
        if ($buttons.Count -gt 0) { break }
        if ([DateTime]::UtcNow -ge $deadline) { break }
        Start-Sleep -Milliseconds 250
        $document = Assert-Target
        if ((Runtime-Key $document) -ne $originalKey) { Skip 'target_changed' }
    } while ($true)
    if ($buttons.Count -gt 1) { Skip 'native_continue_ambiguous' }
    if ($buttons.Count -eq 1) {
        if (-not $buttons[0].Current.IsEnabled) { Skip 'native_continue_not_ready' }
        if ($DryRun) { Write-Output 'ready:native_continue'; return }
        $current = Assert-Target
        if ((Runtime-Key $current) -ne $originalKey) { Skip 'target_changed' }
        $buttonKey = Runtime-Key $buttons[0]
        if (-not $buttonKey) { Skip 'target_changed' }
        $currentButtons = @(Native-Continue $current)
        if ($currentButtons.Count -ne 1 -or
            (Runtime-Key $currentButtons[0]) -ne $buttonKey) { Skip 'target_changed' }
        if (-not $currentButtons[0].Current.IsEnabled) { Skip 'native_continue_not_ready' }
        $invoke = $currentButtons[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        Assert-Account
        $script:actionStarted = $true
        $invoke.Invoke()
        Write-Output 'invoked:native_continue'
        return
    }
    Skip 'native_continue_unavailable'
}
try {
    if (-not $NavigateOnly -and $Action -ne 'interrupted') { Skip 'bridge_required' }
    Assert-Account
    $deadline = [DateTime]::UtcNow.AddSeconds(6)
    do {
        $windows = @(Existing-Windows)
        if ($windows.Count -eq 0) { Skip 'desktop_not_running' }
        $foreground = [NXResumeWindow]::GetForegroundWindow()
        $script:pin = Resolve-ResumeWindow $windows $foreground
        if ($null -ne $script:pin -or -not $WaitForTarget) { break }
        Start-Sleep -Milliseconds 250
        Assert-Account
    } while ([DateTime]::UtcNow -lt $deadline)
    Write-Output ('location:' + ($script:locationEvidence | ConvertTo-Json -Compress))
    if ($null -eq $script:pin) {
        Skip $script:locationReason
    }
    $document = Find-Target
    if ($null -eq $document) {
        # Select the unique sidebar entry INSIDE the pinned window. Never call
        # an external protocol handler, which could launch another instance.
        if ($DryRun) { Skip 'target_not_visible' }
        # Navigation never submits text; keep the task's existing editor intact.
        $window = Pinned-Window
        if ($null -eq $window) { Skip 'target_changed' }
        $entries = @()
        foreach ($item in (@(Visible-Controls $window $buttonType) + @(Visible-Controls $window $linkType))) {
            try {
                if ($item.Current.ControlType -in @($buttonType,$linkType) -and
                    -not $item.Current.IsOffscreen -and $item.Current.IsEnabled -and
                    $item.Current.Name.StartsWith($TitlePrefix,[StringComparison]::Ordinal)) { $entries += $item }
            } catch { }
        }
        if ($entries.Count -ne 1) { Skip 'target_not_visible' }
        Assert-Account
        $entries[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        $deadline = [DateTime]::UtcNow.AddSeconds(12)
        do {
            Start-Sleep -Milliseconds 250
            $document = Find-Target
        } while ($null -eq $document -and [DateTime]::UtcNow -lt $deadline)
        if ($null -eq $document) { Skip 'target_not_visible' }
    }
    if ($NavigateOnly) {
        Assert-Account
        if ($null -eq (Find-Target)) { Skip 'target_changed' }
        if (-not $DryRun) { $null = [NXResumeWindow]::SetForegroundWindow($script:pin.Hwnd) }
        Write-Output 'opened:existing_task'; exit 0
    }
    $ready = Wait-ResumeReady
    Resume-Task $ready.Document
    exit 0
} catch { Skip 'desktop_error' }
