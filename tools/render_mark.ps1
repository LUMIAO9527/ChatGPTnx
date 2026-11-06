[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Output,
    [ValidateRange(16, 2048)][int]$Size = 1024,
    [ValidateSet('dark', 'light')][string]$Theme = 'dark'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationCore, WindowsBase
[xml]$svg = [IO.File]::ReadAllText([IO.Path]::GetFullPath($Source))
if ($svg.DocumentElement.GetAttribute('viewBox') -ne '0 0 32 32' -or
    $svg.SelectNodes('//*[@transform or local-name()="text" or local-name()="image"]').Count) {
    throw 'Expected a self-contained 32-unit mark without transforms, fonts or images.'
}
$tile = $svg.SelectSingleNode('//*[local-name()="rect"]')
$letters = $svg.SelectSingleNode('//*[local-name()="g"]')
$brush = [Windows.Media.BrushConverter]::new()
$foreground = if ($Theme -eq 'light') { '#171717' } else { '#ffffff' }
$background = if ($Theme -eq 'light') { '#ffffff' } else { '#171717' }
$pen = [Windows.Media.Pen]::new($brush.ConvertFromString($foreground), [double]$letters.GetAttribute('stroke-width'))
$pen.StartLineCap = 'Round'
$pen.EndLineCap = 'Round'
$pen.LineJoin = 'Round'
$visual = [Windows.Media.DrawingVisual]::new()
$drawing = $visual.RenderOpen()
$drawing.PushTransform([Windows.Media.ScaleTransform]::new($Size / 32.0, $Size / 32.0))
$edge = if ($Theme -eq 'light') { [Windows.Media.Pen]::new($brush.ConvertFromString('#d9d9d9'), .7) } else { $null }
$drawing.DrawRoundedRectangle($brush.ConvertFromString($background), $edge,
    [Windows.Rect]::new(0, 0, 32, 32), [double]$tile.GetAttribute('rx'), [double]$tile.GetAttribute('rx'))
foreach ($path in $letters.SelectNodes('*[local-name()="path"]')) {
    $drawing.DrawGeometry($null, $pen, [Windows.Media.Geometry]::Parse($path.GetAttribute('d')))
}
$drawing.Close()
$bitmap = [Windows.Media.Imaging.RenderTargetBitmap]::new($Size, $Size, 96, 96, 'Pbgra32')
$bitmap.Render($visual)
$encoder = [Windows.Media.Imaging.PngBitmapEncoder]::new()
$encoder.Frames.Add([Windows.Media.Imaging.BitmapFrame]::Create($bitmap))
$destination = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination)) | Out-Null
$stream = [IO.File]::Create($destination)
try { $encoder.Save($stream) } finally { $stream.Dispose() }
