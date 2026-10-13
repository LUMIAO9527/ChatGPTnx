# Windows 面板圆角评审

## 2026-10-13：16px 统一圆角

1.0.3 候选版把外框与主要卡片统一为 16px。Windows 11 的系统圆角不能指定该半径，因此改为：不透明 WebView2 保留主题底色，窗口区域只包含完全覆盖的像素，四个很小的附属透明窗口补充弧边的半透明像素。附属窗口不激活、不接收点击、不进入任务栏，随主面板移动、隐藏和销毁。失败时保持面板隐藏，不展示缺失边缘的裁切。Windows 10 仍保留传统区域回退。

原来的白角防护继续保留：不透明 WebView2、整面主题底色、`SYSTEMBACKDROP_TYPE=NONE`。浅深外观变化同步弧边颜色，深色启动底色统一为 `#1d1d1d`。

隔离验收使用实际 WebView2 与产品 `Desktop._apply_native_shape()` 及其原生事件：Windows 11 build 26200、168 DPI，16px 对应 28 个物理像素。浅色启动、深色启动及外观切换，分别在蓝色 `#305bce`、浅灰 `#e7ebef` 后景下检查四角；最外侧像素全部与后景相同，每个弧边有 19–24 种混合色，深色角部未发现中性白色残留。隐藏、再显示、移动、销毁检查通过。测试代码与截图位于 `_wip/login-update-20261013/corner-trial-*`；未使用真实账号数据。实际正式 EXE 的验收单独记录，不将浏览器预览当成原生验收。

以下为 1.0.0 时的调查记录；其中 DWM 系统圆角是当时的实现。

基线为 `main@734513f0f030cb27585298638e77d42a882e0932`；产品版本保持 `1.0.0`。

## 原因与处理

面板由 Win32 窗口、DWM 和 WebView2 共同绘制。CSS 圆角只裁剪网页内容，不能保证窗口外侧露出真实后景。WebView2 表面使用不透明的主题底色，避免网页透明像素露出固定的宿主底色。

原代码将 DWM 属性 38 误标为 `REDIRECTIONBITMAP_ALPHA`。微软文档规定 38 实际是 `SYSTEMBACKDROP_TYPE`，值 1 是 `DWMSBT_NONE`，即不绘制系统背景；`REDIRECTIONBITMAP_ALPHA` 是属性 39。在本机，删除属性 38 后，即使窗口区域设置成功，圆角外仍出现固定深灰色。

初版修复保留了 38=1，并用 `SetWindowRgn` 硬裁剪。真实 NX 窗口验收时用户指出弧边有严重锯齿；像素检查也确认硬裁剪没有混合色。Windows 11 修订版因此不设置窗口区域，而是由 DWM 属性 33=ROUND、34=COLOR_NONE、38=NONE 绘制外轮廓。真实 WebView2 隔离窗口上，四角外侧跟随后景变化，弧边有抗锯齿混合色。Windows 10 保留窗口区域作为兼容回退，仍可能存在硬裁剪锯齿。

补丁还补全了本次涉及的 Win32 函数签名、旧系统区域失败时的资源释放和隐藏保护、窗口句柄重建后的重新设置。切号接续时如圆角设置失败，面板保持隐藏并继续原有的限时展示重试；接续工作流本身不因此清除。

## 本机验证

- Windows 11 build 26200、真实 WebView2：使用与产品相同的 CSS 和 `Desktop._apply_native_shape()`，在面板显示前设置 DWM 圆角。浅色和暗色面板分别置于蓝色 `#305bce`、浅灰色 `#e7ebef` 窗口前；四角最外侧采样像素均与后景一致，弧边有 8–10 种混合颜色。截图与测试代码位于本次隔离工作区 `_wip/AUTO_20260928native-review/`。
- `tools/verify_windows.ps1`：PowerShell 解析、合成接续检查、资源构建和 443 项 Python 测试通过。原生面板单组 34 项通过。
- Edge 浏览器界面检查 130 项通过；它不代表原生窗口视觉验收。
- 实际 NX EXE：在 Windows 11 build 26200、168 DPI 的窗口上读取到 DWM 圆角属性 33=2、系统背景属性 38=1，且没有窗口区域。面板前方保持可见时，在深灰色无焦点背景窗上四角最外侧像素与背景一致，弧边有 10 种混合颜色；四条直边外侧采样未见额外阴影。首轮硬裁剪版本被用户指出锯齿后停止发布，随后换成了这版 DWM 圆角。

## 尚未验证

Windows 10、其他 Windows 11 构建、其他 DPI/显示器组合，以及真实账号切换和任务接续尚未做端到端验收。圆角视觉测试使用真实 NX 窗口和不含账号内容的角部截图，没有发起切号。

参考：[微软 DWM 圆角说明](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-rounded-corners)、[DWM 属性](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)、[DWM 系统背景类型](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type)、[SetWindowRgn](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowrgn)。
