"""Verify the delivered offline screenshot index, not a separate test mock."""
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from browser_session import browser_session
from screen_catalog import CASES


def main(browser: Path, output: Path, gallery: Path | None = None) -> int:
    results = []
    with browser_session(browser) as engine:
        page = engine.new_page(viewport={'width': 1440, 'height': 1000})
        errors, requests = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: requests.append(r.url))
        page.set_content((gallery or ROOT / 'docs/ui-gallery.html').read_text(encoding='utf-8'))
        def check(name, passed):
            results.append({'name': name, 'passed': bool(passed), 'errors': list(errors)})
        page.locator('article').first.wait_for()
        check('gallery/every-catalog-entry-present', page.locator('article').count() == len(CASES))
        check('gallery/all-images-decode', page.evaluate('''async () => {
          const sources=items.flatMap(c=>['light','dark'].flatMap(t=>[
            {data:c[t].image,width:c[t].width,height:c[t].height},
            ...(c[t].fullImage?[{data:c[t].fullImage,width:c[t].width,height:c[t].fullHeight}]:[])
          ]));
          // Verify every image without asking Chromium to retain hundreds of
          // decoded bitmaps at once. The gallery itself loads cards lazily.
          let decoded=0;
          for (const source of sources) {
            const img=new Image(); img.src=source.data;
            try {
              await img.decode();
              if (img.naturalWidth!==source.width||img.naturalHeight!==source.height) return false;
              decoded++;
            } catch (_) { return false; }
            finally { img.src=''; }
          }
          return decoded===sources.length&&decoded>=items.length*2;
        }'''))
        page.locator('#search').fill('Credits')
        check('gallery/text-search', page.locator('article').count() == 5)
        page.locator('article [data-mode="pair"]').first.click()
        check('gallery/original-size-comparison', page.locator('#viewer').is_visible() and page.locator('#images img').count() == 2)
        page.locator('#close').click()
        page.locator('#search').fill('')
        page.locator('#group').select_option(label='06 · 设置与参与账号')
        check('gallery/group-filter', page.locator('article').count() == sum(c['group']=='06 · 设置与参与账号' for c in CASES))
        page.locator('#group').select_option('')
        page.locator('#scrollOnly').check()
        count = page.locator('article').count()
        check('gallery/scroll-only-filter', count>0 and count<len(CASES) and page.locator('article [data-mode="full"]').count()==count)
        page.locator('article [data-mode="full"]').first.click()
        check('gallery/scroll-image-labelled', '不表示原生窗口会变高' in page.locator('#viewerNote').inner_text())
        check('gallery/no-external-network', not requests)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Gallery: {sum(r['passed'] for r in results)}/{len(results)}")
    for result in results:
        if not result['passed']: print(result)
    return int(any(not r['passed'] for r in results))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser',required=True,type=Path)
    parser.add_argument('--output',default=ROOT/'docs/validation/gallery-tests.json',type=Path)
    parser.add_argument('--gallery',type=Path)
    args=parser.parse_args()
    raise SystemExit(main(args.browser,args.output,args.gallery))
