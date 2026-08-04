# Data handling

This prototype stores project JSON and uploads in project-specific local directories. Files are never sent to an external service by the application. PNG, JPEG, and WebP images are accepted up to 10 MB by default; content type, decoded format, signature consistency, and size are validated.

Original filenames are not trusted or stored as the storage key. UUID identifiers name projects and assets. Uploads, generated assets, logs, environment files, model weights, and checkpoints are ignored by Git.

Only self-created or rights-cleared sample assets belong in examples. Private client assets, customer data, browser data, secrets, and model weights must not be committed. Production work needs retention, user deletion, access control, backups, encryption, and incident-response policies.
