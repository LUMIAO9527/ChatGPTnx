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
2. 点击「添加账号」，在 ChatGPT 完成登录。
3. 点击首页的「下一棒」切换账号。自动接力和任务接续可在设置中开启。
4. 从「设置 → 关于 → 版本更新」安装新版。

## 界面速览

| 确认账号接力 | 查阅接续记录 | 比较账号额度 |
| :---: | :---: | :---: |
| <img src="docs/images/handoff-confirm.png" width="205" alt="确认当前账号和下一棒后开始接力"> | <img src="docs/images/continue-history.png" width="205" alt="任务接续时间、结果和重试入口"> | <img src="docs/images/quota-overview.png" width="205" alt="所有账号的额度与重置时间"> |

| 查看用量趋势 | 管理密码与 2FA | 检查版本更新 |
| :---: | :---: | :---: |
| <img src="docs/images/personal-usage.png" width="205" alt="用量的时间范围、统计和趋势"> | <img src="docs/images/account-security.png" width="205" alt="账号详情内的密码、验证器和动态码"> | <img src="docs/images/version-update.png" width="205" alt="当前版本、检查更新按钮和检查结果"> |

## 数据与源码

「设置 → 账号与数据 → 导入与导出」可生成带密码的备份，供迁移到另一台电脑。

下载源码包后，运行 `setup.cmd` 安装依赖，再运行 `build.cmd` 构建。 [发布页](https://github.com/LUMIAO9527/ChatGPTnx/releases/latest) · [更新记录](CHANGELOG.md) · [许可](LICENSE)
