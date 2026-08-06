$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Speech

$scriptDir = $PSScriptRoot
$outputDir = Join-Path $scriptDir "final\audio"
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$segments = @(
    @{
        Id = "01-overview"
        Start = 0.5
        Text = "Solo Worker OS turns a freelancer's scattered business admin into one private, conversational workflow."
    },
    @{
        Id = "02-live-status"
        Start = 15.0
        Text = "The provider is local. The Radeon-hosted model is reachable, and Qwen three, four B is being served through vee L L M."
    },
    @{
        Id = "03-create-project"
        Start = 25.0
        Text = "I describe a new client in plain Chinese: the work, budget, and deadline. The agent extracts those details and calls create project. No form filling."
    },
    @{
        Id = "04-generate-contract"
        Start = 37.0
        Text = "In the next turn, it reuses that project context and calls generate contract. The service agreement includes the client, fee, deadline, and working terms."
    },
    @{
        Id = "05-trace"
        Start = 49.0
        Text = "Each run is observable. The trace records the router decision, model call, tool execution, result, and latency."
    },
    @{
        Id = "06-result"
        Start = 60.0
        Text = "The new project now appears in the business workspace. The recording is backed by a dedicated AMD Radeon GPU running rock em, vee L L M, and Qwen three, four B."
    }
)

function Read-WaveFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ([System.Text.Encoding]::ASCII.GetString($bytes, 0, 4) -ne "RIFF") {
        throw "Not a RIFF file: $Path"
    }

    $offset = 12
    $format = $null
    $data = $null
    while ($offset + 8 -le $bytes.Length) {
        $chunkId = [System.Text.Encoding]::ASCII.GetString($bytes, $offset, 4)
        $chunkSize = [BitConverter]::ToInt32($bytes, $offset + 4)
        $chunkStart = $offset + 8
        if ($chunkId -eq "fmt ") {
            $format = New-Object byte[] $chunkSize
            [Array]::Copy($bytes, $chunkStart, $format, 0, $chunkSize)
        } elseif ($chunkId -eq "data") {
            $data = New-Object byte[] $chunkSize
            [Array]::Copy($bytes, $chunkStart, $data, 0, $chunkSize)
        }
        $offset = $chunkStart + $chunkSize + ($chunkSize % 2)
    }

    if (-not $format -or -not $data) {
        throw "Missing fmt or data chunk: $Path"
    }

    [PSCustomObject]@{ Format = $format; Data = $data }
}

function Write-WaveFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][byte[]]$Format,
        [Parameter(Mandatory = $true)][byte[]]$Data
    )

    $stream = [System.IO.File]::Create($Path)
    $writer = New-Object System.IO.BinaryWriter($stream)
    try {
        $ascii = [System.Text.Encoding]::ASCII
        $writer.Write($ascii.GetBytes("RIFF"))
        $writer.Write([int](4 + 8 + $Format.Length + 8 + $Data.Length))
        $writer.Write($ascii.GetBytes("WAVE"))
        $writer.Write($ascii.GetBytes("fmt "))
        $writer.Write([int]$Format.Length)
        $writer.Write($Format)
        $writer.Write($ascii.GetBytes("data"))
        $writer.Write([int]$Data.Length)
        $writer.Write($Data)
    } finally {
        $writer.Dispose()
        $stream.Dispose()
    }
}

$probe = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $probe.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo }
$voice = $voices | Where-Object { $_.Culture.Name -eq "en-US" } | Select-Object -First 1
if (-not $voice) { $voice = $voices | Select-Object -First 1 }
if (-not $voice) { throw "No Windows speech synthesis voice is installed." }
$voiceName = $voice.Name
$probe.Dispose()

$rendered = @()
foreach ($segment in $segments) {
    $path = Join-Path $outputDir ($segment.Id + ".wav")
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SelectVoice($voiceName)
    $synth.Rate = 0
    $synth.Volume = 100
    $synth.SetOutputToWaveFile($path)
    $synth.Speak($segment.Text)
    $synth.Dispose()

    $wave = Read-WaveFile -Path $path
    $byteRate = [BitConverter]::ToInt32($wave.Format, 8)
    $duration = [Math]::Round($wave.Data.Length / $byteRate, 3)
    $rendered += [PSCustomObject]@{
        id = $segment.Id
        start_seconds = $segment.Start
        duration_seconds = $duration
        file = [System.IO.Path]::GetFileName($path)
        text = $segment.Text
        wave = $wave
    }
}

$baseFormat = $rendered[0].wave.Format
$byteRate = [BitConverter]::ToInt32($baseFormat, 8)
$blockAlign = [BitConverter]::ToInt16($baseFormat, 12)
$trackDuration = 74.56
$trackLength = [int]([Math]::Ceiling($trackDuration * $byteRate / $blockAlign) * $blockAlign)
$trackData = New-Object byte[] $trackLength

for ($i = 0; $i -lt $rendered.Count; $i++) {
    $item = $rendered[$i]
    $startByte = [int]([Math]::Floor($item.start_seconds * $byteRate / $blockAlign) * $blockAlign)
    $copyLength = [Math]::Min($item.wave.Data.Length, $trackData.Length - $startByte)
    if ($copyLength -gt 0) {
        [Array]::Copy($item.wave.Data, 0, $trackData, $startByte, $copyLength)
    }

    if ($i + 1 -lt $rendered.Count) {
        $end = $item.start_seconds + $item.duration_seconds
        $nextStart = $rendered[$i + 1].start_seconds
        if ($end -gt $nextStart) {
            Write-Warning "$($item.id) overlaps the next segment by $([Math]::Round($end - $nextStart, 2)) seconds."
        }
    }
}

$timedPath = Join-Path $outputDir "solo-worker-os-live-radeon-voiceover-en.wav"
Write-WaveFile -Path $timedPath -Format $baseFormat -Data $trackData

$metadata = $rendered | Select-Object id, start_seconds, duration_seconds, file, text
$metadata | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $outputDir "voiceover-segments.json") -Encoding utf8

$lines = @(
    "# English Voiceover Timing",
    "",
    "Voice: $voiceName",
    "",
    "| Segment | Start | Duration | File |",
    "| --- | ---: | ---: | --- |"
)
foreach ($item in $metadata) {
    $lines += "| $($item.id) | $($item.start_seconds) s | $($item.duration_seconds) s | $($item.file) |"
}
$lines += ""
$lines += "Timed track: solo-worker-os-live-radeon-voiceover-en.wav ($trackDuration s)"
$lines | Set-Content -Path (Join-Path $outputDir "VOICEOVER_TIMINGS.md") -Encoding utf8

Write-Output "Voice: $voiceName"
Write-Output "Segments: $($rendered.Count)"
Write-Output "Timed track: $timedPath"
