@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 cell_agent.py --demo
pause
