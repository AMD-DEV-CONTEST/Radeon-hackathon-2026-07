$ErrorActionPreference = "Stop"
$Login = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/api/auth/login" `
    -ContentType "application/json" -Body '{"username":"admin","password":"Admin@123"}'
$Headers = @{ Authorization = "Bearer $($Login.token)" }
$Dashboard = Invoke-RestMethod -Uri "http://127.0.0.1:8081/api/dashboard" -Headers $Headers
if ($Dashboard.documents -lt 1) { throw "No documents indexed. Run load-sample-data.ps1." }
$Answer = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/api/chat/query" -Headers $Headers `
    -ContentType "application/json" -Body '{"question":"Why did Pump P-101 fail repeatedly in 2025?","assetTag":"P-101"}'
if (-not $Answer.answer -or $Answer.citations.Count -lt 1) { throw "Answer or citations missing." }
$Rca = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/api/assets/P-101/rca" -Headers $Headers
if ($Rca.probableCauses.Count -lt 1) { throw "RCA causes missing." }
Write-Host "Smoke test passed: login, dashboard, RAG answer, citations, and RCA." -ForegroundColor Green
Write-Host "Mode: $($Answer.mode); citations: $($Answer.citations.Count); confidence: $($Answer.confidence)"
