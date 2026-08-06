$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Login = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8081/api/auth/login" `
    -ContentType "application/json" -Body '{"username":"admin","password":"Admin@123"}'
$Headers = @{ Authorization = "Bearer $($Login.token)" }
$Files = Get-ChildItem -LiteralPath (Join-Path $Root "sample-data") -File
foreach ($File in $Files) {
    Write-Host "Uploading $($File.Name)..."
    $Result = & curl.exe --silent --show-error --fail `
        -H "Authorization: Bearer $($Login.token)" `
        -F "file=@$($File.FullName)" `
        "http://127.0.0.1:8081/api/documents"
    if ($LASTEXITCODE -ne 0) { throw "Upload failed for $($File.Name)" }
}
Write-Host "Sample corpus loaded." -ForegroundColor Green
