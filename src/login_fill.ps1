# Fill the ChatGPT sign-in form one stage per call, then stop.
#
# Values arrive on stdin as JSON so no password ever appears on a command line,
# in the process list, or in an environment block:
#
#   '{"email":"a@b.com","password":"...","code":"123456"}' | powershell -File login_fill.ps1 -Stage email
#
# The helper never guesses: it reports the stage it can prove is on screen and
# refuses to type when that stage is not the requested one. Anything it cannot
# classify (phone verification, e-mail codes, human checks) is reported so the
# caller can stop and wait for the user.
param(
    [ValidateSet('probe', 'launch', 'email', 'password', 'otp')][string]$Stage = 'probe',
    [string]$WindowHandle,
    [switch]$DryRun,
    [switch]$SurfaceFixture
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
[Console]::InputEncoding = New-Object Text.UTF8Encoding($false)

function Write-Result([hashtable]$Value) {
    $Value | ConvertTo-Json -Compress -Depth 4
    exit 0
}

# ---- payload -------------------------------------------------------------
$payload = @{}
try {
    $raw = [Console]::In.ReadToEnd()
    if (-not [string]::IsNullOrWhiteSpace($raw)) { $payload = $raw | ConvertFrom-Json }
} catch { Write-Result @{ ok = $false; step = 'unknown'; error = 'bad_payload' } }

. (Join-Path $PSScriptRoot 'login_surface.ps1')
if ($SurfaceFixture) {
    $result = Get-NXLoginSurface -Url $payload.url -Edits @($payload.edits) -Text $payload.text -Buttons @($payload.buttons) -AppHost ([bool]$payload.app)
    Write-Result $result
}

# ---- native helpers ------------------------------------------------------
if (-not ('NXLoginFill' -as [type])) {
    Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class NXLoginFill {
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
    [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT {
        public ushort wVk, wScan; public uint dwFlags, time; public UIntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT {
        public int dx, dy; public uint mouseData, dwFlags, time; public UIntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Explicit, Size = 40)] struct INPUT {
        [FieldOffset(0)] public uint type;
        [FieldOffset(8)] public KEYBDINPUT ki;
        [FieldOffset(8)] public MOUSEINPUT mi; }

    [DllImport("user32.dll")] static extern uint SendInput(uint n, INPUT[] p, int cb);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);

    const uint KEYUP = 0x0002, UNICODE = 0x0004, SCAN = 0x0008, DOWN = 0x0001, ABSOLUTE = 0x8000;

    static INPUT KeyInput(ushort vk, ushort scan, uint flags, bool unicode) {
        var item = new INPUT { type = 1 };
        item.ki.wVk = vk; item.ki.wScan = scan;
        item.ki.dwFlags = flags | (unicode ? UNICODE : 0);
        return item;
    }

    // Refuse to inject while the user is holding anything: a password half typed
    // into another window is worse than a stage that simply reports failure.
    public static bool UserIdle() {
        foreach (int key in new int[] { 1, 2, 4, 5, 6, 16, 17, 18, 91, 92 })
            if ((GetAsyncKeyState(key) & 0x8000) != 0) return false;
        return true;
    }

    // Typing is the only reliable path: Chromium refuses ValuePattern writes on
    // an IsPassword field, and React inputs ignore a bare value assignment.
    public static uint TypeText(string text) {
        var list = new List<INPUT>();
        foreach (char ch in text) {
            list.Add(KeyInput(0, ch, 0, true));
            list.Add(KeyInput(0, ch, KEYUP, true));
        }
        if (list.Count == 0) return 0;
        return SendInput((uint)list.Count, list.ToArray(), Marshal.SizeOf(typeof(INPUT)));
    }

    public static uint ClearField() {
        var list = new List<INPUT>();
        list.Add(KeyInput(0x11, 0, 0, false));          // Ctrl down
        list.Add(KeyInput(0x41, 0, 0, false));          // A down
        list.Add(KeyInput(0x41, 0, KEYUP, false));      // A up
        list.Add(KeyInput(0x11, 0, KEYUP, false));      // Ctrl up
        list.Add(KeyInput(0x2E, 0, 0, false));          // Delete down
        list.Add(KeyInput(0x2E, 0, KEYUP, false));      // Delete up
        return SendInput((uint)list.Count, list.ToArray(), Marshal.SizeOf(typeof(INPUT)));
    }

    // Fallback for a control that exposes a rectangle but no InvokePattern.
    public static uint ClickAt(int screenX, int screenY) {
        int left = GetSystemMetrics(76), top = GetSystemMetrics(77);
        int width = GetSystemMetrics(78), height = GetSystemMetrics(79);
        if (width < 2 || height < 2) return 0;
        if (screenX < left || screenY < top ||
            (long)screenX >= (long)left + width || (long)screenY >= (long)top + height) return 0;
        var list = new List<INPUT>();
        var move = new INPUT { type = 0 };
        move.mi.dx = (int)Math.Round((double)(screenX - left) * 65535 / (width - 1));
        move.mi.dy = (int)Math.Round((double)(screenY - top) * 65535 / (height - 1));
        move.mi.dwFlags = ABSOLUTE | 0x4000;
        list.Add(move);
        var down = new INPUT { type = 0 }; down.mi.dwFlags = DOWN; list.Add(down);
        var up = new INPUT { type = 0 }; up.mi.dwFlags = KEYUP; list.Add(up);
        return SendInput((uint)list.Count, list.ToArray(), Marshal.SizeOf(typeof(INPUT)));
    }

    [DllImport("user32.dll")] static extern int GetSystemMetrics(int index);
}
'@
}

Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName WindowsBase

$AE = [System.Windows.Automation.AutomationElement]
$descendants = [System.Windows.Automation.TreeScope]::Descendants
$editType = [System.Windows.Automation.ControlType]::Edit
$buttonType = [System.Windows.Automation.ControlType]::Button
$textType = [System.Windows.Automation.ControlType]::Text

# ---- read one visible authentication document -----------------------------
function Get-DocumentValue($document) {
    try {
        $value = $document.GetCurrentPropertyValue([System.Windows.Automation.ValuePattern]::ValueProperty, $true)
        if ($value -ne $AE::NotSupported -and $value -is [string]) { return $value }
    } catch { }
    try {
        $pattern = $document.GetCurrentPattern([System.Windows.Automation.LegacyIAccessiblePattern]::Pattern)
        return [string]$pattern.Current.Value
    } catch { return '' }
}

function Read-Surface($window, [bool]$AppHost) {
    try {
        $documents = $window.FindAll($descendants,
            (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty,
                [System.Windows.Automation.ControlType]::Document)))
        foreach ($document in $documents) {
            if ($document.Current.IsOffscreen) { continue }
            $url = Get-DocumentValue $document
            $fields = @($document.FindAll($descendants,
                (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $editType))))
            $buttons = @($document.FindAll($descendants,
                (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $buttonType))))
            $visibleButtons = @($buttons | Where-Object { $_.Current.IsEnabled -and -not $_.Current.IsOffscreen })
            $descriptions = @($fields | ForEach-Object {
                @{name=$_.Current.Name;id=$_.Current.AutomationId;password=$_.Current.IsPassword;
                  enabled=$_.Current.IsEnabled;offscreen=$_.Current.IsOffscreen}
            })
            $texts = $document.FindAll($descendants,
                (New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $textType)))
            $words = @($texts | Select-Object -First 150 | ForEach-Object { $_.Current.Name }) -join ' '
            $names = @($visibleButtons | ForEach-Object { $_.Current.Name })
            $info = Get-NXLoginSurface -Url $url -Edits $descriptions -Text $words -Buttons $names -AppHost $AppHost
            if ($info.surface -eq 'auth' -or $info.step -eq 'launch') {
                return @{window=$window;document=$document;url=$url;fields=$fields;buttons=$visibleButtons;
                         info=$info;app=$AppHost}
            }
        }
    } catch { }
    return $null
}

function Find-SignInWindow {
    $found = @()
    foreach ($name in @('chatgpt', 'chrome', 'msedge', 'brave', 'firefox')) {
        foreach ($process in [System.Diagnostics.Process]::GetProcessesByName($name)) {
            try {
                $handle = $process.MainWindowHandle
                if ($handle -eq [IntPtr]::Zero) { continue }
                if ($WindowHandle -and $handle -ne [IntPtr][long]$WindowHandle) { continue }
                $record = Read-Surface ($AE::FromHandle($handle)) ($name -eq 'chatgpt')
                if ($record) { $found += $record }
            } catch { }
        }
    }
    $hosted = @($found | Where-Object { $_.info.surface -eq 'auth' })
    if ($hosted.Count) { $found = $hosted }
    if ($found.Count -eq 1) { return $found[0] }
    $foreground = [NXLoginFill]::GetForegroundWindow()
    $active = @($found | Where-Object { [IntPtr]$_.window.Current.NativeWindowHandle -eq $foreground })
    if ($active.Count -eq 1) { return $active[0] }
    return $null
}

$record = Find-SignInWindow
if (-not $record) { Write-Result @{ok=$false;step='unknown';hint='none';error='no_window'} }
$info = $record.info
if ($Stage -eq 'probe') { Write-Result @{ok=$true;step=$info.step;hint=$info.hint;surface=$info.surface;edits=$record.fields.Count} }
if ($Stage -ne $info.step) { Write-Result @{ok=$false;step=$info.step;hint=$info.hint;error='stage_mismatch'} }
if ($info.hint -in @('phone','human_check','email_code')) { Write-Result @{ok=$false;step=$info.step;hint=$info.hint;error=$info.hint} }
if ($Stage -eq 'otp' -and $info.hint -ne 'authenticator') { Write-Result @{ok=$false;step='otp';error='otp_unrecognized'} }
if ($DryRun) { Write-Result @{ok=$true;step=$info.step;hint=$info.hint;dry_run=$true;clicked=$false} }

$handle = [IntPtr]$record.window.Current.NativeWindowHandle
if ([NXLoginFill]::GetForegroundWindow() -ne $handle) {
    [void][NXLoginFill]::SetForegroundWindow($handle)
    Start-Sleep -Milliseconds 150
}
if ([NXLoginFill]::GetForegroundWindow() -ne $handle) { Write-Result @{ok=$false;error='not_foreground'} }
if (-not [NXLoginFill]::UserIdle()) { Write-Result @{ok=$false;error='user_active'} }
$observed = Read-Surface $record.window $record.app
if (-not $observed -or $observed.url -ne $record.url -or $observed.info.step -ne $Stage) { Write-Result @{ok=$false;error='stage_mismatch'} }
$record = $observed

if ($Stage -ne 'launch') {
    $value = if ($Stage -eq 'email') { [string]$payload.email } elseif ($Stage -eq 'password') { [string]$payload.password } else { [string]$payload.code }
    if ([string]::IsNullOrEmpty($value) -or $record.info.index -lt 0) { Write-Result @{ok=$false;error='bad_payload'} }
    $target = $record.fields[$record.info.index]
    try { $target.SetFocus() } catch { Write-Result @{ok=$false;error='no_focus'} }
    Start-Sleep -Milliseconds 100
    if (-not $target.Current.HasKeyboardFocus -or [NXLoginFill]::GetForegroundWindow() -ne $handle) { Write-Result @{ok=$false;error='no_focus'} }
    if ([NXLoginFill]::ClearField() -ne 6) { Write-Result @{ok=$false;error='no_input'} }
    if ([NXLoginFill]::TypeText($value) -ne ($value.Length * 2)) { Write-Result @{ok=$false;error='no_input'} }
    Start-Sleep -Milliseconds 100
}

$final = Read-Surface $record.window $record.app
if (-not $final -or $final.url -ne $record.url -or $final.info.step -ne $Stage) { Write-Result @{ok=$true;step=$Stage;clicked=$false} }
$names = if ($Stage -eq 'launch') { @('Continue to sign in','继续登录','Sign in with ChatGPT','使用 ChatGPT 登录') }
         else { @('继续','下一步','继续登录','登录','提交','验证','Continue','Next','Log in','Sign in','Submit','Verify') }
$submit = @($final.buttons | Where-Object { $_.Current.Name -in $names })
$clicked = $false
if ($submit.Count -eq 1 -and [NXLoginFill]::GetForegroundWindow() -eq $handle) {
    try {
        $pattern = $submit[0].GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pattern.Invoke(); $clicked = $true
    } catch { }
}
Write-Result @{ok=$true;step=$Stage;hint=$info.hint;clicked=$clicked}
