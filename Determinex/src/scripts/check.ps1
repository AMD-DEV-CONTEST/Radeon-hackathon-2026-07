$errs = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile('C:\Dev\Determinex\scripts\quickstart.ps1', [ref] $tokens, [ref] $errs)
$errs | ForEach-Object {
    Write-Host "Error at line $($_.Extent.StartLineNumber): $($_.Message)"
}
