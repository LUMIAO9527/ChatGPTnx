"""Compile the small WinRT visual host using the installed Windows SDK."""
from pathlib import Path
import os
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def build_backdrop(output):
    if os.name != 'nt':
        return None
    framework=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Microsoft.NET'/'Framework64'/'v4.0.30319'
    kits=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits'/'10'/'References'
    def latest(paths):
        return max(paths,key=lambda path:tuple(int(n) for n in path.parent.name.split('.')))
    universal=list(kits.glob('*/Windows.Foundation.UniversalApiContract/*/*.winmd'))
    foundation=list(kits.glob('*/Windows.Foundation.FoundationContract/*/*.winmd'))
    if not universal or not foundation:
        raise RuntimeError('Install the Windows 10/11 SDK to build the clipped glass material')
    refs=[framework/name for name in ('System.Runtime.dll','System.Runtime.WindowsRuntime.dll',
                                       'System.Numerics.dll','System.Numerics.Vectors.dll')]
    refs += [latest(universal),latest(foundation)]
    output=Path(output).resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    command=[str(framework/'csc.exe'),'/nologo','/target:library','/optimize+',
             '/out:'+str(output),*('/r:'+str(p) for p in refs),str(ROOT/'src/window_backdrop.cs')]
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
    if result.returncode:
        raise RuntimeError('Backdrop compilation failed:\n'+result.stdout[-4000:])
    return output


if __name__=='__main__':
    print('Built clipped glass host:',build_backdrop(ROOT/'_wip/build/resources/ChatGPTnx.Backdrop.dll'))
