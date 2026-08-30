# 이 저장소의 커밋 훅(.githooks/)을 활성화한다. 클론 후 1회.
#   powershell -ExecutionPolicy Bypass -File scripts\setup-hooks.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
git config core.hooksPath .githooks
Write-Host "core.hooksPath = .githooks  (pre-commit 활성)"
