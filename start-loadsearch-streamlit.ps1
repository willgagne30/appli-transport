$pythonPath = "C:\Users\Utilisateur\AppData\Local\Programs\Python\Python312\python.exe"
$projectPath = "C:\Users\Utilisateur\Desktop\appli transport"

if (-not (Test-Path $pythonPath)) {
  Write-Host "Python n'a pas ete trouve a l'emplacement attendu:" -ForegroundColor Red
  Write-Host $pythonPath -ForegroundColor Yellow
  exit 1
}

Set-Location $projectPath

Write-Host "Demarrage de LoadSearch avec Streamlit..." -ForegroundColor Cyan
Write-Host "Ouvrez ensuite: http://localhost:8501" -ForegroundColor Green
Write-Host ""

& $pythonPath -m streamlit run "streamlit_app.py"
