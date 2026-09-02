"""AI Engine configuration and health API endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from app.dependencies.auth import get_current_user_role, require_admin
from services.llm_engine.manager import AIEngineManager
from services.llm_engine.healthcheck import check_cloud, check_local
from services.llm_engine.model_profiles import get_profiles
from services.audit_log import log_event
from services.db import get_db
from services.database_registry import get_active_database_id, get_active_book_id
from app.models import AnalysisPreferencesUpdate
from services.model_registry import list_eligible_model_profiles, get_provider

router = APIRouter(tags=["ai_engine"])

@router.get("/api/ai/status")
def api_ai_status(role: str = Depends(get_current_user_role)):
    """Get AI Engine initialization status and mode."""
    return AIEngineManager.get_status()

@router.get("/api/ai/config")
def api_ai_config(_: None = Depends(require_admin)):
    """Get current LLM configuration."""
    return {"llm": AIEngineManager.load_config()}

@router.post("/api/ai/config")
def api_ai_config_update(updates: dict, _: None = Depends(require_admin)):
    """Update LLM configuration."""
    result = AIEngineManager.update_config(updates)
    db = get_db()
    try:
        log_event(
            db,
            "ai.config.update",
            "AI config updated by admin",
            target="llm",
            database_id=get_active_database_id(),
            book_id=get_active_book_id(),
            success=True,
        )
    finally:
        db.close()
    return {"status": "ok", "llm": result}


@router.get("/api/ai/analysis-preferences")
def api_analysis_preferences(role: str = Depends(get_current_user_role)):
    preferences = AIEngineManager.get_analysis_preferences()
    cloud_available = any(
        (get_provider(profile["provider_id"]) or {}).get("provider_type")
        not in {"local", "local_ollama", "ollama"}
        for profile in list_eligible_model_profiles()
    )
    return {
        **preferences,
        "available_modes": ["local_rules", "cloud_model"],
        "local_rules_available": True,
        "cloud_model_available": cloud_available,
    }


@router.put("/api/ai/analysis-preferences")
def api_update_analysis_preferences(
    payload: AnalysisPreferencesUpdate,
    _: None = Depends(require_admin),
):
    result = AIEngineManager.update_analysis_preferences(payload.default_mode)
    db = get_db()
    try:
        log_event(
            db,
            "ai.analysis_preferences.update",
            "Import analysis preference updated",
            target=payload.default_mode,
            database_id=get_active_database_id(),
            book_id=get_active_book_id(),
            success=True,
        )
    finally:
        db.close()
    return {"status": "ok", **result}

@router.post("/api/ai/test-cloud")
def api_ai_test_cloud(provider_name: str = None, _: None = Depends(require_admin)):
    """Test cloud provider connectivity."""
    return check_cloud(provider_name)

@router.post("/api/ai/test-local")
def api_ai_test_local(role: str = Depends(get_current_user_role)):
    """Test local Ollama provider connectivity."""
    return check_local()

@router.get("/api/ai/model-profiles")
def api_ai_model_profiles(role: str = Depends(get_current_user_role)):
    """List available model configuration profiles."""
    return {"profiles": get_profiles()}

@router.post("/api/ai/local/check-runtime")
def api_ai_check_runtime(_: None = Depends(require_admin)):
    """Check if local Ollama runtime is running."""
    from services.llm_engine.local_runtime import check_runtime
    from services.llm_engine.manager import AIEngineManager
    cfg = AIEngineManager.load_config()
    base_url = cfg.get("local", {}).get("api_base", "http://localhost:11434")
    return check_runtime(base_url)

# ---- Cache Stats ----
@router.get("/api/cache/stats")
def api_cache_stats(role: str = Depends(get_current_user_role)):
    """Get cache statistics."""
    from services.cache import cache_stats
    return cache_stats()
