"""Render the canonical n× geometry in both platform icon palettes."""
from pathlib import Path
import shutil
import subprocess
ROOT = Path(__file__).resolve().parents[1]

def build(output=None):
    from PIL import Image
    folder = ROOT / '_wip/icon-render'
    folder.mkdir(parents=True, exist_ok=True)
    for theme in ('dark', 'light'):
        raster = folder / f'nx-{theme}.png'
        subprocess.run(['powershell.exe', '-NoProfile', '-Sta', '-ExecutionPolicy', 'Bypass',
            '-File', str(ROOT/'tools/render_mark.ps1'), '-Source', str(ROOT/'src/assets/nx-mark.svg'),
            '-Output', str(raster), '-Theme', theme], check=True)
        with Image.open(raster) as rendered:
            image = rendered.convert('RGBA')
        image.save(ROOT/f'src/assets/nx-{theme}.ico', format='ICO',
                   sizes=[(n,n) for n in (16,20,24,32,40,48,64,128,256)])
        image.resize((256,256), Image.Resampling.LANCZOS).save(ROOT/f'docs/images/nx-mark-{theme}.png')
    result = Path(output or ROOT/'src/assets/nx.ico')
    shutil.copy2(ROOT/'src/assets/nx-dark.ico', result)
    shutil.copy2(ROOT/'docs/images/nx-mark-dark.png', ROOT/'docs/images/nx-mark.png')
    return result

if __name__ == '__main__':
    print(build())
