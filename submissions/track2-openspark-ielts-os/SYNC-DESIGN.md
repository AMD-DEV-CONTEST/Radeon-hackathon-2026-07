# Account and sync contract

The current build is local-first. Export/import works offline, merges array/object data, and saves a private pre-import snapshot under `ielts-os.preImportBackup.v1` before changing data.

## Production contract

- Use Sign in with Apple plus one backend user ID. Never use email as a database key.
- Encrypt transport with HTTPS and encrypt server backups at rest.
- Store each learning record with `id`, `updatedAt`, `deletedAt`, and `deviceId`.
- Resolve ordinary records with newest `updatedAt`; merge append-only learning events by `id`; retain tombstones for 30 days so deletions propagate.
- Keep writing versions and speaking sessions immutable. A new edit creates a new version rather than overwriting history.
- Show last successful sync, pending count, and conflict count. Learning must remain usable when offline.
- Provide export and full account/data deletion in the app. Purge primary data and backups within the published retention period.

Provider selection and credentials remain an external decision. Implement the adapter only after choosing one provider; CloudKit is the shortest Apple-only path, while Supabase/Firebase better supports later web/Android clients.

