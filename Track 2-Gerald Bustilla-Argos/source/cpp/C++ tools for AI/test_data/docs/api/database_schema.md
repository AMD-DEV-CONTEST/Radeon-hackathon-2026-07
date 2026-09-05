# Database Schema

## Tables

### users
- id (PK, UUID)
- username (VARCHAR, UNIQUE)
- password_hash (VARCHAR)
- created_at (TIMESTAMP)

### sessions
- token (PK, VARCHAR)
- user_id (FK, UUID)
- expires_at (TIMESTAMP)

### migrations
- id (PK, SERIAL)
- filename (VARCHAR)
- executed_at (TIMESTAMP)
