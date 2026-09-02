<#
  Loads .secrets.ps1, verifies the four credentials are present, then runs the
  credentialed VGS data adapters.

    .\scripts\run-us-data.ps1            # smoke pass: 1 symbol, short ranges
    .\scripts\run-us-data.ps1 -Full     # full pass: 7 symbols, 2020-2026 ranges

  Each step is independent; a failure in one is reported and the script moves on.
#>
[CmdletBinding()]
param([switch]$Full)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONPATH = 'src'
$env:PYTHONDONTWRITEBYTECODE = '1'

$secrets = Join-Path $root '.secrets.ps1'
if (-not (Test-Path $secrets)) { Write-Error ".secrets.ps1 not found at $secrets"; exit 1 }
. $secrets

$missing = @()
foreach ($v in 'SEC_USER_AGENT','ALPACA_API_KEY_ID','ALPACA_API_SECRET_KEY','FRED_API_KEY') {
    $val = [Environment]::GetEnvironmentVariable($v)
    if ([string]::IsNullOrWhiteSpace($val) -or $val -like 'FILL_ME*') { $missing += $v }
}
if ($missing.Count) { Write-Error ("Fill these in .secrets.ps1 first: " + ($missing -join ', ')); exit 1 }
Write-Host ("SEC_USER_AGENT = {0}" -f $env:SEC_USER_AGENT) -ForegroundColor DarkGray
Write-Host ("Alpaca key id  = {0}..." -f $env:ALPACA_API_KEY_ID.Substring(0,[Math]::Min(4,$env:ALPACA_API_KEY_ID.Length))) -ForegroundColor DarkGray

if ($Full) {
    $symbols = @('GOOGL','MRVL','MU','SNDK','ADI','NVDA','QCOM')
    $barStart = '2023-01-01'; $barEnd = '2026-09-02'
    $fredStart = '2020-01-01'; $fredEnd = '2026-09-01'
    $mode = 'FULL'
} else {
    $symbols = @('GOOGL')
    $barStart = '2026-06-01'; $barEnd = '2026-09-02'
    $fredStart = '2026-01-01'; $fredEnd = '2026-09-01'
    $mode = 'SMOKE'
}
Write-Host "=== $mode pass ===" -ForegroundColor Cyan

function Step($name, [scriptblock]$body) {
    Write-Host "`n--- $name ---" -ForegroundColor Yellow
    $sw = [Diagnostics.Stopwatch]::StartNew()
    & $body
    $code = $LASTEXITCODE
    $sw.Stop()
    Write-Host ("[{0}] exit={1} in {2:n1}s" -f $name, $code, $sw.Elapsed.TotalSeconds) -ForegroundColor ($(if($code){'Red'}else{'Green'}))
}

Step 'sec-security-master' { python -m vgs.cli sec-security-master --data-root data }
Step 'fred'                { python -m vgs.cli fred --series DGS10 --start $fredStart --end $fredEnd --vintage-date 2026-09-01 --data-root data }
Step 'alpaca-bars'         { python -m vgs.cli alpaca-bars @symbols --start $barStart --end $barEnd --feed iex --data-root data }
if ($Full) {
    Step 'fred (all series)' { python -m vgs.cli fred --start $fredStart --end $fredEnd --vintage-date 2026-09-01 --data-root data }
}

Write-Host "`n=== files in data\normalized ===" -ForegroundColor Cyan
Get-ChildItem data\normalized -File | Select-Object Name, Length, LastWriteTime | Format-Table -AutoSize
