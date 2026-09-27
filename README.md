<div align="center">
<img src="docs/images/nx-mark.png" width="88" alt="ChatGPTnx">
<h1>ChatGPTnx</h1>
<p><b>自动接力 · 任务接续 · 按用量配置 n×</b></p>
<p>用 5 个 Plus 账号，接力推进一个长任务。自动切号，继续原任务。</p>

<img src="docs/images/badges/platform.svg" alt="Windows 10 | 11" height="20">
<img src="docs/images/badges/version.svg" alt="v1.0.0" height="20">
<img src="docs/images/badges/license.svg" alt="源码可查看 · 保留权利" height="20">
</div>

ChatGPTnx 是一款轻量的 Windows 桌面工具，通过多账号自动接力与任务接续，减少长任务因额度耗尽而中断后的等待和手动操作。

## 功能

- **自动接力**：额度耗尽时切换到有可用额度的参与账号，支持手动接力和自定义参与账号。
- **任务接续**：切换账号后接续原桌面任务，支持自定义接续消息和查看接续记录。
- **额度与用量**：集中查看各账号的剩余额度、重置时间和 Token 用量，为接力安排和账号数量配置提供参考。
- **轻量化**：常驻 Windows 托盘，面板用完即收起，支持通知、快捷键和深浅外观。

### 持续任务能力

ChatGPTnx 的核心，是让多个 Plus 账号接力推进同一个长任务。当前账号额度耗尽时，**自动接力**切换到下一个可用账号，**任务接续**随后继续原桌面任务，减少手动切号和重新接续的操作。

**n× 代表可以按实际用量自由配置的账号数量。** 你可以从少量账号开始，根据任务强度和使用频率增加账号，或调整参与接力的账号。例如，配置 5 个 Plus 账号，就可以让它们轮流参与接力，让长任务更少因单个账号的额度限制而停下来等待。

自动接力和任务接续共同提供持续任务能力；额度总览、用量统计与轻量桌面操作为它们提供配套支持，让你看清可用额度、判断实际用量，并更方便地安排下一棒。

## 界面

### 账号接力与任务接续

| 首页 · 当前账号与下一棒 | 账号接力 · 确认下一棒 | 任务接续 · 查看记录 |
| --- | --- | --- |
| <img src="docs/images/home-live.png" width="260" alt="首页：当前账号、剩余额度与下一棒"> | <img src="docs/images/relay-confirm-live.png" width="260" alt="账号接力：确认下一棒并开始接力"> | <img src="docs/images/resume-live.png" width="260" alt="任务接续记录"> |

### 额度与用量

| 额度总览 | 个人用量 | 账号详情 |
| --- | --- | --- |
| <img src="docs/images/quota-live.png" width="260" alt="各账号额度总览"> | <img src="docs/images/usage-live.png" width="260" alt="个人 Token 用量与趋势"> | <img src="docs/images/detail-live.png" width="260" alt="账号详情"> |

### 设置与外观

| 设置 | 深色外观 | 添加账号 |
| --- | --- | --- |
| <img src="docs/images/settings-live.png" width="260" alt="设置：接力与任务接续"> | <img src="docs/images/home-dark-current.png" width="260" alt="首页深色外观"> | <img src="docs/images/add-account-live.png" width="260" alt="添加账号：打开桌面登录窗口并确认保存"> |

## 下载与运行

从 [v1.0.0 Release](https://github.com/LUMIAO9527/ChatGPTnx/releases/tag/v1.0.0) 下载 `ChatGPTnx.exe`；源码可下载 `ChatGPTnx-v1.0.0-source.zip`。需要 Windows 10 / 11 64 位、已安装并登录的 ChatGPT 桌面应用，以及 Microsoft Edge WebView2 Runtime。

1. 将 EXE 放入独立、可写的目录后启动，从托盘打开面板。
2. 点击“添加账号”，按提示打开桌面登录窗口；登录新账号后，回到面板确认保存。
3. 先用“下一棒”完成一次手动接力，再在设置中开启自动接力并选择参与账号。
4. 开启“切号后自动接续任务”，根据需要配置接续消息；在任务接续记录中查看结果。

关闭面板只是收起界面，程序仍在托盘运行；需要完全退出时，使用托盘菜单。

## 数据与隐私

账号与运行数据保存在程序所在目录，请妥善保管，勿公开上传。反馈问题时请移除邮箱、令牌、任务信息和本机路径。

## 授权

源码可下载查看，使用与授权条款见 [LICENSE](LICENSE)。本项目与 OpenAI 没有隶属或认可关系。
