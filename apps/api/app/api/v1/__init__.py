"""
API v1 路由汇总 (M0 精简版)

M0 阶段只保留 auth + teleoperation REST 端点.
datasets / training / users / files 在 M2 随数据层恢复.
"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    agents,
    auth,
    billing,
    copilot,
    datasets,
    hub,
    marketplace,
    models,
    record,
    setup,
    skills,
    stats,
    teleoperation,
    trainings,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["认证"])
api_router.include_router(agents.router, prefix="/agents", tags=["Local Agent"])
api_router.include_router(
    teleoperation.router, prefix="/teleoperation", tags=["遥操作"]
)
api_router.include_router(record.router, prefix="/record", tags=["录制代理"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["数据集"])
api_router.include_router(trainings.router, prefix="/trainings", tags=["训练任务"])
api_router.include_router(models.router, prefix="/models", tags=["模型"])
api_router.include_router(stats.router, prefix="/stats", tags=["平台统计"])
api_router.include_router(hub.router, prefix="/hub", tags=["AI Hub"])
api_router.include_router(setup.router, prefix="/setup", tags=["Setup / Onboarding"])
api_router.include_router(skills.router, prefix="/skills", tags=["Skills"])
api_router.include_router(billing.router, prefix="/billing", tags=["Billing"])
api_router.include_router(marketplace.router, prefix="/marketplace", tags=["Marketplace"])
api_router.include_router(copilot.router, prefix="/copilot", tags=["Copilot"])
# TODO(M4): 恢复 users, files 路由
