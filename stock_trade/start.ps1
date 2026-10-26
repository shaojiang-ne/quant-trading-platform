$env:PYTHONPATH = $PSScriptRoot
$env:STOCK_TRADE_API_KEY = "stock_trade_secret_key"
& "$PSScriptRoot\venv\Scripts\python.exe" "$PSScriptRoot\main.py"