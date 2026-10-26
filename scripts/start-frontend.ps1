$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path $PSScriptRoot -Parent) 'frontend')
# 2026-09-27: switched to production mode (build + start).
# Reason: Next 16 Turbopack dev server is broken on this machine -
# it serves the page shell but client components never hydrate,
# so every page hangs at its loading text. Production mode works.
# Build takes ~20s on each launch; pages then load much faster than dev.
& npm.cmd run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& npm.cmd run start
exit $LASTEXITCODE
