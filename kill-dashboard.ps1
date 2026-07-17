Get-NetTCPConnection -LocalPort 8788 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
  Write-Host ("Killed pid {0}" -f $_.OwningProcess)
}
Start-Sleep -Seconds 2
Write-Host "Done"