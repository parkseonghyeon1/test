@echo off
cd /d "%~dp0"
pip install pyinstaller -r requirements.txt
pyinstaller --onefile --name EclipseSkip skip_bot.py
xcopy /E /I /Y templates dist\templates
echo.
echo dist\EclipseSkip.exe and dist\templates were created.
pause
