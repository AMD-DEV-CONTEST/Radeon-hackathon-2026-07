"""Post-commit hooks — executed after a successful pipeline commit.

Not a plugin system. Internal strategy implementations.
Built-in: VectorStoreSync, GlobalIndexSync, ConsistencyCheckTrigger.
"""
from abc import ABC, abstractmethod
import logging

log = logging.getLogger(__name__)


class PostCommitHook(ABC):
    """Strategy: run after successful pipeline commit."""
    name: str = "base"
    @abstractmethod
    def after_commit(self, changeset, result: dict):
        ...


class VectorStoreSyncHook(PostCommitHook):
    """Update vector store with newly imported entities."""
    name = "vector_store_sync"

    def after_commit(self, changeset, result: dict):
        eid_map = result.get("entity_id_map", {})
        if not eid_map:
            return
        try:
            from services.vector_store import import_entity_to_vector_store
            for title, eid in eid_map.items():
                ent = next((e for e in changeset.entities if e.get("title") == title), None)
                if ent:
                    import_entity_to_vector_store(eid, ent)
            log.info("Hook: synced %d entities to vector store", len(eid_map))
        except Exception as e:
            log.warning("Hook: vector store sync failed: %s", e)


class GlobalIndexSyncHook(PostCommitHook):
    """Mark global index as dirty after import."""
    name = "global_index_sync"

    def after_commit(self, changeset, result: dict):
        try:
            from services.global_index import mark_database_dirty
            from services.database_registry import get_active_database_id
            mark_database_dirty(get_active_database_id(), "import commit")
            log.info("Hook: global index marked dirty")
        except Exception as e:
            log.warning("Hook: global index sync failed: %s", e)


class ConsistencyCheckTriggerHook(PostCommitHook):
    """Trigger consistency check after large imports."""
    name = "consistency_check"

    def after_commit(self, changeset, result: dict):
        if len(changeset.entities) < 5:
            return
        try:
            from services.consistency import run_check
            from services.database_registry import get_db_path
            run_check(get_db_path(), scope="full", check_types=["character", "timeline"])
            log.info("Hook: consistency check triggered")
        except Exception as e:
            log.warning("Hook: consistency check failed: %s", e)
