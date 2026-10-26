$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectDir

& "$projectDir\venv\Scripts\python.exe" "$projectDir\main.py"
