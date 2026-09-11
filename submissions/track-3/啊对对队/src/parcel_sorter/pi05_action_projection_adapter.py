"""Opt-in full PI0.5 action input/output projection adaptation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


PI05_FULL_ACTION_PROJECTION_MODULES = ("action_in_proj", "action_out_proj")
PI05_FULL_ACTION_PROJECTION_PROTOCOL = "parcel-pi05-full-action-io-projections-v1"


def checkpoint_uses_full_pi05_action_projections(peft_config: Any) -> bool:
    """Return whether both action projections are fully stored by PEFT."""

    modules = (
        peft_config.get("modules_to_save")
        if isinstance(peft_config, Mapping)
        else getattr(peft_config, "modules_to_save", None)
    )
    configured = set(modules or ())
    return set(PI05_FULL_ACTION_PROJECTION_MODULES) <= configured


def configure_pi05_full_action_projection_peft_defaults(
    defaults: dict[str, Any],
) -> dict[str, Any]:
    """Fully train new-embodiment action I/O layers instead of LoRA-wrapping them."""

    result = dict(defaults)
    target_modules = result.get("target_modules")
    if not isinstance(target_modules, str):
        raise RuntimeError("PI0.5 full action projections require regex PEFT targets")
    for module in PI05_FULL_ACTION_PROJECTION_MODULES:
        target_modules = target_modules.replace(f"{module}|", "")
        target_modules = target_modules.replace(f"|{module}", "")
        if module in target_modules:
            raise RuntimeError(f"unable to remove {module} from PI0.5 LoRA targets")
    result["target_modules"] = target_modules
    modules_to_save = list(result.get("modules_to_save") or ())
    for module in PI05_FULL_ACTION_PROJECTION_MODULES:
        if module not in modules_to_save:
            modules_to_save.append(module)
    result["modules_to_save"] = modules_to_save
    return result


def install_pi05_full_action_projection_adapter() -> None:
    """Patch LeRobot PI0.5 PEFT defaults for full action I/O adaptation."""

    from lerobot.policies.pi05.modeling_pi05 import PI05Policy

    if getattr(PI05Policy, "_parcel_full_action_projection_installed", False):
        return
    original_peft_defaults = PI05Policy._get_default_peft_targets

    def peft_defaults(self: Any) -> dict[str, Any]:
        defaults = original_peft_defaults(self)
        if defaults is None:
            raise RuntimeError("PI0.5 does not expose PEFT target defaults")
        return configure_pi05_full_action_projection_peft_defaults(defaults)

    PI05Policy._get_default_peft_targets = peft_defaults
    PI05Policy._parcel_full_action_projection_installed = True
