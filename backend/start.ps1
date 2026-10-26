& .\venv\Scripts\Activate.ps1

$proc = Start-Process -FilePath "python" -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--reload-dir", "app", "--host", "0.0.0.0", "--port", "8000" -NoNewWindow -PassThru

try {
    Wait-Process -InputObject $proc
} catch {
    # Ctrl+C triggers OperationCanceledException
} finally {
    if (!$proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        # Kill child uvicorn reloader process
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$($proc.Id)" | ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}
