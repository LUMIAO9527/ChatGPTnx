"""Clipped material selection, resize, policy and opaque failure recovery."""
from pathlib import Path
import ctypes
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch, call
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from nx import window_material as wm

class Function:
    def __init__(self,result=0,effect=None):
        self.result,self.effect,self.calls=result,effect,[]
    def __call__(self,*args):
        self.calls.append(args)
        return self.effect(*args) if self.effect else self.result

class MaterialTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(patch.stopall)
        self.version=patch.object(wm.sys,'getwindowsversion',return_value=SimpleNamespace(build=19045),create=True).start()
        self.policy=patch.object(wm,'transparency_allowed',return_value=True).start()
        self.user=SimpleNamespace(SetWindowCompositionAttribute=Function(1))
        self.dwm=SimpleNamespace(DwmSetWindowAttribute=Function(),DwmExtendFrameIntoClientArea=Function())
        patch.object(wm.ctypes,'windll',SimpleNamespace(user32=self.user,dwmapi=self.dwm),create=True).start()
        self.host=wm.WindowMaterial(Mock())
        self.host._surface=Mock()
        self.host._geometry=Mock(return_value=(312,458,16))
        self.clip=Mock()
        self.host._create_clip=Mock(return_value=self.clip)
        self.form,self.hwnd=object(),0x123456789
    def apply(self,**kwargs):
        return self.host.apply(self.form,self.hwnd,**kwargs)
    def accent_states(self):
        states=[]
        self.user.SetWindowCompositionAttribute.effect=lambda hwnd,p: states.append(ctypes.cast(p._obj.data,ctypes.POINTER(wm.AccentPolicy)).contents.state) or 1
        return states
    def test_win10_registers_sampling_without_whole_window_blur(self):
        states=self.accent_states()
        self.assertEqual(self.apply(),'blur')
        self.assertEqual(states,[0,5])
        self.assertEqual(self.dwm.DwmSetWindowAttribute.calls,[])
        self.clip.Resize.assert_called_once_with(312,458,16)
        self.clip.SetVisible.assert_called_once_with(True)
    def test_win11_clips_brush_instead_of_rectangular_acrylic(self):
        self.version.return_value.build=22621
        self.assertEqual(self.apply(dark=True),'blur')
        attrs=[(c[1],c[2]._obj.value) for c in self.dwm.DwmSetWindowAttribute.calls]
        self.assertIn((17,1),attrs)
        self.assertIn((38,1),attrs)
        self.assertNotIn((38,3),attrs)
        self.assertEqual(self.host.outline,{'width':312,'height':458,'radius':16})
    def test_resize_retargets_clip_without_recreating_visual(self):
        self.apply();self.host._geometry.return_value=(468,687,24)
        self.assertEqual(self.apply(),'blur')
        self.host._create_clip.assert_called_once()
        self.clip.Resize.assert_called_with(468,687,24)
    def test_solid_covers_surface_before_hiding_backdrop(self):
        self.apply();calls=Mock()
        calls.attach_mock(self.host._surface,'surface');calls.attach_mock(self.clip.SetVisible,'visible')
        self.assertEqual(self.apply(backend='solid'),'solid')
        self.assertEqual(calls.mock_calls[:2],[call.surface(self.form,False,False),call.visible(False)])
        self.assertIsNone(self.host.outline)
    def test_missing_legacy_export_restores_surface(self):
        del self.user.SetWindowCompositionAttribute
        self.assertEqual(self.apply(dark=True),'solid')
        self.host._surface.assert_any_call(self.form,False,True)
        self.host._create_clip.assert_not_called()
    def test_missing_visual_host_never_leaves_rectangular_blur(self):
        states=self.accent_states();self.host._create_clip.side_effect=RuntimeError('synthetic')
        self.assertEqual(self.apply(),'solid')
        self.assertNotIn(3,states);self.assertEqual(states[-1],0)
        self.host._surface.assert_any_call(self.form,False,False)
    def test_extension_failure_never_creates_visual(self):
        self.dwm.DwmExtendFrameIntoClientArea.result=-1
        self.assertEqual(self.apply(),'solid');self.host._create_clip.assert_not_called()
    def test_system_policy_overrides_preference(self):
        self.policy.return_value=False
        self.assertEqual(self.apply(),'solid');self.host._surface.assert_called_once_with(self.form,False,False)
    def test_solid_preference_never_makes_surface_transparent(self):
        self.assertEqual(self.apply(requested=False),'solid')
        self.host._surface.assert_called_once_with(self.form,False,False);self.policy.assert_not_called()
    def test_policy_change_reuses_hidden_visual(self):
        self.assertEqual(self.apply(),'blur');self.policy.return_value=False
        self.assertEqual(self.apply(),'solid');self.policy.return_value=True
        self.assertEqual(self.apply(),'blur');self.host._create_clip.assert_called_once()
    def test_same_material_leaves_compositor_and_webview_unchanged(self):
        self.apply();self.apply();self.host._surface.assert_called_once();self.clip.Resize.assert_called_once()
    def test_failure_is_retryable(self):
        self.host._create_clip.side_effect=[RuntimeError('synthetic'),self.clip]
        self.assertEqual(self.apply(),'solid');self.assertEqual(self.apply(),'blur')
    def test_close_releases_material(self):
        self.apply();self.host.close();self.clip.Dispose.assert_called_once();self.assertIsNone(self.host._backdrop)
    def test_unavailable_or_old_windows_uses_solid(self):
        for version in (None,SimpleNamespace(build=15063)):
            self.version.return_value=version;self.assertEqual(self.apply(),'solid')
    def test_geometry_failure_restores_solid(self):
        self.host._geometry.side_effect=OSError('synthetic');self.assertEqual(self.apply(),'solid')
    def test_legacy_payload_preserves_pointer_width(self):
        pointer=ctypes.sizeof(ctypes.c_void_p)
        self.assertEqual(wm.CompositionAttribute.data.offset,pointer)
        self.assertEqual(wm.CompositionAttribute.size.offset,pointer*2)
        self.assertEqual(ctypes.sizeof(wm.CompositionAttribute),pointer*3)

if __name__=='__main__':unittest.main()
