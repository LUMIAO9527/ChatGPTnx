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
Add-Type -AssemblyName WindowsBase
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Diagnostics;
using System.Threading;
public static class NXResumeWindow {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [StructLayout(LayoutKind.Sequential)] public struct Point { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] struct MouseInput {
        public int X, Y; public uint Data, Flags, Time; public UIntPtr Extra;
    }
    [StructLayout(LayoutKind.Sequential)] struct Input { public uint Type; public MouseInput Mouse; }
    [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
    [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr window, uint flags);
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] static extern int GetSystemMetrics(int index);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    [DllImport("user32.dll", SetLastError=true)] static extern uint SendInput(uint count, Input[] inputs, int size);
    public static int NormalizeCoordinate(int value, int origin, int size) {
        if (size < 2 || value < origin || (long)value >= (long)origin + size)
            throw new ArgumentOutOfRangeException("value");
        return (int)Math.Round(((double)value - origin) * 65535 / (size - 1));
    }
    public static int Click(IntPtr window, int x, int y) {
        IntPtr previous = IntPtr.Zero;
        try {
            try { previous = SetThreadDpiAwarenessContext(new IntPtr(-4)); }
            catch (EntryPointNotFoundException) { }
            // All rejection paths precede input. Never click through an overlay
            // or combine the action with a user's held mouse/modifier key.
            if (!IsWindow(window) || GetForegroundWindow() != window ||
                GetAncestor(WindowFromPoint(new Point { X=x, Y=y }), 2) != window) return 0;
            foreach (int key in new int[] {1,2,4,5,6,16,17,18,91,92})
                if ((GetAsyncKeyState(key) & 0x8000) != 0) return 0;
            int left=GetSystemMetrics(76), top=GetSystemMetrics(77);
            int width=GetSystemMetrics(78), height=GetSystemMetrics(79);
            if (width < 2 || height < 2 || x < left || y < top ||
                (long)x >= (long)left+width || (long)y >= (long)top+height) return 0;
            Input[] inputs = new Input[3];
            inputs[0].Mouse.X = NormalizeCoordinate(x, left, width);
            inputs[0].Mouse.Y = NormalizeCoordinate(y, top, height);
            inputs[0].Mouse.Flags = 0x0001 | 0x8000 | 0x4000; // move, absolute, virtual desktop
            inputs[1].Mouse.Flags = 0x0002;
            inputs[2].Mouse.Flags = 0x0004;
            uint sent = SendInput(3, inputs, Marshal.SizeOf(typeof(Input)));
            // A partially injected sequence has an unknown action outcome.
            // Release an injected down event without issuing another down.
            if (sent == 2) SendInput(1, new Input[] { inputs[2] }, Marshal.SizeOf(typeof(Input)));
            return (int)sent;
        } finally {
            if (previous != IntPtr.Zero) SetThreadDpiAwarenessContext(previous);
        }
    }
}

'@
$tree = [System.Windows.Automation.TreeScope]
$element = [System.Windows.Automation.AutomationElement]
$buttonType = [System.Windows.Automation.ControlType]::Button
$documentType = [System.Windows.Automation.ControlType]::Document
$linkType = [System.Windows.Automation.ControlType]::Hyperlink
$script:actionStarted = $false

function Skip([string]$Reason) {
    # An error after input cannot be retried automatically: the click may
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
        if ($stable -ge 2) { return }
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
        'Continue','Continue generating','Continue response','Continue conversation','Resume')
    return @(Find-Controls $document $names $buttonType $true)
}

function Focus-ResumeWindow {
    $null = [NXResumeWindow]::SetForegroundWindow($script:pin.Hwnd)
    $deadline = [DateTime]::UtcNow.AddMilliseconds(1500)
    do {
        Assert-Account
        if ($null -eq (Pinned-Window)) { Skip 'target_changed' }
        if ([NXResumeWindow]::GetForegroundWindow() -eq $script:pin.Hwnd) { return }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    Skip 'native_continue_not_ready'
}
function Native-ClickPoint($document, $button) {
    $point = [System.Windows.Point]::new(0,0)
    try {
        if (-not $button.TryGetClickablePoint([ref]$point) -or
            -not $button.Current.BoundingRectangle.Contains($point) -or
            -not $document.Current.BoundingRectangle.Contains($point)) { Skip 'native_continue_not_ready' }
        $key = Runtime-Key $button
        $hit = $element::FromPoint($point)
        # Chromium may expose a child icon at the point. Its owning button
        # must be the exact control that was revalidated in this task.
        for ($depth=0; $null -ne $hit -and $depth -lt 16; $depth++) {
            if ($key -and (Runtime-Key $hit) -eq $key) {
                return [pscustomobject]@{X=[int][Math]::Round($point.X); Y=[int][Math]::Round($point.Y)}
            }
            $hit = [System.Windows.Automation.TreeWalker]::RawViewWalker.GetParent($hit)
        }
    } catch { Skip 'native_continue_not_ready' }
    Skip 'native_continue_not_ready'
}
function Send-ContinueClick($point) {
    return [NXResumeWindow]::Click($script:pin.Hwnd, $point.X, $point.Y)
}
function Invoke-NativeClick($point) {
    Assert-Account
    $script:actionStarted = $true
    $sent = Send-ContinueClick $point
    if ($sent -eq 0) {
        $script:actionStarted = $false
        Skip 'native_continue_not_ready'
    }
    if ($sent -ne 3) { Skip 'native_continue' }
    Write-Output 'clicked:native_continue'
}
function Resume-Task {
    # Activating Chromium can rebuild the accessibility tree for the same task.
    # Capture the document and button after focus, using the original pinned window.
    if (-not $DryRun) { Focus-ResumeWindow }
    Wait-ResumeReady
    $deadline = [DateTime]::UtcNow.AddMilliseconds(1500)
    $failure = 'native_continue_unavailable'
    do {
        $document = Assert-Target
        $documentKey = Runtime-Key $document
        if (-not $documentKey) { Skip 'target_changed' }
        $buttons = @(Native-Continue $document)
        if ($buttons.Count -gt 1) { Skip 'native_continue_ambiguous' }
        if ($buttons.Count -eq 1) {
            $failure = 'native_continue_not_ready'
            if ($buttons[0].Current.IsEnabled) {
                $buttonKey = Runtime-Key $buttons[0]
                if (-not $buttonKey) { Skip 'target_changed' }
                $verified = Assert-Target
                $verifiedButtons = @(Native-Continue $verified)
                if ($verifiedButtons.Count -gt 1) { Skip 'native_continue_ambiguous' }
                if ((Runtime-Key $verified) -ne $documentKey -or $verifiedButtons.Count -ne 1 -or
                    (Runtime-Key $verifiedButtons[0]) -ne $buttonKey) {
                    # The pinned window still shows the exact task. Read fresh
                    # controls within the same deadline before issuing any input.
                    $failure = 'target_changed'
                } elseif ($verifiedButtons[0].Current.IsEnabled) {
                    if ($DryRun) { Write-Output 'ready:native_continue'; return }
                    $point = Native-ClickPoint $verified $verifiedButtons[0]
                    Invoke-NativeClick $point
                    return
                }
            }
        }
        if ([DateTime]::UtcNow -ge $deadline) { break }
        Start-Sleep -Milliseconds 150
    } while ($true)
    Skip $failure
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
    Resume-Task
    exit 0
} catch { Skip 'desktop_error' }
