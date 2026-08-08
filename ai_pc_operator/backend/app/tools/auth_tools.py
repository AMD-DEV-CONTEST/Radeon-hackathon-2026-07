"""Authentication tools - password login, passkey login, vault unlock."""

from __future__ import annotations

from typing import Dict, Any, Optional

from app.security.vault import PasswordVault


class AuthTools:
    """Authentication tools."""

    def __init__(self):
        """Initialize auth tools."""
        self.vault = PasswordVault()

    async def prepare(self) -> Dict[str, Any]:
        """Warm cryptography imports without unlocking the vault."""
        try:
            import asyncio

            await asyncio.to_thread(
                __import__,
                "cryptography.hazmat.primitives.ciphers.aead",
            )
            return {"status": "success", "prepared": "cryptography-import"}
        except ImportError:
            return {
                "status": "failed",
                "error": "cryptography is not installed",
            }

    async def vault_unlock(self, master_password: str) -> Dict[str, Any]:
        """Unlock the password vault."""
        try:
            self.vault.unlock(master_password)
            return {
                "status": "success",
                "message": "Vault unlocked",
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def vault_lock(self) -> Dict[str, Any]:
        """Lock the password vault."""
        self.vault.lock()
        return {
            "status": "success",
            "message": "Vault locked",
        }

    async def vault_add(
        self, site: str, username: str, password: str
    ) -> Dict[str, Any]:
        """Add credential to vault."""
        try:
            entry_id = await self.vault.add_credential(
                site, username, password
            )
            return {
                "status": "success",
                "entry_id": entry_id,
                "site": site,
                "username": username,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def vault_get(
        self, site: str, username: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get credential from vault."""
        try:
            cred = await self.vault.get_credential(site, username)
            if not cred:
                return {
                    "status": "failed",
                    "error": f"No credential found for {site}",
                }
            return {
                "status": "success",
                "site": cred["site"],
                "username": cred["username"],
                "password": cred["password"],
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def vault_list(self) -> Dict[str, Any]:
        """List all sites in vault."""
        try:
            sites = await self.vault.list_sites()
            return {
                "status": "success",
                "sites": sites,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def password_login(
        self, site: str, username: Optional[str] = None
    ) -> Dict[str, Any]:
        """Login using saved password."""
        try:
            # Get credential from vault
            cred = await self.vault.get_credential(site, username)
            if not cred:
                return {
                    "status": "failed",
                    "error": f"No saved password for {site}",
                }

            # Use browser tools to login
            from app.tools.browser_tools import BrowserTools
            browser = BrowserTools()

            # Open site
            await browser.open(site)

            # Fill username
            await browser.type('input[name="username"], input[type="email"]', cred["username"])

            # Fill password
            await browser.type('input[name="password"], input[type="password"]', cred["password"])

            # Submit
            await browser.click('button[type="submit"], input[type="submit"]')

            return {
                "status": "success",
                "site": site,
                "message": "Login submitted",
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }

    async def passkey_login(self, site: str) -> Dict[str, Any]:
        """Trigger passkey login flow."""
        try:
            from app.tools.browser_tools import BrowserTools
            browser = BrowserTools()

            # Open site
            await browser.open(site)

            # Click "Sign in with passkey" button
            # This will trigger OS/browser passkey prompt
            await browser.click(
                'button:has-text("passkey"), button:has-text("Passkey")'
            )

            return {
                "status": "success",
                "site": site,
                "message": "Passkey prompt triggered - please approve on your device",
                "requires_user_action": True,
            }
        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }
