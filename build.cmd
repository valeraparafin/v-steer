@echo off
rem Build dist\vs200-steer.exe. Uses .venv when present (setup.cmd), else python on PATH (CI).
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%~dp0"
"%PY%" -m PyInstaller --noconfirm --clean --onefile --console --name vs200-steer ^
  --paths src --collect-submodules bleak --collect-submodules winrt --collect-submodules zeroconf ^
  packaging\entry.py || exit /b 1
"dist\vs200-steer.exe" --check
