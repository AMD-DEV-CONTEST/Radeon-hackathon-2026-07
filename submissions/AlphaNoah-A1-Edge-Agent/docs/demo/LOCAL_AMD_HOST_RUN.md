# Local AMD Host Run Evidence

Recorded: 2026-07-23T18:05:54+08:00

## Purpose

Record the narrow AMD fact actually verified during the P0 build. This is not a
ROCm or GPU-inference benchmark.

## Read-only host inventory

Commands:

```powershell
[System.Environment]::OSVersion.VersionString
python --version
Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name
Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name
```

Observed:

| Item | Result |
|---|---|
| OS | Microsoft Windows NT 10.0.26200.0 |
| Python | 3.11.9 |
| CPU/APU | AMD Ryzen 7 8845H w/ Radeon 780M Graphics |
| AMD display adapter | AMD Radeon(TM) 780M |

A virtual display driver was also present but is not part of the AlphaNoah claim.
No hostname, username, device serial or network information is retained here.

## Executed software evidence

On this host:

- ten standard-library unit tests passed;
- the explicit approval demo reached `CLOSED` and emitted 20 AuditRecords;
- the explicit rejection demo reached `REJECTED`;
- inputs came from local synthetic JSON and state was written to local SQLite;
- the formal runtime imports no network client or third-party package.

## Exact boundary

Supported statement:

> The AlphaNoah local closed-loop prototype and its tests ran successfully on a
> Windows host with an AMD Ryzen 7 8845H / Radeon 780M platform.

Not supported:

- ROCm was used by this Windows run;
- the Radeon GPU performed inference or accelerated the workflow;
- the external Ryzen AI Max+ 395 Linux environment was independently rerun;
- AMD-specific performance optimization has been implemented.

The next AMD integration task must run a pinned model/Provider on the audited Linux
prototype and preserve direct ROCm/GPU evidence.
