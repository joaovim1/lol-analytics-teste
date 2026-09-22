@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    python -m venv .venv
    if errorlevel 1 goto :error
)

echo Instalando e atualizando dependencias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Backend iniciado em http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --port 8000
goto :eof

:error
echo.
echo Falha ao preparar o backend. Veja o erro acima.
pause
exit /b 1
