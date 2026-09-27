# Operate only in an already-running, pinned ChatGPT window. Never replace editor
# text, touch the clipboard, launch a client, or spawn an app-server. Focus the
# composer, append the continuation message, then invoke Send once. Existing
# composer content and placeholder state are deliberately not inspected.
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
    [DllImport("user32.dll")] public static extern bool BlockInput(bool block);
    [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
    [DllImport("user32.dll", SetLastError=true)] static extern uint SendInput(uint count, INPUT[] input, int size);
    [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint size, time; }
    [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT { public ushort vk, scan; public uint flags, time; public UIntPtr extra; }
    [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT { public int dx, dy; public uint data, flags, time; public UIntPtr extra; }
    [StructLayout(LayoutKind.Explicit)] struct INPUTUNION {
        [FieldOffset(0)] public KEYBDINPUT keyboard;
        [FieldOffset(0)] public MOUSEINPUT mouse;
    }
    [StructLayout(LayoutKind.Sequential)] struct INPUT { public uint type; public INPUTUNION data; }
    public static bool Idle() {
        LASTINPUTINFO last = new LASTINPUTINFO(); last.size=(uint)Marshal.SizeOf(last);
        if (!GetLastInputInfo(ref last) || unchecked((uint)Environment.TickCount-last.time)<1000) return false;
        for(int key=1;key<255;key++) if((GetAsyncKeyState(key)&0x8000)!=0) return false;
        return true;
    }
    // One input batch; no VK codes, Enter, deletion, selection or shortcuts.
    public static bool AppendUnicode(string text, IntPtr expected) {
        if(GetForegroundWindow()!=expected) return false;
        INPUT[] input=new INPUT[text.Length*2];
        for(int i=0;i<text.Length;i++) {
            input[i*2].type=1; input[i*2].data.keyboard.scan=text[i]; input[i*2].data.keyboard.flags=4;
            input[i*2+1]=input[i*2]; input[i*2+1].data.keyboard.flags=6;
        }
        return SendInput((uint)input.Length,input,Marshal.SizeOf(typeof(INPUT)))==input.Length;
    }
}

'@
$tree = [System.Windows.Automation.TreeScope]
$element = [System.Windows.Automation.AutomationElement]
$buttonType = [System.Windows.Automation.ControlType]::Button
$editType = [System.Windows.Automation.ControlType]::Edit
$documentType = [System.Windows.Automation.ControlType]::Document
$linkType = [System.Windows.Automation.ControlType]::Hyperlink
$script:writeStarted = $false

function Skip([string]$Reason) {
    if ($null -ne $script:inputGuard) { $script:inputGuard.Dispose(); $script:inputGuard = $null }
    # An error after writing/invoking cannot be retried automatically: acceptance
    # might already have happened even when the UIA call did not return.
    if ($script:writeStarted) { Write-Output ('uncertain:' + $Reason) }
    else { Write-Output ('skip:' + $Reason) }
    exit 2
}
function Assert-Account {
    $stage = 'auth_hash'
    try {
        $hash = (Get-FileHash -LiteralPath $AuthFile -Algorithm SHA256).Hash
        if ($hash -ine $ExpectedAuthHash) { Skip 'account_changed' }
        if ($SettingsFile) {
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
    # Python has already established that the title identifies one task.
    # Multiple windows showing that same task are equivalent destinations.
    if ($documents.Count -gt 0 -and $valid.Count -gt 0) { return $valid[0] }
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
function Composer-Trim([string]$Raw) {
    $padding = '[\s\u00AD\u034F\u061C\u180E\u200B-\u200F\u202A-\u202E\u2060-\u2064\u2066-\u2069\uFEFF]'
    return ($Raw -replace ('^' + $padding + '+|' + $padding + '+$'), '')
}
function Composer-TextState([string]$Raw, [string]$AccessibleName) {
    $text = Composer-Trim $Raw
    if ($text.Length -eq 0) { return 'empty' }
    $labels = @((Composer-Trim $AccessibleName), 'Ask anything', '随心输入', 'Message ChatGPT')
    foreach ($label in $labels) { if ($label -and $text.Equals($label, [StringComparison]::OrdinalIgnoreCase)) { return 'unknown' } }
    return 'present'
}
function Resolve-ComposerState([string]$ValueState, [string]$TextState) {
    if ($ValueState -eq 'empty') { if ($TextState -eq 'present') { return 'unknown' }; return 'empty' }
    if ($ValueState -eq 'present') { if ($TextState -eq 'empty') { return 'unknown' }; return 'present' }
    if ($ValueState -eq 'unavailable') { if ($TextState -in @('empty','present')) { return $TextState }; return 'unknown' }
    if ($TextState -eq 'present') { return 'present' }
    return 'unknown'
}
function Find-Composer($document) {
    $editors = @()
    $visibleEditors = @()
    foreach ($item in (Visible-Controls $document $editType)) {
        try {
            if ($item.Current.ControlType -eq $editType -and -not $item.Current.IsOffscreen -and
                $item.Current.IsEnabled) { $visibleEditors += $item }
            if ($item.Current.ControlType -eq $editType -and -not $item.Current.IsOffscreen -and
                $item.Current.IsEnabled -and
                ([string]$item.Current.Name).Trim() -in @('随心输入','Ask anything','Message ChatGPT')) { $editors += $item }
        } catch { }
    }
    # Placeholder and accessible name can vary with app version and task state.
    # A single editable control in the identified task document needs no text read.
    if ($editors.Count -eq 0 -and $visibleEditors.Count -eq 1) { $editors = $visibleEditors }
    if ($editors.Count -ne 1) { Skip 'composer_unavailable' }
    return [pscustomobject]@{Editor=$editors[0]}
}
function Valid-ResumeMessage([object]$message) {
    if ($message -isnot [string] -or [string]::IsNullOrWhiteSpace($message) -or
        $message -ne $message.Trim()) { return $false }
    $count = 0
    for ($i = 0; $i -lt $message.Length; $i++) {
        $category = [Globalization.CharUnicodeInfo]::GetUnicodeCategory($message, $i)
        if ($category -in @([Globalization.UnicodeCategory]::Control,
            [Globalization.UnicodeCategory]::Format,[Globalization.UnicodeCategory]::Surrogate,
            [Globalization.UnicodeCategory]::PrivateUse,[Globalization.UnicodeCategory]::OtherNotAssigned,
            [Globalization.UnicodeCategory]::LineSeparator,[Globalization.UnicodeCategory]::ParagraphSeparator)) { return $false }
        if ($category -eq [Globalization.UnicodeCategory]::SpaceSeparator -and $message[$i] -ne ' ') { return $false }
        if ([char]::IsHighSurrogate($message[$i])) {
            if ($i + 1 -ge $message.Length -or -not [char]::IsLowSurrogate($message[$i+1])) { return $false }
            $i++
        }
        $count++
    }
    return $count -ge 1 -and $count -le 200
}
function Get-ResumeMessage {
    $message = '继续'
    if ($SettingsFile) {
        try { $message = (Get-Content -LiteralPath $SettingsFile -Raw -Encoding UTF8 | ConvertFrom-Json).settings.resume_message }
        catch { Skip 'account_guard_unavailable' }
    }
    if (-not (Valid-ResumeMessage $message)) { Skip 'invalid_resume_message' }
    return $message
}
function Find-Send($document,$composer,[bool]$IncludeDisabled=$false) {
    return @(Find-Controls $document @('发送','Send','发送消息','Send message','提交','Submit') $buttonType $IncludeDisabled |
        Where-Object { [Math]::Abs($_.Current.BoundingRectangle.Top-$composer.Editor.Current.BoundingRectangle.Top) -le 250 })
}
function Send-ResumeMessage($document,$composer) {
    $message = Get-ResumeMessage
    if ($DryRun) { Write-Output 'ready:send_message'; return }
    # Deliberately ignore existing composer text and placeholder state. The user
    # requested the same fast path for empty and non-empty composers.
    if ([NXResumeWindow]::GetForegroundWindow() -ne $script:pin.Hwnd -and
        -not [NXResumeWindow]::SetForegroundWindow($script:pin.Hwnd)) { Skip 'input_focus_changed' }
    $composer.Editor.SetFocus()
    if (-not $composer.Editor.Current.HasKeyboardFocus) { Skip 'input_focus_changed' }
    Assert-Account
    $script:writeStarted = $true
    if (-not [NXResumeWindow]::AppendUnicode($message,$script:pin.Hwnd)) { Skip 'text_insertion_unconfirmed' }
    $deadline = [DateTime]::UtcNow.AddSeconds(3)
    do {
        $document = Assert-Target
        if ([NXResumeWindow]::GetForegroundWindow() -ne $script:pin.Hwnd -or
            -not $composer.Editor.Current.HasKeyboardFocus) { Skip 'input_focus_changed' }
        $send = @(Find-Send $document $composer)
        if ($send.Count -eq 1) { break }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($send.Count -ne 1) { Skip 'send_unavailable' }
    Assert-Account
    $send[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
    Write-Output 'invoked:send_message'
}
function Assert-Target {
    Assert-Account
    $document = Find-Target
    if ($null -eq $document) { Skip 'target_changed' }
    if (@(Find-Controls $document @('停止','Stop') $buttonType).Count -gt 0) { Skip 'task_already_running' }
    return $document
}
function Native-Continue($document, $composer) {
    $names = @('继续','继续生成','继续回答','继续响应','继续对话',
        'Continue','Continue generating','Continue response','Continue conversation','开始','Start')
    # A disabled Continue button still means the native action is present. It
    # must never cause a fallback message to be sent.
    $buttons = @(Find-Controls $document $names $buttonType $true)
    if ($buttons.Count -gt 0) { return $buttons }

    # In some ChatGPT desktop layouts the action is a sibling of the task
    # Document. Search the pinned window, restricted to the conversation's
    # horizontal area so sidebar actions cannot be selected.
    $window = Pinned-Window
    if ($null -eq $window) { Skip 'target_changed' }
    $editors = @(Visible-Controls $document $editType)
    if ($editors.Count -ne 1) { return @() }
    $editorRect = $editors[0].Current.BoundingRectangle
    $windowButtons = @(Find-Controls $window $names $buttonType $true)
    return @($windowButtons | Where-Object {
        $rect = $_.Current.BoundingRectangle
        $center = $rect.Left + $rect.Width / 2
        $center -ge $editorRect.Left - 150 -and
        $center -le $editorRect.Right + 150 -and
        $rect.Bottom -le $editorRect.Top + 100
    })
}
function Resume-Task($document,$composer) {
    # The button can render just after the task document. Check several times
    # before deciding that a text continuation is needed.
    $deadline = [DateTime]::UtcNow.AddMilliseconds(1500)
    do {
        $buttons = @(Native-Continue $document $composer)
        if ($buttons.Count -gt 0) { break }
        if ([DateTime]::UtcNow -ge $deadline) { break }
        Start-Sleep -Milliseconds 250
        $document = Assert-Target
    } while ($true)
    if ($buttons.Count -gt 1) { Skip 'native_continue_ambiguous' }
    if ($buttons.Count -eq 1) {
        if (-not $buttons[0].Current.IsEnabled) { Skip 'native_continue_not_ready' }
        if ($DryRun) { Write-Output 'ready:native_continue'; return }
        Assert-Account
        $script:writeStarted = $true
        $buttons[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        Write-Output 'invoked:native_continue'
        return
    }
    $composer = Find-Composer $document
    Send-ResumeMessage $document $composer
}
try {
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
        # Do not switch conversations while the user is actively typing. An
        # explicit Open task action is separate from automatic continuation.
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
    Start-Sleep -Milliseconds 250
    $document = Assert-Target
    Resume-Task $document $null
    exit 0
} catch { Skip 'desktop_error' }
