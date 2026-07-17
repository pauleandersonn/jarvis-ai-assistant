Set-Location 'C:\Users\paule\Projects\jarvis-ai-assistant'
$env:JARVIS_DASHBOARD_PORT = 8788
Start-Process -FilePath 'python' `
  -ArgumentList 'dashboard.py' `
  -WorkingDirectory (Get-Location) `
  -RedirectStandardOutput 'dashboard.log' `
  -RedirectStandardError 'dashboard.err.log' `
  -WindowStyle Hidden
Start-Sleep -Seconds 5
Write-Host "Started"