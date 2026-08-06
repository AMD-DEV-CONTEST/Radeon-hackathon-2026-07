"""Iron Law System - UAS 铁律核心模块"""

def decompose(*a, **kw):
    from iron_law.decomposer import decompose as _decompose
    return _decompose(*a, **kw)

def record_decomposition_outcome(*a, **kw):
    from iron_law.decomposer import record_decomposition_outcome as _fn
    return _fn(*a, **kw)

# ILS v2.2 exports
from iron_law.intent_packet import IntentPacket, IntentType
from iron_law.participants import (
    ParticipantRole, DerivationSource, ParticipantEntry,
    TaskParticipants, derive_roles, validate_assignment,
)
from iron_law.ownership import OwnershipRegistry, get_registry, OwnershipConflictError
from iron_law.hooks import HookBlockError

__all__ = [
    "decompose",
    "record_decomposition_outcome",
    "IntentPacket",
    "IntentType",
    "OwnershipRegistry",
    "get_registry",
    "OwnershipConflictError",
    "HookBlockError",
    "ParticipantRole",
    "DerivationSource",
    "ParticipantEntry",
    "TaskParticipants",
    "derive_roles",
    "validate_assignment",
]
