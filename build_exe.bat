@echo off
cd /d "%~dp0"
pip install pyinstaller -r requirements.txt
pyinstaller --onefile --windowed --uac-admin --name EclipseSkip --add-data "templates;templates" app.py
echo.
echo dist\EclipseSkip.exe was created.
pause
