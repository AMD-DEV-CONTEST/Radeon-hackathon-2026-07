"""
VM manager — lifecycle management for desktop agent VMs.
Hard rule: no host desktop control. VM or no run.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

_REQUIRE_VM = os.environ.get("DETERMINEX_REQUIRE_VM", "1") == "1"


@dataclass
class VMInfo:
    vm_id: str
    provider: str  # "virtualbox" | "qemu" | "hyper-v" | "vmware"
    state: str  # "stopped" | "running" | "paused" | "snapshot"
    ip: str = ""
    ssh_port: int = 22
    rdp_port: int = 3389
    snapshot_name: str = ""


class VMManager:
    """
    Manages a pool of VMs for desktop agent isolation.
    Supports VirtualBox (primary), QEMU, Hyper-V.
    """

    def __init__(self, provider: str = "virtualbox") -> None:
        self.provider = provider
        self._active_vms: dict[str, VMInfo] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, vm_id: str) -> VMInfo:
        log.info("[vm_manager] starting VM %s (provider=%s)", vm_id, self.provider)
        if self.provider == "virtualbox":
            return self._vbox_start(vm_id)
        if self.provider == "qemu":
            return self._qemu_start(vm_id)
        raise NotImplementedError(f"Provider {self.provider} not supported yet")

    def stop(self, vm_id: str) -> None:
        log.info("[vm_manager] stopping VM %s", vm_id)
        if self.provider == "virtualbox":
            self._vbox_stop(vm_id)
        elif self.provider == "qemu":
            self._qemu_stop(vm_id)
        self._active_vms.pop(vm_id, None)

    def restore_snapshot(self, vm_id: str, snapshot: str) -> None:
        log.info("[vm_manager] restoring snapshot %s on VM %s", snapshot, vm_id)
        if self.provider == "virtualbox":
            subprocess.run(
                ["VBoxManage", "snapshot", vm_id, "restore", snapshot],
                check=True,
                capture_output=True,
            )

    def take_snapshot(self, vm_id: str, name: str) -> None:
        if self.provider == "virtualbox":
            subprocess.run(
                ["VBoxManage", "snapshot", vm_id, "take", name, "--live"],
                check=True,
                capture_output=True,
            )

    def is_running(self, vm_id: str) -> bool:
        return vm_id in self._active_vms and self._active_vms[vm_id].state == "running"

    def require_vm_or_raise(self, vm_id: str) -> VMInfo:
        """Enforce VM isolation. Raises RuntimeError if VM not running and DETERMINEX_REQUIRE_VM=1."""
        if not self.is_running(vm_id):
            if _REQUIRE_VM:
                raise RuntimeError(
                    f"[vm_manager] Desktop agent requires a running VM (vm_id={vm_id}). "
                    "Start the VM first or set DETERMINEX_REQUIRE_VM=0 to disable enforcement (not recommended)."
                )
            log.warning(
                "[vm_manager] VM %s not running — DETERMINEX_REQUIRE_VM=0, proceeding without isolation",
                vm_id,
            )
        return self._active_vms.get(
            vm_id, VMInfo(vm_id=vm_id, provider=self.provider, state="unknown")
        )

    # ------------------------------------------------------------------
    # VirtualBox backend
    # ------------------------------------------------------------------

    def _vbox_start(self, vm_id: str) -> VMInfo:
        try:
            result = subprocess.run(
                ["VBoxManage", "startvm", vm_id, "--type", "headless"],
                capture_output=True,
                text=True,
                check=True,
            )
            info = VMInfo(vm_id=vm_id, provider="virtualbox", state="running")
            self._active_vms[vm_id] = info
            return info
        except FileNotFoundError:
            raise RuntimeError(
                "VBoxManage not found. Install VirtualBox or set DETERMINEX_REQUIRE_VM=0."
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"VBoxManage startvm failed: {exc.stderr}") from exc

    def _vbox_stop(self, vm_id: str) -> None:
        try:
            subprocess.run(
                ["VBoxManage", "controlvm", vm_id, "savestate"],
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            log.warning("[vm_manager] VBox stop failed (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # QEMU backend (stub)
    # ------------------------------------------------------------------

    def _qemu_start(self, vm_id: str) -> VMInfo:
        raise NotImplementedError("QEMU backend not yet implemented. Use virtualbox.")

    def _qemu_stop(self, vm_id: str) -> None:
        raise NotImplementedError("QEMU backend not yet implemented.")
