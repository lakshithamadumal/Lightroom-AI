@echo off
title Lightroom AI - Media Studio Web UI
echo =======================================================
echo   Starting Lightroom AI Studio Server...
echo =======================================================
echo.
start http://localhost:8000
python server.py
pause
