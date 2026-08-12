@echo off
REM Corrida diaria de precio-radar. La registra Task Scheduler al mediodia.
REM
REM El orden importa: si py_fetch falla (bloqueo de PerimeterX, sin internet,
REM notebook recien despertada), no se ingesta nada y el reporte de ayer queda
REM publicado tal cual. Es preferible a publicar un dia incompleto que parezca
REM que los precios cambiaron cuando en realidad no se pudieron leer.

cd /d "%~dp0"
set LOG=data\run-daily.log
echo. >> %LOG%
echo ===== %DATE% %TIME% ===== >> %LOG%

python src\py_fetch.py daily >> %LOG% 2>&1
if errorlevel 1 (
    echo FALLO py_fetch, no se ingesta ni se publica >> %LOG%
    exit /b 1
)

python src\store.py py >> %LOG% 2>&1
if errorlevel 1 (
    echo FALLO store >> %LOG%
    exit /b 1
)

python src\report.py >> %LOG% 2>&1
if errorlevel 1 (
    echo FALLO report >> %LOG%
    exit /b 1
)

REM Publicar. Si no hay cambios, git commit devuelve error y no es un problema.
git add data\serie.csv data\py docs >> %LOG% 2>&1
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "precios %DATE%" >> %LOG% 2>&1
    git push >> %LOG% 2>&1
    if errorlevel 1 echo FALLO push, el reporte local esta al dia igual >> %LOG%
) else (
    echo sin cambios para publicar >> %LOG%
)

echo OK >> %LOG%
