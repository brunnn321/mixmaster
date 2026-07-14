@echo off
rem Lanzador de MixMaster — abre la app sin dejar consola abierta
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" main.py
