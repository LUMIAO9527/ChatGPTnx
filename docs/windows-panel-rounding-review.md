# Windows 面板圆角评审

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
- 隔离副本能够打包为 `ChatGPTnx.exe`。最终实际 NX 窗口和 GitHub 发布验收结果应在部署后另行核对。

## 尚未验证

Windows 10、其他 Windows 11 构建、其他 DPI/显示器组合，以及真实账号切换和任务接续尚未做端到端验收。本机视觉测试只使用合成内容，没有触碰账号或运行数据。

参考：[微软 DWM 圆角说明](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-rounded-corners)、[DWM 属性](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)、[DWM 系统背景类型](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type)、[SetWindowRgn](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowrgn)。
