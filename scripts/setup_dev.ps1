#Requires -Version 5.1
<#
.SYNOPSIS
    Windows equivalent of scripts/setup_dev.sh -- see that file for the
    canonical (bash) version this must stay in step with.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

python -m venv .venv

$Py = ".venv\Scripts\python.exe"

& $Py -m pip install --upgrade pip
& $Py -m pip install -r requirements.txt -r requirements-dev.txt

Write-Host "Dev environment ready. Activate with: .venv\Scripts\Activate.ps1"
