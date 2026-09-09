# Windows Read-Only Observation

The Windows surface uses seven fixed collectors: system overview, startup applications, running processes, services, scheduled tasks, listening ports, and Windows security posture. Startup inspection reads approved registry locations and Startup folders. Security inspection reports bounded Microsoft Defender and Firewall fields.

Collectors never accept PowerShell, registry paths, WMI queries, filesystem commands, or process command lines from the user or model. Startup arguments and user-profile prefixes are redacted. Unsupported platforms and failed collectors remain visible instead of being described as successful.

This Windows feature is a genuine local extension. It is not presented as the same execution as the Linux Radeon Cloud competition proof.
