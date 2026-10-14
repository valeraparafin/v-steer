@echo off
rem Build dist\V-Steer.exe and run its --check (see packaging\build.py).
rem Uses .venv when present (setup.cmd), else python on PATH (CI).
setlocal
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0packaging\build.py"
