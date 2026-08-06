# Privacy Module Agent Instructions

## Module Purpose
The `privacy` module handles all data tracking, auditing, and encryption for the Bunker project. It is critical for proving the "Zero Data Exfiltration" claim for the hackathon by providing transparent, real-time metrics and historical logs.

## Audit Log Format
- **Format**: JSON Lines (.jsonl), one event per line.
- **Fields**: `timestamp`, `event_type`, `session_id`, `is_local`, `bytes_processed`, `details` (dict).
- **Event Type Constants**:
  - `EVENT_INFERENCE`
  - `EVENT_TOOL_CALL`
  - `EVENT_DATA_ACCESS`
  - `EVENT_USER_ACTION`
  - `EVENT_PERMISSION`

## Data Flow Monitor
- **Purpose**: Real-time tracking of data entering/leaving the local system.
- **Events to Record**: API requests, database reads/writes, external service calls.
- **Listener Pattern**: Components (like the UI dashboard) register callbacks to receive live updates when data flows occur.

## Encryption
- **Tool**: `cryptography.fernet.Fernet`
- **Key Location**: `./data/memory/encryption.key` (Auto-generated if missing)
- **When to Use**: Encrypting sensitive user files (like calendar caches or emails) at rest.

## Critical Invariants
- **Log EVERYTHING**: Log EVERY inference and tool call — never skip.
- **Locality Tracking**: Set `is_local=True` for all local operations. Set `is_local=False` ONLY for external API calls (e.g., Radeon Cloud API fallback).
- **Dashboard Integrity**: Dashboard data is used for judge evidence — ensure `local_percentage` is accurate and highly visible.

## Wires Into
- `PrivacyDashboard` connects `AuditLogger` and `DataFlowMonitor` to the `gradio_app.py` UI.
- `ReActAgent` calls `AuditLogger.log_inference()` and `log_tool_call()`.
