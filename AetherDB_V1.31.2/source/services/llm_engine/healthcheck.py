"""Connectivity testing for cloud and local providers."""
from services.llm_engine.manager import AIEngineManager
from services.llm_engine.cloud_provider import test_connection as test_cloud
from services.llm_engine.local_runtime import test_connection as test_local, check_runtime

def check_all() -> dict:
    """Run all health checks."""
    config = AIEngineManager.load_config()
    results = {"cloud": {}, "local": {}}

    cloud_cfg = config.get("cloud", {})
    active = cloud_cfg.get("active_provider", "deepseek")
    results["cloud"] = test_cloud(active, cloud_cfg)

    local_cfg = config.get("local", {})
    if local_cfg.get("enabled", False):
        runtime = check_runtime(local_cfg.get("api_base", "http://localhost:11434"))
        if runtime.get("running"):
            results["local"] = test_local(local_cfg)
        else:
            results["local"] = {"success": False, "error": runtime.get("error", "Not running")}

    return results

def check_cloud(provider_name: str = None) -> dict:
    config = AIEngineManager.load_config()
    cloud_cfg = config.get("cloud", {})
    provider = provider_name or cloud_cfg.get("active_provider", "deepseek")
    return test_cloud(provider, cloud_cfg)

def check_local() -> dict:
    config = AIEngineManager.load_config()
    local_cfg = config.get("local", {})
    runtime = check_runtime(local_cfg.get("api_base", "http://localhost:11434"))
    return runtime
