@echo off
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>nul
if errorlevel 1 (
  echo Python 3.10+ is required.
  exit /b 1
)
.venv\Scripts\python.exe -c "import streamlit,httpx,pydantic,pandas,sklearn,rapidfuzz,pypdf,defusedxml,rich,prompt_toolkit,cryptography,fontTools" 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)
exit /b 0
