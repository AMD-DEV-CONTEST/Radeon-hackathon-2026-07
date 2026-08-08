# Screen-AI Permissions & Access Control

## Access Levels

Screen-AI uses a **6-level access model** to balance capability with safety.

### Level 0: Read-Only (No Approval)

**Actions**:
- Check system status
- List files
- Read file contents
- Search web
- View disk/memory usage

**Examples**:
- "Check my storage"
- "List files in Downloads"
- "How much RAM am I using?"

### Level 1: Open (No Approval)

**Actions**:
- Open applications
- Open websites
- View documents

**Examples**:
- "Open Chrome"
- "Launch Notepad"
- "Go to github.com"

### Level 2: Modify (Maybe Approval)

**Actions**:
- Download files
- Rename files
- Move files
- Copy files

**Examples**:
- "Download VLC"
- "Move file to Documents"
- "Rename document.txt"

**Approval**: Required for executables (.exe, .msi, .bat, etc.)

### Level 3: Sensitive (Mobile Approval Required)

**Actions**:
- Login to websites
- Send emails
- Install software
- Run scripts
- Use credentials

**Examples**:
- "Login to gmail.com"
- "Send email to john@example.com"
- "Install Python"

**Approval**: Always required via phone

### Level 4: Critical (Mobile Approval Required)

**Actions**:
- Delete files
- Bulk operations
- Admin commands
- System modifications

**Examples**:
- "Delete files in Downloads"
- "Run as administrator"
- "Modify system settings"

**Approval**: Always required via phone

**Default Method**: Quarantine (reversible)

### Level 5: Dangerous (Special Mode Only)

**Actions**:
- Permanent delete
- Format drive
- Export credentials
- Financial transactions

**Examples**:
- "Permanently delete all files"
- "Format C: drive"
- "Transfer money"

**Approval**: Requires **Full Access Session** (time-limited, explicit)

## Approval Flow

### Standard Approval

```
1. User sends command
2. Agent classifies intent
3. Risk assessment determines level
4. If level ≥ 3 → create approval request
5. Phone receives notification
6. User reviews:
   - Action type
   - Target
   - Impact summary
   - Risk level
7. User approves/rejects
8. If approved → execute
9. If rejected → cancel
10. Log decision
```

### Approval Request Format

```json
{
  "id": 123,
  "command_id": 456,
  "action_type": "delete_files",
  "target": "C:\\Users\\brigh\\Downloads",
  "risk_level": 4,
  "description": "Delete all files in Downloads",
  "impact_summary": {
    "files_affected": 248,
    "total_size": "3.2 GB",
    "method": "quarantine"
  },
  "created_at": "2026-07-19T19:30:00",
  "expires_at": "2026-07-19T19:35:00"
}
```

### Phone Approval Screen

```
┌─────────────────────────────────┐
│  ⚠️ Critical Action             │
│                                 │
│  Delete files in:               │
│  C:\Users\brigh\Downloads       │
│                                 │
│  Files affected: 248            │
│  Total size: 3.2 GB             │
│  Method: Quarantine (reversible)│
│                                 │
│  [✓ Approve]  [✗ Reject]        │
└─────────────────────────────────┘
```

## Protected Paths

**Always require explicit approval**:

```
C:\Windows
C:\Program Files
C:\Program Files (x86)
C:\Users\<user>\AppData
Browser credential stores
SSH keys
.env files
Wallet files
```

## Dangerous File Extensions

**Never auto-execute**:

```
.exe
.msi
.bat
.cmd
.ps1
.vbs
.scr
.jar
.js
```

**Require approval before running**.

## Emergency Stop

**Always Available**:
- Red STOP button on phone
- `POST /emergency/stop` endpoint
- Cancels all pending operations
- Kills running tools
- Logs emergency stop event

**Cannot be disabled**.

## Full Access Session

**For Level 5 actions**:

```
Requirements:
- Phone approval
- Time-limited (5-15 minutes)
- Visible on PC
- Emergency stop enabled
- All actions logged (except secrets)

Activation:
1. User requests full access
2. Phone shows warning
3. User confirms
4. Session starts with timer
5. Auto-expires after timeout
```

## Audit Logging

**All actions logged**:
- Command ID
- Device ID
- Action type
- Target
- Risk level
- Approval status
- Execution result
- Timestamp

**Secrets redacted**:
- Passwords
- Tokens
- API keys
- Credit cards
- SSN

## Non-Negotiable Rules

1. **Critical actions require phone approval**
2. **Passwords are redacted from logs**
3. **Destructive actions use quarantine first**
4. **Emergency stop always works**
5. **All non-secret actions are logged**
6. **Login target domain shown before approval**
7. **Downloaded executables require approval**
8. **Full access sessions are time-limited**
9. **Model proposes actions; tool system executes**
10. **User can wipe logs, vault, memory, quarantine**
