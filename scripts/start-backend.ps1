$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

# Real knowledge retrieval by default; unconfigured hub degrades honestly instead
# of falling back to demo data. Override with your own environment variables if needed.
if (-not $env:KNOWLEDGE_PROVIDER) { $env:KNOWLEDGE_PROVIDER = 'knowledge_hub' }
if (-not $env:KNOWLEDGE_HUB_BASE_URL) { $env:KNOWLEDGE_HUB_BASE_URL = 'http://127.0.0.1:8200' }

& .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
exit $LASTEXITCODE
