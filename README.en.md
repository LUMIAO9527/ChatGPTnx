[简体中文](README.md) | **English**

<div align="center">
<img src="docs/images/nx-mark.png" width="88" alt="ChatGPTnx">
<h1>ChatGPTnx</h1>
<p><b>Automatic handoff · Task continuation · Configure n accounts for your workload</b></p>
<p>Keep a long task moving across the accounts you own. Switch accounts when quota runs out, then attempt to continue the original task.</p>

<img src="docs/images/badges/platform.svg" alt="Windows 10 | 11" height="20">
<img src="docs/images/badges/version.svg" alt="v1.4.1" height="20">
<img src="docs/images/badges/license.svg" alt="Source available to inspect; rights reserved" height="20">
</div>

ChatGPTnx is a lightweight Windows desktop utility that reduces the waiting and manual steps when a long task is interrupted by an account's usage limit. It brings account handoff, task continuation, quota information, and usage statistics into one tray app.

## Video introduction

Chinese narration and subtitles.

https://github.com/user-attachments/assets/e1d24f80-0716-4bba-a024-7058e5c0b2e0

## Features

- **Automatic handoff:** Switch to a participating account with available quota when the current account runs out. You can also switch manually, choose participating accounts, or schedule a cancellable handoff after an account's quota recovers.
- **Relay preheat:** During active desktop work, start selected spare Plus accounts' five-hour windows with a tiny request and prepare the next round after recovery. Off by default; no desktop login changes or repeat requests within the same window.
- **Task continuation:** After a switch, attempt to resume the original desktop task. Configure a continuation message and review successful, skipped, and unresolved results separately. Identified background agents do not trigger independent desktop continuation.
- **Quotas and usage:** See each account's remaining quota, reset times, and token usage. Temporary query failures retain known quotas consistently across views and handoff decisions. Normal queries and preheat share pause and cooldown rules.
- **Credential protection and diagnostics:** Protect account snapshots with Windows current-user encryption, and preview or copy a redacted diagnostic summary.
- **Sign-in and updates:** Keep the panel visible during sign-in, automatically verify and save completed sign-ins, and check for official GitHub updates from Settings.
- **Lightweight desktop controls:** Keep the app in the Windows tray, with notifications, keyboard shortcuts, and light and dark themes.

### Keeping long tasks moving

Automatic handoff and task continuation are separate settings. When the current account reaches its limit, handoff switches to an eligible account. Continuation then checks the original desktop task and attempts to resume it there. Continuation depends on the task's state and may wait or report a failure; it cannot guarantee that every task will resume.

**n is the number of your own accounts you choose to configure for your workload.** Start with a few and adjust the participating accounts as your usage changes. For example, five Plus accounts can take turns in a rotation so a long task spends less time waiting for one account's quota to reset.

The quota overview and usage statistics help you see which account is available and how much capacity you actually use.

## Screenshots

### Account handoff and task continuation

| Home · Current account and next handoff | Account handoff · Confirm the next account | Task continuation · Review results |
| --- | --- | --- |
| <img src="docs/images/home-live.png" width="260" alt="Home: current account, remaining quota, and next handoff"> | <img src="docs/images/relay-confirm-live.png" width="260" alt="Confirm the next account and start handoff"> | <img src="docs/images/resume-live.png" width="260" alt="Task continuation records"> |

### Quotas and usage

| Quota overview | Personal usage | Account details |
| --- | --- | --- |
| <img src="docs/images/quota-live.png" width="260" alt="Quota overview for all accounts"> | <img src="docs/images/usage-live.png" width="260" alt="Personal token usage and trends"> | <img src="docs/images/detail-live.png" width="260" alt="Account details"> |

### Settings and appearance

| Settings | Dark theme | Add an account |
| --- | --- | --- |
| <img src="docs/images/settings-live.png" width="260" alt="Settings for handoff and task continuation"> | <img src="docs/images/home-dark-current.png" width="260" alt="Home screen in dark theme"> | <img src="docs/images/add-account-live.png" width="260" alt="Add an account: open the desktop sign-in window and confirm the account"> |

## Download and run

The current version is **v1.4.1**. Open `ChatGPTnx-v1.4.1.html` at the project root for all current pages and states.

v1.4.1 refines page animations and control sizing for smoother navigation and expanding or collapsing sections. Checked in light and dark appearances, including rapid back-and-forth navigation.

Download `ChatGPTnx.exe` from the [v1.4.1 release](https://github.com/LUMIAO9527/ChatGPTnx/releases/tag/v1.4.1). The release also provides `ChatGPTnx-v1.4.1-source.zip` for source inspection. You need 64-bit Windows 10 or 11, the installed ChatGPT desktop app with a signed-in account, Microsoft .NET Framework 4.6.2 or later, and Microsoft Edge WebView2 Runtime.

1. Put the EXE in its own writable folder and launch it. Open the panel from the system tray.
2. Select **Add account** and sign in to ChatGPT. The app automatically verifies and saves the account. If verification is temporarily unavailable, use **Retry verification** in the panel.
3. Try one manual handoff with **Next account**. Then enable automatic handoff in Settings and choose the participating accounts.
4. Enable **Automatically continue tasks after switching accounts** if you want task continuation. Configure a continuation message if needed, and check the task continuation records for results.

Closing the panel only hides it; the app keeps running in the tray. Use the tray menu to exit completely.

## Data and privacy

Account snapshots, archived snapshots, and transaction recovery backups use Windows current-user encryption and restricted file permissions. Encrypted snapshots cannot be copied directly to another Windows user. The official desktop app's active authentication file keeps its existing format.

Account and runtime data are stored next to the EXE. Keep that folder private and do not upload it publicly. When reporting an issue, use the diagnostic summary in Settings. It excludes email addresses, tokens, task content, and local paths, and is never uploaded automatically.

See [USAGE.md](USAGE.md) (Chinese) for query recovery, continuation behavior, and rollback instructions. Before restoring an executable that cannot read encrypted snapshots, restore the credential format using the documented recovery tool.

## License

The source is available to inspect. Use and redistribution are governed by the [LICENSE](LICENSE); all rights are reserved. ChatGPTnx is an independent tool and is not affiliated with or endorsed by OpenAI.

## Unified offline demo and debugging

Open `ChatGPTnx-v1.4.1.html` at the project root or run `preview.cmd`. It includes the current UI, searchable scenarios, themes, simulated login/update states, and safe debug-report exports. The preview automatically fits and centers in the available space; select 100% to inspect its actual dimensions. It uses synthetic data and does not access local accounts or perform actual desktop, download, or installation actions.

The console can check all light/dark scenarios and record intermediate navigation frames, including interrupted returns, inline disclosures, floating notices, passive refreshes, and long release notes. A shared rule prioritizes information-card backgrounds, then main buttons or account avatars; unrelated pages use a grouped body transition.

Regenerate it with `python tools/build_explorer.py` after editing the UI; `build.cmd` also generates it. Native Windows behavior requires separate acceptance.
