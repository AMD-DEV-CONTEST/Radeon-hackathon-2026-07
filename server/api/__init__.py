"""Versioned HTTP API package.

Aggregates feature routers. Each feature follows:
``schema → repository → service → router``.
"""

from fastapi import APIRouter

from api.auth.router import router as auth_router
from api.candidate.router import router as candidate_router
from api.interview.router import router as interview_router
from api.report.router import router as report_router
from api.resume.router import router as resume_router
from api.websocket.router import router as websocket_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(resume_router)
api_router.include_router(interview_router)
api_router.include_router(report_router)
api_router.include_router(candidate_router)
api_router.include_router(websocket_router)

__all__ = ["api_router"]
