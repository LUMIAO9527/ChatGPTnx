**简体中文** · [English](README.en.md)

<div align="center">
  <img src="docs/images/nx-mark.png" width="72" alt="">
  <h1>ChatGPTnx</h1>
  <p>从 Windows 托盘管理 ChatGPT 账号、额度和本机任务接续。</p>
  <p><a href="https://github.com/LUMIAO9527/ChatGPTnx/releases/latest/download/ChatGPTnx.exe"><b>下载 ChatGPTnx.exe</b></a> · <a href="https://github.com/LUMIAO9527/ChatGPTnx/releases/latest">版本说明与离线演示</a> · <a href="USAGE.md">使用说明</a></p>
  <p><img src="docs/images/badges/platform.svg" alt="Windows 10 和 11" height="20"> <img src="docs/images/badges/version.svg" alt="当前发布版本" height="20"></p>
  <img src="docs/images/home-dark.png" width="220" alt="深色首页，显示当前账号、剩余额度和下一棒">
  <img src="docs/images/home-light.png" width="220" alt="浅色首页，显示其他账号的额度">
</div>

## 开始使用

需要 Windows 10 或 11（64 位）、已登录的 ChatGPT 桌面应用、Microsoft .NET Framework 4.6.2 或更新版本，以及 Microsoft Edge WebView2 Runtime。

1. 启动 `ChatGPTnx.exe`，选择程序文件夹。以后可从 Windows 托盘打开 NX。
2. 点击「添加账号」，在 ChatGPT 完成登录。NX 核验后保存该账号。
3. 用首页「下一棒」试一次手动接力，再到设置选择参与账号。按需开启自动接力和「切号后自动接续任务」。
4. 已在使用 NX 时，从「设置 → 关于 → 版本更新」检查并安装新版。

需要在同一台电脑切号接续的任务，应从本机项目以本机模式启动。NX 优先使用桌面端原生「继续」，并在接续记录显示结果。私有云端对话随其所属 ChatGPT 账号显示。

## 界面速览

截图使用合成账号和数据。完整页面、浅深色外观和交互可在 [发布页](https://github.com/LUMIAO9527/ChatGPTnx/releases/latest) 下载 HTML 离线演示。

| 确认账号接力 | 查阅接续记录 | 比较账号额度 |
| :---: | :---: | :---: |
| <img src="docs/images/handoff-confirm.png" width="205" alt="确认当前账号和下一棒后开始接力"> | <img src="docs/images/continue-history.png" width="205" alt="任务接续时间、结果和重试入口"> | <img src="docs/images/quota-overview.png" width="205" alt="所有账号的额度与重置时间"> |

| 查看用量趋势 | 管理密码与 2FA | 检查版本更新 |
| :---: | :---: | :---: |
| <img src="docs/images/personal-usage.png" width="205" alt="用量的时间范围、统计和趋势"> | <img src="docs/images/account-security.png" width="205" alt="账号详情内的密码、验证器和动态码"> | <img src="docs/images/version-update.png" width="205" alt="当前版本、检查更新按钮和检查结果"> |

- **任务接力**支持手动、自动和额度恢复后接力。可按需为备用账号开启预热。
- **用量和账号管理**支持额度总览、分账号 Token 统计、昵称、会员期限和归档。
- **密码与 2FA**支持在详情里更新密码、绑定或更换验证器，并导入 Google Authenticator 二维码。
- **外观和操作**可切换浅色、深色、磨砂玻璃或纯色，并设置托盘通知与快捷键。

## 数据与源码

账号快照和登录资料使用 Windows 当前用户加密。换电脑时，通过「设置 → 账号与数据 → 导入与导出」生成带密码的备份。反馈故障时可在设置里预览并复制脱敏诊断摘要。

从 [发布页](https://github.com/LUMIAO9527/ChatGPTnx/releases/latest) 下载源码包。运行 `setup.cmd` 准备依赖，再运行 `build.cmd` 构建。操作细节见 [使用说明](USAGE.md)，变更见 [更新记录](CHANGELOG.md)。

源码可查看，使用与分发条款见 [LICENSE](LICENSE)。ChatGPTnx 是独立工具，与 OpenAI 无隶属关系。
