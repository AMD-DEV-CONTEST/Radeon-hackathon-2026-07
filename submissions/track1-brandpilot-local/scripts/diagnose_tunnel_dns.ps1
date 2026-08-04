[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Hostname,
    [ValidateRange(1, 65535)]
    [int]$Port = 443,
    [ValidateRange(1, 120)]
    [int]$Timeout = 10,
    [string]$PrivateOutputPath = (
        Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) `
            'BrandPilotLocal\private-support\tunnel-dns.private.json'
    ),
    [string]$SanitizedOutputPath = (
        Join-Path (Get-Location) 'support\tunnel-dns-diagnostic.sanitized.json'
    ),
    [switch]$UseCurl
)

$ErrorActionPreference = 'Stop'
$redactedHostname = '<redacted-radeon-tunnel-hostname>'

function Resolve-SafeReportPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][bool]$Private
    )

    if (($Path -split '[\\/]') -contains '..') {
        throw 'Output path traversal is not allowed.'
    }
    if ([IO.Path]::GetExtension($Path) -ne '.json') {
        throw 'Output report must use a .json filename.'
    }

    $resolved = [IO.Path]::GetFullPath($Path)
    $repository = [IO.Path]::GetFullPath((Get-Location).Path).TrimEnd('\') + '\'
    if ($Private -and $resolved.StartsWith(
            $repository,
            [StringComparison]::OrdinalIgnoreCase
        )) {
        throw 'Private output must be stored outside the repository.'
    }
    return $resolved
}

function Write-JsonReport {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$Report
    )

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $Report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Path -Encoding UTF8
}

$privatePath = Resolve-SafeReportPath -Path $PrivateOutputPath -Private $true
$sanitizedPath = Resolve-SafeReportPath -Path $SanitizedOutputPath -Private $false
if ($privatePath -eq $sanitizedPath) {
    throw 'Private and sanitized outputs must differ.'
}

$started = Get-Date
$private = @{
    timestamp_utc = $started.ToUniversalTime().ToString('o')
    timestamp_local = $started.ToString('o')
    hostname = $Hostname
    port = $Port
    timeout_seconds = $Timeout
    dns_resolved = $false
    ipv4_available = $false
    ipv6_available = $false
    resolved_addresses = @()
    dns_error_category = $null
    tcp_attempted = $false
    tcp_succeeded = $false
    tcp_error_category = $null
    https_attempted = $false
    http_status = $null
    https_error_category = $null
    certificate_validation = $false
    final_classification = 'diagnostic_error'
}

if (
    [string]::IsNullOrWhiteSpace($Hostname) -or
    $Hostname.Contains('://') -or
    $Hostname.IndexOfAny([char[]]'/\?#@') -ge 0
) {
    $private.final_classification = 'invalid_hostname'
}
else {
    try {
        $dns = @(Resolve-DnsName -Name $Hostname -DnsOnly -ErrorAction Stop)
        $addresses = @(
            $dns |
                Where-Object { $_.Type -in @('A', 'AAAA') } |
                ForEach-Object { $_.IPAddress } |
                Where-Object { $_ } |
                Select-Object -Unique
        )
        $private.resolved_addresses = $addresses
        $private.ipv4_available = @($dns | Where-Object Type -eq 'A').Count -gt 0
        $private.ipv6_available = @($dns | Where-Object Type -eq 'AAAA').Count -gt 0
        $private.dns_resolved = $addresses.Count -gt 0
    }
    catch {
        $private.dns_error_category = $_.CategoryInfo.Category.ToString()
        $private.final_classification = 'dns_resolution_failed'
    }

    if ($private.dns_resolved) {
        $private.tcp_attempted = $true
        try {
            $tcp = Test-NetConnection `
                -ComputerName $Hostname `
                -Port $Port `
                -InformationLevel Detailed `
                -WarningAction SilentlyContinue
            $private.tcp_succeeded = [bool]$tcp.TcpTestSucceeded
            if (-not $private.tcp_succeeded) {
                $private.final_classification = 'dns_resolved_tcp_failed'
            }
        }
        catch {
            $private.tcp_error_category = $_.CategoryInfo.Category.ToString()
            $private.final_classification = 'dns_resolved_tcp_failed'
        }

        if ($private.tcp_succeeded -and $UseCurl) {
            $private.https_attempted = $true
            try {
                $status = & curl.exe `
                    --head `
                    --silent `
                    --show-error `
                    --max-time $Timeout `
                    --output NUL `
                    --write-out '%{http_code}' `
                    "https://$Hostname/" 2>$null
                if ($LASTEXITCODE -eq 0 -and $status -match '^\d{3}$') {
                    $private.http_status = [int]$status
                    $private.certificate_validation = $true
                    $private.final_classification = 'dns_resolved_https_reachable'
                }
                elseif ($LASTEXITCODE -eq 60) {
                    $private.https_error_category = 'CertificateValidation'
                    $private.final_classification = 'dns_resolved_tls_failed'
                }
                else {
                    $private.https_error_category = 'HttpsRequestFailed'
                    $private.final_classification = 'http_unreachable'
                }
            }
            catch {
                $private.https_error_category = $_.CategoryInfo.Category.ToString()
                $private.final_classification = 'http_unreachable'
            }
        }
        elseif ($private.tcp_succeeded) {
            $private.https_error_category = 'HttpsProbeNotRequested'
            $private.final_classification = 'diagnostic_error'
        }
    }
}

$private.total_duration_seconds = [Math]::Round(
    ((Get-Date) - $started).TotalSeconds,
    3
)

$sanitized = @{
    timestamp_utc = $private.timestamp_utc
    timestamp_local = $private.timestamp_local
    hostname = $redactedHostname
    port = $private.port
    timeout_seconds = $private.timeout_seconds
    dns_resolved = $private.dns_resolved
    ipv4_available = $private.ipv4_available
    ipv6_available = $private.ipv6_available
    dns_error_category = $private.dns_error_category
    tcp_attempted = $private.tcp_attempted
    tcp_succeeded = $private.tcp_succeeded
    tcp_error_category = $private.tcp_error_category
    https_attempted = $private.https_attempted
    http_status = $private.http_status
    https_error_category = $private.https_error_category
    certificate_validation = $private.certificate_validation
    total_duration_seconds = $private.total_duration_seconds
    final_classification = $private.final_classification
}

Write-JsonReport -Path $privatePath -Report $private
Write-JsonReport -Path $sanitizedPath -Report $sanitized
Write-Output "classification=$($private.final_classification)"
