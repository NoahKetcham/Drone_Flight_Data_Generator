@echo off
cd /d "%~dp0Flight_Generator"
powershell -NoExit -Command "python .\drone_flight_generator.py --web"
