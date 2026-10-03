@echo off
cd "%~dp0"
call npm --prefix frontend install
call py -m pip install -r requirements.txt
call npm --prefix frontend run build
call py main.py