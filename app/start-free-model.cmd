@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 setup_local_model.py
pause
