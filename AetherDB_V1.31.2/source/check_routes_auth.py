"""V1.24.9 Route-level auth coverage test."""
import sys, os
sys.path.insert(0, os.path.abspath("."))
from fastapi.routing import APIRoute
from main import app

PUBLIC = {("/", "GET"), ("/docs", "GET"), ("/redoc", "GET"), ("/openapi.json", "GET")}
PUBLIC_PROBES = {("/health", "GET")}

# Web routes (Jinja2 pages, not API — no API key required)
WEB_ROUTES = {
    ("GET", "/add"), ("GET", "/search"), ("GET", "/timeline"),
    ("GET", "/admin"), ("GET", "/import"),
    ("POST", "/admin/entity/{entity_id}/delete"),
    ("GET", "/admin/search/quick"),
    ("POST", "/admin/import/preview"), ("POST", "/admin/import/confirm"),
}

# Routes with custom auth (NOVEL_API_KEY env var, not our Depends system)
CUSTOM_AUTH_MODULES = {"api.search_semantic", "api.rag_context", "api.consistency_check", "api.translate", "routes.web"}

def extract_deps(route):
    deps = set()
    for d in route.dependant.dependencies:
        if hasattr(d.call, "__name__"):
            deps.add(d.call.__name__)
    return deps

def test_all_routes_have_auth():
    failures = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for m in (route.methods or set()):
            if m in ("HEAD", "OPTIONS"): continue
            key = (route.path, m)
            if key in PUBLIC: continue
            deps = extract_deps(route)
            if key in PUBLIC_PROBES:
                status = "probe"
            elif route.endpoint.__module__ in CUSTOM_AUTH_MODULES:
                status = "custom_auth"
            elif "require_admin" in deps:
                status = "admin"
            elif any(dep.startswith("require_capability_") for dep in deps):
                status = "capability"
            elif "get_current_user_role" in deps or "get_api_key" in deps:
                status = "user"
            elif "probe_api_key_status" in deps:
                status = "probe"
            elif "require_desktop_handshake" in deps:
                status = "custom_auth"
            else:
                status = "UNKNOWN"
                failures.append((m, route.path, route.endpoint.__module__))
            print(f"  [{status.upper():7}] {m:6} {route.path}")

    print("\n" + "Failures: " + str(len(failures)))
    web_fails = 0
    for m, p, mod in failures:
        if (p, m) in WEB_ROUTES or mod in CUSTOM_AUTH_MODULES:
            web_fails += 1
    print("Web/custom_auth: " + str(web_fails))
    real = []
    for m, p, mod in failures:
        if (p, m) not in WEB_ROUTES and mod not in CUSTOM_AUTH_MODULES:
            real.append((m, p, mod))
    print("Real issues: " + str(len(real)))
    for m, p, mod in real:
        print("  " + str(m) + " " + str(p))
    assert not real, "Routes without auth: " + str(real)
    print("ALL OK")

if __name__ == "__main__":
    test_all_routes_have_auth()
