Write-Host "Starting Personal Expense Tracker..." -ForegroundColor Cyan

if (Test-Path ".\.venv\Scripts\python.exe") {
    & ".\.venv\Scripts\python.exe" app.py
} elseif (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe") {
    & "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" app.py
} else {
    python app.py
}

