"""Brand assets and the shared surface composition remain available after packaging."""
from pathlib import Path
import struct
import sys
import unittest
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build import panel

class SurfaceBuildTests(unittest.TestCase):
    def test_brand_mark_uses_a_self_contained_vector(self):
        svg=ET.fromstring((ROOT/'src/assets/nx-mark.svg').read_bytes())
        self.assertEqual(svg.attrib['viewBox'],'0 0 32 32')
        self.assertGreater(len(list(svg)),0)
        text=(ROOT/'src/assets/nx-mark.svg').read_text(encoding='utf-8')
        self.assertNotIn('href=',text)
        self.assertNotIn('<text',text)
    def test_production_and_demo_embed_same_brand_once(self):
        for demo in (True,False):
            html=panel(demo=demo)
            self.assertEqual(html.count('window.NX_BRAND_MARK='),1)
            self.assertIn('M6.5 22V14.2',html)
            self.assertIn('n× · ChatGPTnx',html)
    def test_native_icon_has_small_and_high_dpi_frames(self):
        data=(ROOT/'src/assets/nx.ico').read_bytes()
        reserved,kind,count=struct.unpack('<HHH',data[:6])
        self.assertEqual((reserved,kind),(0,1))
        sizes=set()
        for i in range(count):
            w,h,_,_,planes,bits,length,offset=struct.unpack('<BBBBHHII',data[6+i*16:22+i*16])
            sizes.add(w or 256)
            self.assertEqual(w,h)
            self.assertLessEqual(offset+length,len(data))
            self.assertGreater(length,0)
        self.assertTrue({16,20,24,32,48,256}.issubset(sizes))
    def test_preview_simulation_is_not_in_production(self):
        live=panel();demo=panel(demo=True)
        self.assertNotIn('async function applyStep',live)
        self.assertIn('if(step.simulate)',demo)
    def test_usage_head_inherits_shared_identity_and_periods(self):
        src=(ROOT/'src/ui/views/usage.js').read_text(encoding='utf-8')
        self.assertIn('usage-context',src)
        self.assertIn('usage-summary',src)
        self.assertIn('accountIdentity(',src)
        self.assertIn('usage-accounts',src)

if __name__=='__main__':unittest.main()
