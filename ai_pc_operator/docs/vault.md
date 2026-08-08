# Screen-AI Password Vault

## Overview

The password vault is a **local encrypted credential store** that allows Screen-AI to automate logins while keeping passwords secure.

## Security

### Encryption

- **Algorithm**: AES-256-GCM
- **Key Derivation**: Argon2id
- **Storage**: SQLite (encrypted blobs)
- **Memory**: Wiped on lock

### Master Key

- User-defined passphrase
- Never stored on disk
- Required to unlock vault
- Session expires after 5 minutes

### Credential Records

```json
{
  "site": "example.com",
  "username": "user@example.com",
  "encrypted_password": "base64_encrypted_blob",
  "nonce": "base64_nonce",
  "salt": "base64_salt",
  "created_at": "2026-07-19T19:30:00",
  "last_used": "2026-07-19T20:15:00"
}
```

## Usage Flow

### Adding Credential

```
1. User: "Save password for github.com"
2. AI: Opens vault unlock dialog on phone
3. User: Enters master key
4. Vault: Decrypts
5. User: Enters username and password
6. Vault: Encrypts and stores
7. AI: Confirms saved
```

### Using Credential

```
1. User: "Login to github.com"
2. AI: Opens github.com
3. AI: Detects login page
4. AI: Requests vault unlock on phone
5. User: Enters master key
6. Vault: Decrypts github.com password
7. AI: Fills username and password
8. AI: Submits form
9. AI: Wipes password from memory
10. AI: Continues task
```

### Locking Vault

**Automatic**:
- After 5 minutes of inactivity
- When user logs out
- When emergency stop is triggered

**Manual**:
- User says "Lock vault"
- User closes app
- User clicks lock button

## Implementation

### Key Derivation

```python
from argon2 import PasswordHasher

hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MB
    parallelism=4
)

# Derive key from master password
key = hasher.hash(master_password)
```

### Encryption

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Generate key from master password
key = derive_key(master_password, salt)

# Encrypt password
aesgcm = AESGCM(key)
nonce = os.urandom(12)
ciphertext = aesgcm.encrypt(nonce, password.encode(), None)

# Store: nonce + ciphertext
```

### Decryption

```python
# Decrypt password
aesgcm = AESGCM(key)
password = aesgcm.decrypt(nonce, ciphertext, None).decode()

# Use password
fill_form(password)

# Wipe from memory
password = None
```

## Security Best Practices

### Do

✅ Use strong master key (12+ characters)
✅ Lock vault when not in use
✅ Use unique passwords per site
✅ Enable 2FA where possible
✅ Review vault entries regularly
✅ Backup vault encrypted backup

### Don't

❌ Share master key
❌ Store master key on disk
❌ Log decrypted passwords
❌ Screenshot during password entry
❌ Use weak master key
❌ Reuse master key for other services

## Passkey Support

For passkeys, Screen-AI does **not** store the secret. Instead:

```
1. User: "Login to Microsoft with passkey"
2. AI: Opens Microsoft login
3. AI: Clicks "Sign in with passkey"
4. Windows/Edge: Shows passkey prompt
5. AI: Requests phone approval
6. User: Approves on phone
7. Windows/Edge: User authenticates (biometric/PIN)
8. AI: Waits for success
9. AI: Continues after login
```

**Passkeys cannot be exported** - they stay in Windows Hello / browser.

## Vault Management

### List Entries

```bash
GET /vault/list
```

Returns:
```json
{
  "entries": [
    {
      "site": "github.com",
      "username": "user@example.com",
      "created_at": "2026-07-19T19:30:00",
      "last_used": "2026-07-19T20:15:00"
    }
  ]
}
```

### Add Entry

```bash
POST /vault/add
{
  "site": "github.com",
  "username": "user@example.com",
  "password": "encrypted_blob"
}
```

### Delete Entry

```bash
POST /vault/delete
{
  "site": "github.com"
}
```

### Backup Vault

```bash
POST /vault/backup
{
  "destination": "encrypted_backup_file.vault"
}
```

### Restore Vault

```bash
POST /vault/restore
{
  "source": "encrypted_backup_file.vault"
}
```

## Threat Model

### Protected Against

✅ Local file access (encrypted at rest)
✅ Memory dumps (wiped on lock)
✅ Log analysis (redacted)
✅ Shoulder surfing (phone approval)
✅ Network sniffing (local only)

### Not Protected Against

❌ Compromised master key
❌ Malware on PC
❌ Physical access to unlocked vault
❌ Screen recording during password entry

## Future Enhancements

- Biometric unlock (Windows Hello)
- Hardware security key support
- Vault sync across devices (encrypted)
- Auto-fill browser extension
- Password generator
- Breach detection
