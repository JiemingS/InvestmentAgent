$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

uv sync --project $backend --locked
if ($LASTEXITCODE -ne 0) { throw 'Could not install backend dependencies.' }

npm.cmd --prefix $frontend ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Could not install frontend dependencies.' }

$server = Start-Process -FilePath (Join-Path $backend '.venv\Scripts\python.exe') `
    -WorkingDirectory $backend -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
    -WindowStyle Hidden -PassThru
try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($server.HasExited) {
            throw 'FastAPI exited during startup. Check that port 8000 is free and the database is writable.'
        }
        try {
            $api = Invoke-RestMethod 'http://127.0.0.1:8000/openapi.json' -TimeoutSec 1
            if ($api.info.title -eq 'Personal Investment Intelligence Agent') {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }
    if (-not $ready) { throw 'FastAPI did not become ready on port 8000.' }

    Write-Host 'Portfolio UI: http://127.0.0.1:5173'
    Write-Host 'FastAPI docs: http://127.0.0.1:8000/docs'
    Push-Location $frontend
    try {
        node .\node_modules\vite\bin\vite.js --host 127.0.0.1 --strictPort
        if ($LASTEXITCODE -ne 0) { throw 'Vite exited with an error. Check that port 5173 is free.' }
    } finally {
        Pop-Location
    }
} finally {
    if (-not $server.HasExited) { Stop-Process -Id $server.Id }
}
