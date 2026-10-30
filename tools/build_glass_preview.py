"""Build a self-contained material comparison from the real offline UI."""
from pathlib import Path
import json
from build import ROOT, panel


def build_preview(output):
    demo = json.dumps(panel(demo=True), ensure_ascii=False).replace('<', '\\u003c')
    template = (ROOT / 'tools/templates/glass-preview.html').read_text(encoding='utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.replace('__DEMO__', demo), encoding='utf-8')
    print('Built glass preview:', output)


def build_native(output_directory):
    import os
    import subprocess
    import sys
    work=ROOT/'_wip'/'glass-native-build'
    from build_backdrop import build_backdrop
    backdrop=build_backdrop(ROOT/'_wip/build/resources/ChatGPTnx.Backdrop.dll')
    (work/'temp').mkdir(parents=True,exist_ok=True)
    (work/'demo.html').write_text(panel(demo=True),encoding='utf-8')
    env={**os.environ,'TEMP':str(work/'temp'),'TMP':str(work/'temp'),
         'PYINSTALLER_CONFIG_DIR':str(work/'cache'),'PYTHONDONTWRITEBYTECODE':'1'}
    subprocess.run([sys.executable,'-B','-m','PyInstaller','--noconfirm','--clean',
        '--onefile','--noconsole','--name','ChatGPTnx-GlassPreview',
        '--icon',str(ROOT/'src/assets/nx.ico'),'--paths',str(ROOT/'src'),
        '--add-data',str(work/'demo.html')+';.',
        '--add-data',str(ROOT/'tests/glass_render_checks.js')+';.',
        '--add-data',str(backdrop)+';.',
        '--distpath',str(output_directory),'--workpath',str(work/'work'),
        '--specpath',str(work/'spec'),str(ROOT/'tools/preview_glass.py')],
        cwd=ROOT,env=env,check=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / '_wip' / 'glass-preview' / 'ChatGPTnx-glass-preview.html')
    parser.add_argument('--native',action='store_true')
    args=parser.parse_args()
    build_preview(args.output.resolve())
    if args.native: build_native(args.output.resolve().parent)
