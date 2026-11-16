param([switch]$NoBrowser, [switch]$Serve)

$ErrorActionPreference = 'Stop'
$demoUrl = 'http://127.0.0.1:8765'
$demoProcess = $null
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = (Get-Command python.exe).Source
}
if (-not $env:SUMO_HOME) {
    foreach ($sumoDirectory in @('C:\Program Files (x86)\Eclipse\Sumo', 'C:\Program Files\Eclipse\Sumo')) {
        if (Test-Path -LiteralPath (Join-Path $sumoDirectory 'bin\sumo.exe')) {
            $env:SUMO_HOME = $sumoDirectory
            break
        }
    }
}
if ($env:SUMO_HOME) { $env:Path = (Join-Path $env:SUMO_HOME 'bin') + ';' + $env:Path }

if ($Serve) {
    $demoMutex = [System.Threading.Mutex]::new($false, 'Local\HITTrafficDemo8765')
    $ownsMutex = $false
    try {
        try { $ownsMutex = $demoMutex.WaitOne(0) }
        catch [System.Threading.AbandonedMutexException] { $ownsMutex = $true }
        if (-not $ownsMutex) { return }
        while ($true) {
            $worker = Start-Process -FilePath $pythonPath `
                -ArgumentList '-u', 'web_demo.py', '--no-browser' `
                -WorkingDirectory $PSScriptRoot -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $PSScriptRoot 'web-server.log') `
                -RedirectStandardError (Join-Path $PSScriptRoot 'web-server-errors.log') `
                -PassThru
            $worker.WaitForExit()
            Add-Content -LiteralPath (Join-Path $PSScriptRoot 'web-supervisor.log') `
                -Value "$(Get-Date -Format o) worker $($worker.Id) exited $($worker.ExitCode), restarting"
            Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'web-server-errors.log') `
                -Destination (Join-Path $PSScriptRoot 'web-server-errors-previous.log') -Force
            Start-Sleep -Seconds 2
        }
    }
    finally {
        if ($ownsMutex) { $demoMutex.ReleaseMutex() }
        $demoMutex.Dispose()
    }
    return
}

for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $state = $null
    try {
        $state = Invoke-RestMethod "$demoUrl/api/state" -TimeoutSec 2
    }
    catch {
        # SUMO and PyTorch may still be starting.
    }
    if ($null -ne $state -and $state.PSObject.Properties.Name -contains 'runs') {
        if (-not $NoBrowser) { Start-Process $demoUrl }
        Write-Output "HIT Traffic Lab is running at $demoUrl"
        return
    }

    if ($null -eq $demoProcess) {
        $demoProcess = Start-Process -FilePath 'powershell.exe' `
            -ArgumentList '-NoProfile', '-File', "`"$PSCommandPath`"", '-Serve' `
            -WorkingDirectory $PSScriptRoot -WindowStyle Hidden `
            -PassThru
    }
    if ($demoProcess.HasExited) {
        throw "The demo stopped. See $PSScriptRoot\web-server-errors.log"
    }
    Start-Sleep -Milliseconds 250
}

throw "The demo did not respond. See $PSScriptRoot\web-server-errors.log"
