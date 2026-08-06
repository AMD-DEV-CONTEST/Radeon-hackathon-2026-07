from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from glass_gateway.frontend import frontend_page

router = APIRouter()

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
}


def _page(name: str) -> HTMLResponse:
    return HTMLResponse(
        frontend_page(name).read_text(encoding="utf-8"),
        headers=NO_CACHE_HEADERS,
    )


@router.get("/memory", response_class=HTMLResponse)
async def memory_page() -> HTMLResponse:
    return _page("memory.html")


@router.get("/memory/capsules", response_class=HTMLResponse)
async def memory_capsules_page() -> HTMLResponse:
    return _page("memory.html")


@router.get("/memory/search", response_class=HTMLResponse)
async def memory_search_page() -> HTMLResponse:
    return _page("memory-search.html")


@router.get("/memory/corrections", response_class=HTMLResponse)
async def memory_corrections_page() -> HTMLResponse:
    return _page("corrections.html")


@router.get("/commitments", response_class=HTMLResponse)
async def commitments_page() -> HTMLResponse:
    return _page("commitments.html")


@router.get("/daily", response_class=HTMLResponse)
async def daily_review_page() -> HTMLResponse:
    return _page("daily-report.html")


@router.get("/objects/search", response_class=HTMLResponse)
async def object_search_page() -> HTMLResponse:
    return _page("object-search.html")


@router.get("/people", response_class=HTMLResponse)
async def people_page() -> HTMLResponse:
    return _page("people.html")


@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page() -> HTMLResponse:
    return _page("integrations.html")


@router.get("/login", response_class=HTMLResponse)
async def login_page() -> HTMLResponse:
    return _page("login.html")


@router.get("/project", response_class=HTMLResponse)
async def project_page() -> HTMLResponse:
    return _page("project.html")
