# Open WebUI public-access and tenant isolation

Open WebUI is the only public chat entry point. Dify remains an internal workflow editor and evaluation surface; do not publish its chat URL or expose its login page from the landing site.

Recommended deployment defaults:

```dotenv
ENABLE_SIGNUP=False
DEFAULT_USER_ROLE=pending
USER_PERMISSIONS_WORKSPACE_KNOWLEDGE_ALLOW_PUBLIC_SHARING=False
USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_PUBLIC_SHARING=False
USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING=False
USER_PERMISSIONS_WORKSPACE_TOOLS_ALLOW_PUBLIC_SHARING=False
```

Provision users individually, approve them from the admin panel, and use groups or explicit grants for any shared knowledge base. Never use the admin account as the public demo account. Keep Dify behind an internal network or authentication boundary.

Open WebUI settings may be persisted in its database. If an environment change appears ignored, apply the same setting in Admin Panel → Settings or temporarily use `ENABLE_PERSISTENT_CONFIG=False` while applying the deployment configuration. Do not delete the persistent volume: it contains user accounts and chats.

References:

- [Open WebUI environment configuration](https://docs.openwebui.com/reference/env-configuration/)
- [Open WebUI RBAC](https://docs.openwebui.com/features/authentication-access/rbac/)
- [Open WebUI hardening](https://docs.openwebui.com/getting-started/advanced-topics/hardening/)
