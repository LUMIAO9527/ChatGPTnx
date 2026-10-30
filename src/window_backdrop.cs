// Clip the sampled desktop material itself, before it is composited with WebView2.
using System;
using System.Numerics;
using System.Runtime.InteropServices;
using Windows.UI.Composition;
using Windows.UI.Composition.Desktop;

namespace ChatGPTnx.Native
{
    public sealed class ClippedBackdrop : IDisposable
    {
        [StructLayout(LayoutKind.Sequential)]
        struct QueueOptions { public int size, thread, apartment; }
        [DllImport("CoreMessaging.dll")]
        static extern int CreateDispatcherQueueController(QueueOptions options, out IntPtr controller);
        [ThreadStatic] static IntPtr queue;
        [ThreadStatic] static Compositor compositor;

        [ComImport, Guid("29E691FA-4567-4DCA-B319-D0F207EB6807"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IDesktopInterop
        {
            void CreateDesktopWindowTarget(IntPtr hwnd, bool topmost, out IntPtr target);
        }

        DesktopWindowTarget target;
        SpriteVisual visual;
        CompositionRoundedRectangleGeometry geometry;
        CompositionGeometricClip clip;
        CompositionBackdropBrush brush;
        public int Width { get; private set; }
        public int Height { get; private set; }
        public int Radius { get; private set; }

        public ClippedBackdrop(IntPtr hwnd)
        {
            if (compositor == null)
            {
                int hr = CreateDispatcherQueueController(new QueueOptions {
                    size=Marshal.SizeOf(typeof(QueueOptions)), thread=2, apartment=2
                }, out queue);
                Marshal.ThrowExceptionForHR(hr);
                compositor = new Compositor();
            }
            try
            {
                IntPtr raw;
                ((IDesktopInterop)(object)compositor).CreateDesktopWindowTarget(hwnd, false, out raw);
                try { target=(DesktopWindowTarget)Marshal.GetObjectForIUnknown(raw); }
                finally { Marshal.Release(raw); }
                brush=compositor.CreateHostBackdropBrush();
                geometry=compositor.CreateRoundedRectangleGeometry();
                clip=compositor.CreateGeometricClip(geometry);
                visual=compositor.CreateSpriteVisual();
                visual.Brush=brush;
                visual.Clip=clip;
            }
            catch { Dispose(); throw; }
        }

        public void Resize(int width, int height, int radius)
        {
            if (width < 1 || height < 1 || radius < 1) throw new ArgumentOutOfRangeException();
            radius=Math.Min(radius, Math.Min(width, height)/2);
            if (Width == width && Height == height && Radius == radius) return;
            var size=new Vector2(width,height);
            visual.Size=size;
            geometry.Size=size;
            geometry.CornerRadius=new Vector2(radius,radius);
            Width=width; Height=height; Radius=radius;
        }

        public void SetVisible(bool visible) { target.Root=visible ? visual : null; }

        public void Dispose()
        {
            if (target!=null) { target.Root=null; target.Dispose(); target=null; }
            if (visual!=null) { visual.Dispose(); visual=null; }
            if (clip!=null) { clip.Dispose(); clip=null; }
            if (geometry!=null) { geometry.Dispose(); geometry=null; }
            if (brush!=null) { brush.Dispose(); brush=null; }
        }
    }
}
