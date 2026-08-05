"""Determinex model-routing layer.

Promotes the advisory ``scripts/model_advisor.py`` into a typed runtime
routing surface. The router never calls a model — it produces a structured
decision the caller can either honor (live mode) or record (dry-run mode).

Public surface:

  from models.model_router import (
      ModelRouter, TaskClass, ModelRole, RouteDecision, RouterMode,
      DEFAULT_ROUTES, CURRENT_MODEL_IDS, STALE_MODEL_IDS,
  )
  from models.model_router_record import RouteRecord
  from models.model_inventory import LocalModelInventory
"""

from __future__ import annotations
