@echo off
setlocal

set "MSYS_BASH=C:\msys64\usr\bin\bash.exe"
if not exist "%MSYS_BASH%" (
  echo MSYS2 bash was not found at %MSYS_BASH%.
  exit /b 1
)

set "BUILD_JOBS=%~1"
if "%BUILD_JOBS%"=="" set "BUILD_JOBS=4"

pushd "%~dp0"
"%MSYS_BASH%" -c "export PATH=/ucrt64/bin:/usr/bin; make -j%BUILD_JOBS% EXTERNAL_DEFINES=-DUSE_MULTIPLAYER"
set "BUILD_RESULT=%ERRORLEVEL%"
popd

if not "%BUILD_RESULT%"=="0" (
  echo Multiplayer build failed with exit code %BUILD_RESULT%.
  exit /b %BUILD_RESULT%
)

echo Multiplayer build completed.
exit /b 0
