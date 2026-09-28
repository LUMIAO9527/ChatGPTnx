# Windows 面板圆角评审

基线为 `main@734513f0f030cb27585298638e77d42a882e0932`；产品版本保持 `1.0.0`。

## 原因与处理

面板由 Win32 窗口、DWM 和 WebView2 共同绘制。CSS 圆角只裁剪网页内容，不能保证窗口外侧露出真实后景。窗口区域 `SetWindowRgn` 提供 16 DIP 的原生圆角裁剪；WebView2 表面则使用不透明的主题底色，避免网页透明像素露出固定的宿主底色。

原代码将 DWM 属性 38 误标为 `REDIRECTIONBITMAP_ALPHA`。微软文档规定 38 实际是 `SYSTEMBACKDROP_TYPE`，值 1 是 `DWMSBT_NONE`，即不绘制系统背景；`REDIRECTIONBITMAP_ALPHA` 是属性 39。在本机，删除属性 38 后，即使窗口区域设置成功，圆角外仍出现固定深灰色。将 38=1 保留并按真实含义命名后，深灰色消失。因此本修复只保留这一个 DWM 属性，不再请求 DWM 二次圆角或修改边框颜色。

补丁还补全了本次涉及的 Win32 函数签名、区域失败时的资源释放和隐藏保护、窗口句柄重建后的重新裁剪。切号接续时如裁剪失败，面板保持隐藏并继续原有的限时展示重试；接续工作流本身不因此清除。

## 本机验证

- Windows 11 build 26200、真实 WebView2：使用与产品相同的 CSS 和 `Desktop._apply_native_shape()`，在面板显示前设置窗口区域。浅色和暗色面板分别置于蓝色 `#305bce`、浅灰色 `#e7ebef` 窗口前；四角外侧的采样像素均与后景完全一致，四角内侧显示面板主题底色。截图与测试代码位于本次隔离工作区 `_wip/AUTO_20260928native-review/`。
- `tools/verify_windows.ps1`：PowerShell 解析、合成接续检查、资源构建和 441 项 Python 测试通过。随后增加一项裁剪失败时接续仍可重试的测试，原生面板单组现为 33 项通过。
- Edge 浏览器界面检查 130 项通过；它不代表原生窗口视觉验收。
- 隔离副本能够打包为 `ChatGPTnx.exe`；没有替换现用程序或更改远端发布文件。

## 尚未验证

Windows 10、其他 Windows 11 构建、其他 DPI/显示器组合，以及真实账号切换和任务接续尚未做端到端验收。本机视觉测试只使用合成内容，没有触碰账号或运行数据。

参考：[微软 DWM 属性](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)、[DWM 系统背景类型](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwm_systembackdrop_type)、[SetWindowRgn](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowrgn)。
