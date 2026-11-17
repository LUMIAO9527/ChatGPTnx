[简体中文](README.md) · **English**

<div align="center">
  <img src="docs/images/nx-mark.png" width="72" alt="">
  <h1>ChatGPTnx</h1>
  <p>Manage ChatGPT accounts, quotas, and local task continuation from the Windows tray.</p>
  <p><a href="https://github.com/LUMIAO9527/ChatGPTnx/releases/latest/download/ChatGPTnx.exe"><b>Download ChatGPTnx.exe</b></a> · <a href="https://github.com/LUMIAO9527/ChatGPTnx/releases/latest">Release notes and offline demo</a> · <a href="USAGE.md">User guide (Chinese)</a></p>
  <p><img src="docs/images/badges/platform.svg" alt="Windows 10 and 11" height="20"> <img src="docs/images/badges/version.svg" alt="Current release" height="20"></p>
  <img src="docs/images/home-dark.png" width="220" alt="Dark home panel showing the active account, quota, and next account">
  <img src="docs/images/home-light.png" width="220" alt="Light home panel showing the quotas for other accounts">
</div>

## Getting started

Requires 64-bit Windows 10 or 11, the ChatGPT desktop app with a signed-in account, Microsoft .NET Framework 4.6.2 or later, and Microsoft Edge WebView2 Runtime.

1. Launch `ChatGPTnx.exe` and choose a program folder. Open NX from the Windows tray after setup.
2. Select **Add account** and sign in through ChatGPT.
3. Select **Next account** to switch. Enable automatic handoff and task continuation in Settings.
4. Install updates from **Settings → About → Version update**.

## Screenshots

The app and demo use a Chinese interface.

| Confirm a handoff | Review continuation | Compare quotas |
| :---: | :---: | :---: |
| <img src="docs/images/handoff-confirm.png" width="205" alt="Confirm the active and next accounts before handoff"> | <img src="docs/images/continue-history.png" width="205" alt="Task continuation results, timestamps, and retry control"> | <img src="docs/images/quota-overview.png" width="205" alt="Quota and reset times across accounts"> |

| Review usage | Manage passwords and 2FA | Check for updates |
| :---: | :---: | :---: |
| <img src="docs/images/personal-usage.png" width="205" alt="Date range, token totals, and usage trends"> | <img src="docs/images/account-security.png" width="205" alt="Password, authenticator, and code in account details"> | <img src="docs/images/version-update.png" width="205" alt="Current version, check for updates button, and result"> |

## Data and source

To move to another computer, export a password-protected backup from **Settings → Accounts and data → Import and export**.

Download the source package, run `setup.cmd` to install dependencies, then run `build.cmd`. [Releases](https://github.com/LUMIAO9527/ChatGPTnx/releases/latest) · [Changelog](CHANGELOG.md) · [License](LICENSE)
