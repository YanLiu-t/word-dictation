# Build the portable Windows package (for GitHub Releases only).
# Usage: powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m PyInstaller --noconfirm --clean --onedir --console `
    --name cet6-dictation `
    --paths "src" `
    --add-data "src/dictation/web.py;ui" `
    --add-data "prompts;prompts" `
    --add-data "config.example.json;." `
    --copy-metadata streamlit `
    --copy-metadata altair `
    --copy-metadata pandas `
    --collect-all streamlit `
    packaging\launcher.py

Write-Host ""
Write-Host "Done: dist\cet6-dictation\cet6-dictation.exe"
Write-Host "Zip the whole dist\cet6-dictation folder and upload it to GitHub Releases."
