"""Generate an entirely offline, standalone explorer from production UI components."""
from pathlib import Path
import argparse
import json
from build import ROOT, panel, APP_VERSION, CONFIG, ui_source_digest
from screen_catalog import CASES, NATIVE_SURFACES

def js(value):
    return json.dumps(value,ensure_ascii=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')

def build_explorer(output: Path):
    template=(ROOT/'tools/templates/explorer.html').read_text(encoding='utf-8')
    width,height=CONFIG['sizes']['home']
    html=template.replace('__VERSION__',APP_VERSION).replace('__GEOMETRY__',f'{width} × {height}').replace('__SOURCE_DIGEST__',ui_source_digest()).replace('__CATALOG__',js(CASES)).replace('__NATIVE__',js(NATIVE_SURFACES)).replace('__DEMO__',js(panel(demo=True)))
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(html,encoding='utf-8')
    print('Built offline UI explorer:',output)
    return html

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/f'ChatGPTnx-v{APP_VERSION}.html')
    build_explorer(parser.parse_args().output.resolve())
