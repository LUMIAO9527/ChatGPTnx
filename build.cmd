@echo off
setlocal
cd /d "%~dp0"
if not exist tools\build.py (
  echo Run this script inside the ChatGPTnx project root.
  exit /b 1
)
if exist .venv\Scripts\python.exe (set "PYTHON=.venv\Scripts\python.exe") else (set "PYTHON=py")
set "BUILD_ROOT=%CD%\_wip\build"
set "PYINSTALLER_CONFIG_DIR=%BUILD_ROOT%\cache"

"%PYTHON%" tools\build.py
if errorlevel 1 exit /b 1
"%PYTHON%" -c "import PyInstaller" 1>%SystemRoot%\System32\NUL 2>&1
if errorlevel 1 (
  echo PyInstaller is missing. Install requirements-dev.txt first.
  exit /b 1
)
"%PYTHON%" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name ChatGPTnx --icon "%BUILD_ROOT%\resources\nx.ico" ^
  --paths "%CD%\src" ^
  --add-data "%BUILD_ROOT%\resources\panel.html;." ^
  --add-data "%BUILD_ROOT%\resources\nx.ico;." ^
  --add-data "%BUILD_ROOT%\resources\switch_account.ps1;." ^
  --add-data "%BUILD_ROOT%\resources\continue_in_desktop.ps1;." ^
  --distpath "%BUILD_ROOT%\dist" --workpath "%BUILD_ROOT%\work" ^
  --specpath "%BUILD_ROOT%\spec" src\chatgptnx.py
if errorlevel 1 exit /b 1
copy /Y "%BUILD_ROOT%\dist\ChatGPTnx.exe" "ChatGPTnx.exe" 1>%SystemRoot%\System32\NUL 2>&1
if errorlevel 1 (
  echo New EXE built at _wip\build\dist\ChatGPTnx.exe, but the running formal EXE is locked and was not replaced.
  echo After replacement, launch start.cmd or double-click ChatGPTnx.exe.
  exit /b 2
)
echo Built ChatGPTnx.exe. Temporary build files are under _wip\build.
