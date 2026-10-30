@echo off
chcp 65001 >nul
title HivisionIDPhotos µ÷ÊÔÄ£Ê½
cd /d "%~dp0"
"%~dp0runtime\python.exe" "%~dp0app\desktop_app.py"
if errorlevel 1 pause
