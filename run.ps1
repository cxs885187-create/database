param([int]$Port = 8000, [switch]$Setup)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the Python virtual environment.' }
    $Setup = $true
}
if ($Setup) {
    & $pythonPath -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $pythonPath -m spacy download en_core_web_sm
    if ($LASTEXITCODE -ne 0) { throw 'English spaCy model installation failed.' }
}
Write-Output "Vocabulary server: http://127.0.0.1:$Port"
& $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port $Port
