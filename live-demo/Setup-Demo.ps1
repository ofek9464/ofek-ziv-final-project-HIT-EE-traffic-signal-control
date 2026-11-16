$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = (Get-Command python.exe -ErrorAction Stop).Source
& $pythonPath -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11 or newer is required'"
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer first.' }
& $pythonPath -m venv .venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
$demoPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $demoPython -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'Could not install CPU PyTorch. Check the Internet connection.' }
& $demoPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Could not install demo dependencies.' }
& $demoPython -c "import PIL, numpy, torch, sumolib, traci; print('Python dependencies are ready')"
if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
Write-Output 'Setup complete. Install SUMO, then double-click Start-Web-Demo.cmd.'
