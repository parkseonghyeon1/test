@echo off
cd /d "%~dp0"
pip install pyinstaller -r requirements.txt
pyinstaller --onefile --console --name EclipseSkip --add-data "templates;templates" skip_bot.py
echo.
echo dist\EclipseSkip.exe was created.
pause
