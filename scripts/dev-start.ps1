param(
    [switch]$OpenBrowser,
    [switch]$StartOllama
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

uv sync --project $backend --locked
if ($LASTEXITCODE -ne 0) { throw 'Could not install backend dependencies.' }

npm.cmd --prefix $frontend ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Could not install frontend dependencies.' }

$server = $null
$ollamaServer = $null
try {
    if ($StartOllama) {
        $ollamaUrl = 'http://127.0.0.1:11434'
        if ($env:INVESTMENT_OLLAMA_URL) { $ollamaUrl = $env:INVESTMENT_OLLAMA_URL.TrimEnd('/') }
        if ($ollamaUrl -cnotmatch '^http://(?:127\.0\.0\.1|\[::1\])(?::[0-9]+)?$') {
            throw 'INVESTMENT_OLLAMA_URL must be a loopback HTTP origin.'
        }
        try {
            $tags = Invoke-RestMethod "$ollamaUrl/api/tags" -TimeoutSec 2
        } catch {
            $tags = $null
        }
        if (-not $tags -and $ollamaUrl -eq 'http://127.0.0.1:11434') {
            $ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue
            $installRoot = Split-Path $root -Parent
            $ollamaPath = if ($ollama) { $ollama.Source } else { Join-Path $installRoot 'Ollama\ollama.exe' }
            if (Test-Path -LiteralPath $ollamaPath -PathType Leaf) {
                $models = Join-Path $installRoot 'Models'
                if (-not $env:OLLAMA_MODELS -and (Test-Path -LiteralPath (Join-Path $models 'manifests'))) {
                    $env:OLLAMA_MODELS = $models
                }
                try {
                    $ollamaServer = Start-Process -FilePath $ollamaPath -ArgumentList 'serve' -WindowStyle Hidden -PassThru
                    for ($attempt = 0; $attempt -lt 20 -and -not $ollamaServer.HasExited; $attempt++) {
                        try {
                            $tags = Invoke-RestMethod "$ollamaUrl/api/tags" -TimeoutSec 1
                            break
                        } catch {
                            Start-Sleep -Milliseconds 300
                        }
                    }
                } catch {
                    Write-Warning "Ollama could not start: $($_.Exception.Message)"
                }
            }
        }
        if (-not $tags) {
            Write-Warning 'Ollama is unavailable. The portfolio can still be used. Start Ollama to use Local Agent.'
        } elseif ('gemma4:31b' -notin $tags.models.name) {
            Write-Warning 'Ollama is running, but gemma4:31b was not found in its model list.'
        }
    }

    $server = Start-Process -FilePath (Join-Path $backend '.venv\Scripts\python.exe') `
        -WorkingDirectory $backend -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WindowStyle Hidden -PassThru
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
        $viteArgs = @('--host', '127.0.0.1', '--strictPort')
        if ($OpenBrowser) { $viteArgs += '--open' }
        node .\node_modules\vite\bin\vite.js @viteArgs
        if ($LASTEXITCODE -ne 0) { throw 'Vite exited with an error. Check that port 5173 is free.' }
    } finally {
        Pop-Location
    }
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id }
    if ($ollamaServer -and -not $ollamaServer.HasExited) { Stop-Process -Id $ollamaServer.Id }
}
