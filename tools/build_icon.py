"""Regenerate the committed Windows icon from the same SVG used in the UI.
Optional asset-authoring dependencies: Pillow and cairosvg; normal app builds
copy the committed nx.ico and do not require either dependency.
"""
from pathlib import Path
import io
import re
ROOT=Path(__file__).resolve().parents[1]

def build(output=None):
    import cairosvg
    from PIL import Image
    source=(ROOT/'src/assets/nx-mark.svg').read_text(encoding='utf-8')
    source=re.sub(r' aria-hidden="true"','',source)
    source=source.replace('stroke="currentColor"','stroke="#ffffff"')
    source=source.replace('<path ', '<rect x="0" y="0" width="32" height="32" rx="10" fill="#171717"/><path ',1)
    png=cairosvg.svg2png(bytestring=source.encode(),output_width=256,output_height=256)
    image=Image.open(io.BytesIO(png)).convert('RGBA')
    output=Path(output or ROOT/'src/assets/nx.ico')
    image.save(output,format='ICO',sizes=[(n,n) for n in (16,20,24,32,40,48,64,128,256)])
    return output

if __name__=='__main__': print(build())
