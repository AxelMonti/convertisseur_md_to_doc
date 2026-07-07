@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================================
echo   Construction de MD_vers_DOCX.exe
echo ============================================================

REM -- Vérification Python -----------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou absent du PATH.
    pause & exit /b 1
)

REM -- Dépendances Python ------------------------------------------
echo.
echo [1/4] Installation des dependances Python...
pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo [2/4] Installation de PyInstaller...
pip install pyinstaller
if errorlevel 1 goto :error

REM -- S'assurer que python -m PyInstaller fonctionne même hors PATH --
set "PYINSTALLER_CMD=python -m PyInstaller"

REM -- Téléchargement de Pandoc ------------------------------------
echo.
echo [3/4] Verification / telechargement de Pandoc...
python -c "import pypandoc; pypandoc.download_pandoc()" 2>nul
if errorlevel 1 (
    echo   Pandoc est peut-etre deja dans le PATH, on continue...
)

REM -- Récupération du chemin du binaire pandoc --------------------
for /f "usebackq delims=" %%P in (
    `python -c "import pypandoc; print(pypandoc.get_pandoc_path())"`
) do set "PANDOC_BIN=%%P"

if not defined PANDOC_BIN (
    echo [ERREUR] Impossible de trouver le binaire pandoc.
    goto :error
)
echo   Pandoc trouve : !PANDOC_BIN!

REM -- Build PyInstaller -------------------------------------------
echo.
echo [4/4] Creation de l'executable...

%PYINSTALLER_CMD% ^
    --onefile ^
    --windowed ^
    --name "MD_vers_DOCX" ^
    --add-binary "!PANDOC_BIN!;." ^
    main.py

if errorlevel 1 goto :error

echo.
echo ============================================================
echo   Succes ! Executable disponible dans : dist\MD_vers_DOCX.exe
echo ============================================================
goto :end

:error
echo.
echo ============================================================
echo   ECHEC de la construction. Voir les erreurs ci-dessus.
echo ============================================================

:end
pause
endlocal
