@echo off
REM Сборка AnymakerRussifier.exe из исходников.
REM Требуется Python 3 и PyInstaller (pip install pyinstaller).
setlocal
cd /d "%~dp0src"

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo PyInstaller не найден. Устанавливаю...
    python -m pip install pyinstaller || goto :err
)

python -m PyInstaller --noconfirm --clean --onefile --console ^
    --name "AnymakerRussifier" ^
    --icon "icon.ico" ^
    --add-data "assets/ru;assets/ru" ^
    --add-data "assets/en;assets/en" ^
    --add-data "icon.png;." ^
    --add-data "icon.ico;." ^
    russifier.py || goto :err

echo.
echo Готово. EXE: src\dist\AnymakerRussifier.exe
copy /Y "dist\AnymakerRussifier.exe" "..\AnymakerRussifier.exe" >nul
echo Скопировано в корень репозитория.
pause
exit /b 0

:err
echo.
echo Ошибка сборки.
pause
exit /b 1
