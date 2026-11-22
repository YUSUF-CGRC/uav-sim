@echo off
REM Kullanim (Komut Istemi / cmd icinde):   sim gps_yok
REM 1) Bu pencerede senaryo ve sahte kamera ayarlarini yapar
REM 2) Sahte Cube'u yeni bir pencerede baslatir
REM Sonra AYNI pencerede kendi kodunu calistir:
REM    python -m preflight --config config_sim.toml --check-only

set "SENARYO=%~1"
if "%SENARYO%"=="" set "SENARYO=normal"
if not exist "%~dp0scenarios\%SENARYO%.toml" (
    echo Senaryo bulunamadi: %~dp0scenarios\%SENARYO%.toml
    echo Mevcut senaryolar:
    dir /b "%~dp0scenarios"
    exit /b 1
)
set "UAV_SIM_SCENARIO=%~dp0scenarios\%SENARYO%.toml"
set "PYTHONPATH=%~dp0sim_libs;%~dp0"
start "Sahte Cube - %SENARYO%" cmd /k python -m uav_sim
echo.
echo Senaryo: %SENARYO%
echo Sahte Cube yeni pencerede acildi.
echo Bu pencerede kendi kodunu calistirabilirsin (sahte kamera aktif).
echo Baglanti adresi: udpin:0.0.0.0:14560
