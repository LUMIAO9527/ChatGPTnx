"""Package the maintained source, build assets and tests."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
TOP = ('README.md', 'README.en.md', 'USAGE.md', 'LICENSE', '.gitignore', 'accounts.sample.txt',
       'build.cmd', 'setup.cmd', 'start.cmd', 'preview.cmd', 'requirements.txt',
       'requirements-dev.txt', 'requirements-browser.txt')
EXTENSIONS = {'.py', '.js', '.cjs', '.css', '.ps1', '.ico', '.svg', '.html'}

def package(output: Path) -> int:
    files = [ROOT/name for name in TOP]
    for folder in ('src','tests','tools'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in EXTENSIONS)
    files = sorted(set(files),key=lambda p:p.relative_to(ROOT).as_posix())
    if any(not p.is_file() for p in files):
        raise RuntimeError('Required source archive inputs are missing')
    output.parent.mkdir(parents=True,exist_ok=True)
    hashes=[]
    with ZipFile(output,'w',ZIP_DEFLATED) as archive:
        for path in files:
            name=path.relative_to(ROOT).as_posix();data=path.read_bytes()
            archive.writestr(name,data)
            hashes.append(hashlib.sha256(data).hexdigest()+'  '+name)
        archive.writestr('MANIFEST.sha256','\n'.join(hashes)+'\n')
    with ZipFile(output) as archive:
        if archive.testzip() is not None or len(archive.namelist())!=len(files)+1:
            raise RuntimeError('Source archive CRC/count verification failed')
        for name in archive.namelist():
            if name.startswith(('_data/','snapshots/','_wip/','.git/','.venv/','reference/')) or name in {'accounts.txt','auth.json','ChatGPTnx.exe'}:
                raise RuntimeError('Private/runtime/reference data entered source archive')
        for row in hashes:
            digest,name=row.split('  ',1)
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:
                raise RuntimeError('Source manifest verification failed')
    return len(files)+1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();print(f'Packaged {package(args.output.resolve())} files, including manifest')
