@echo off
REM ============================================================
REM  Violette POS — Build Script
REM  Compila el .exe con PyInstaller
REM ============================================================
echo.
echo  ========================================
echo   Violette POS - Compilacion .exe
echo  ========================================
echo.

REM Verificar que estamos en el directorio correcto
if not exist "launcher.py" (
    echo ERROR: Ejecute este script desde la raiz del proyecto.
    echo        No se encontro launcher.py
    pause
    exit /b 1
)

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no encontrado en PATH.
    pause
    exit /b 1
)

REM Verificar PyInstaller
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo Instalando PyInstaller...
    pip install pyinstaller==6.11.1
)

REM Limpiar builds anteriores
echo [1/4] Limpiando builds anteriores...
if exist "build" rmdir /s /q build
if exist "dist" rmdir /s /q dist

REM Compilar
echo [2/4] Compilando con PyInstaller...
echo        (Esto puede tardar 2-5 minutos)
echo.
pyinstaller violette_pos.spec --noconfirm

if errorlevel 1 (
    echo.
    echo ERROR: La compilacion fallo. Revise los errores arriba.
    pause
    exit /b 1
)

REM Copiar archivos necesarios al directorio de distribución
echo [3/4] Copiando archivos adicionales...

REM .env template
if exist ".env.example" copy /y ".env.example" "dist\ViolettePOS\.env.example" >nul

REM Crear directorio de backups
mkdir "dist\ViolettePOS\data\backups" 2>nul

REM Crear directorio de PDFs
mkdir "dist\ViolettePOS\data\pdfs" 2>nul

REM Crear directorio de certs
mkdir "dist\ViolettePOS\certs" 2>nul

echo [4/4] Build completado!
echo.
echo  ========================================
echo   Resultado: dist\ViolettePOS\
echo   Ejecutable: dist\ViolettePOS\ViolettePOS.exe
echo  ========================================
echo.
echo  Para crear el instalador, ejecute:
echo    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
echo.
pause