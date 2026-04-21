$nodePath = "C:\Program Files\WindowsApps\OpenAI.Codex_26.415.4716.0_x64__2p2nqsd0c76g0\app\resources\node.exe"
$projectPath = "C:\Users\Utilisateur\Desktop\appli transport"

if (-not (Test-Path $nodePath)) {
  Write-Host "Node n'a pas ete trouve a l'emplacement attendu:" -ForegroundColor Red
  Write-Host $nodePath -ForegroundColor Yellow
  exit 1
}

Set-Location $projectPath

Write-Host "Demarrage de LoadSearch..." -ForegroundColor Cyan
Write-Host "Serveur local: http://localhost:3000" -ForegroundColor Green
Write-Host ""

& $nodePath "server.js"
