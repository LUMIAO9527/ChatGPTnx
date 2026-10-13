"""Corner coverage and native resource/lifecycle checks with synthetic handles."""
import ctypes
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from nx.window_corners import WindowCorners, coverage


class CornerCoverageTests(unittest.TestCase):
    def test_each_dpi_has_partial_pixels_monotone_arc_and_no_center_holes(self):
        for radius in (16,20,24,28,32,40):
            matrix = coverage(radius)
            self.assertEqual(matrix[0][0], 0)
            self.assertEqual(matrix[-1][-1], 255)
            self.assertTrue(any(0 < p < 255 for row in matrix for p in row))
            for y, row in enumerate(matrix):
                self.assertEqual(tuple(sorted(row)), row)
                for x, alpha in enumerate(row):
                    self.assertEqual(alpha, matrix[x][y])
                    if y:
                        self.assertGreaterEqual(alpha, matrix[y-1][x])


class NativeCornerTests(unittest.TestCase):
    def setUp(self):
        self.edges = WindowCorners.__new__(WindowCorners)
        self.visible = True
        self.rect = (100,120,672,922)
        self.user = SimpleNamespace(**{key: Mock(return_value=1) for key in
            ('DestroyWindow','IsWindow','ShowWindow','SetWindowPos','SetWindowRgn')})
        self.user.IsWindowVisible = Mock(side_effect=lambda _: self.visible)
        self.user.GetWindow = Mock(return_value=None)
        self.user.GetWindowLongPtrW = Mock(return_value=0)
        def rect(hwnd, out):
            out._obj.left,out._obj.top,out._obj.right,out._obj.bottom = self.rect
            return 1
        self.user.GetWindowRect = Mock(side_effect=rect)
        self.user.CreateWindowExW = Mock(side_effect=[201,202,203,204,301,302,303,304])
        self.gdi = SimpleNamespace(ExtCreateRegion=Mock(return_value=401),DeleteObject=Mock())
        self.edges.user,self.edges.gdi = self.user,self.gdi
        self.edges.kernel = SimpleNamespace(GetModuleHandleW=Mock(return_value=501))
        self.edges.owner,self.edges.key,self.edges.windows = None,None,[]
        self.edges._paint = Mock()

    def test_owned_edges_are_input_transparent_nonactivating_and_tool_only(self):
        self.edges.apply(101,28,(29,29,29))
        calls = self.user.CreateWindowExW.call_args_list
        self.assertEqual(len(calls),4)
        for call in calls:
            flags = call.args[0]
            self.assertEqual(flags & 0x080800A0, 0x080800A0)
            self.assertFalse(flags & 0x00040000)
            self.assertEqual(call.args[8],101)
        for call in self.user.SetWindowPos.call_args_list:
            self.assertTrue(call.args[-1] & 0x0010)
        self.assertTrue(all(call.args[1] == 4 for call in self.user.ShowWindow.call_args_list))

    def test_region_contains_full_pixels_only_and_is_symmetric(self):
        self.edges.apply(101,28,(29,29,29))
        data = self.gdi.ExtCreateRegion.call_args.args[2].raw
        size,kind,count,bytes_,left,top,right,bottom = struct.unpack_from('<8I',data)
        self.assertEqual((size,kind,bytes_,left,top,right,bottom),(32,1,count*16,0,0,572,802))
        rectangles = [struct.unpack_from('<4i',data,32+i*16) for i in range(count)]
        self.assertEqual(rectangles,sorted(rectangles,key=lambda r:(r[1],r[0])))
        for y in range(28):
            l,t,r,b = rectangles[y]
            self.assertEqual((t,b),(y,y+1))
            self.assertEqual(l,572-r)
            self.assertEqual(l,next((x for x,a in enumerate(coverage(28)[y]) if a==255),28))
            self.assertEqual(rectangles[-y-1],(l,801-y,r,802-y))
        self.gdi.DeleteObject.assert_not_called()

    def test_theme_changes_repaint_all_edges_without_allocating_more_windows(self):
        self.edges.apply(101,28,(255,255,255))
        self.edges.apply(101,28,(29,29,29))
        self.assertEqual(self.edges._paint.call_count,8)
        self.assertEqual(self.user.CreateWindowExW.call_count,4)
        self.assertTrue(all(c.args[2]==(29,29,29) for c in self.edges._paint.call_args_list[-4:]))

    def test_hiding_and_showing_owner_explicitly_updates_all_edges(self):
        self.edges.apply(101,28,(29,29,29))
        self.edges.move(visible=False)
        self.assertTrue(all(c.args[1]==0 for c in self.user.ShowWindow.call_args_list[-4:]))
        self.edges.move(visible=True)
        self.assertTrue(all(c.args[1]==4 for c in self.user.ShowWindow.call_args_list[-4:]))

    def test_recreated_owner_destroys_old_edges_before_replacing_them(self):
        self.edges.apply(101,28,(29,29,29))
        self.edges.apply(102,28,(29,29,29))
        self.assertEqual([c.args[0] for c in self.user.DestroyWindow.call_args_list],[201,202,203,204])
        self.assertEqual(self.edges.windows,[301,302,303,304])

    def test_region_is_released_if_assignment_fails(self):
        self.user.SetWindowRgn.return_value=0
        with self.assertRaises(OSError):
            self.edges.apply(101,28,(29,29,29))
        self.gdi.DeleteObject.assert_called_once_with(401)
        self.assertIsNone(self.edges.key)

    def test_repeat_shape_moves_without_repainting_or_gdi_allocations(self):
        self.edges.apply(101,28,(29,29,29))
        self.edges.apply(101,28,(29,29,29))
        self.assertEqual(self.edges._paint.call_count,4)
        self.gdi.ExtCreateRegion.assert_called_once()
        self.assertEqual(self.user.SetWindowPos.call_count,8)

    def test_edges_follow_owner_into_topmost_band_and_back(self):
        self.edges.apply(101,28,(29,29,29))
        self.user.SetWindowPos.reset_mock()
        self.user.GetWindowLongPtrW.side_effect=lambda hwnd,index: 8 if hwnd==101 else 0
        self.edges.move()
        promotions=[c for c in self.user.SetWindowPos.call_args_list if isinstance(c.args[1],ctypes.c_void_p)]
        self.assertEqual(len(promotions),4)
        self.assertTrue(all(c.args[1].value==ctypes.c_void_p(-1).value for c in promotions))
        self.user.SetWindowPos.reset_mock()
        self.user.GetWindowLongPtrW.side_effect=lambda hwnd,index: 0 if hwnd==101 else 8
        self.edges.move()
        demotions=[c for c in self.user.SetWindowPos.call_args_list if isinstance(c.args[1],ctypes.c_void_p)]
        self.assertEqual(len(demotions),4)
        self.assertTrue(all(c.args[1].value==ctypes.c_void_p(-2).value for c in demotions))

    def test_edges_stay_above_owner_and_below_another_ordinary_window(self):
        self.user.GetWindow.return_value=601
        self.edges.apply(101,28,(29,29,29))
        self.assertEqual([c.args[1] for c in self.user.SetWindowPos.call_args_list],[601,201,202,203])


if __name__ == '__main__':
    unittest.main()
