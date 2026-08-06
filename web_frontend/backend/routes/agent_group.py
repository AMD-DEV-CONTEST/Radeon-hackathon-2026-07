"""
Agent 群聊系统 - HTTP API 路由

提供 REST API 接口：
- GET/POST /api/agent-group/groups - 列表/创建群聊
- GET/PATCH/DELETE /api/agent-group/groups/{id} - 单个群聊操作
- POST /api/agent-group/groups/{id}/members - 添加成员
- DELETE /api/agent-group/groups/{id}/members/{package_id} - 移除成员
- POST /api/agent-group/groups/{id}/messages - 发送消息
- POST /api/agent-group/groups/{id}/runs/{run_id}/cancel - 取消 run
- GET /api/agent-group/agents - 可用 Agent 列表
"""

import asyncio
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from agent_factory.agent_group_system import AgentGroupService
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from web_frontend.backend.runtime_bridge import RuntimeBridge


def create_agent_group_router(
    runtime_bridge: RuntimeBridge, service: AgentGroupService
) -> APIRouter:
    """创建 Agent 群聊路由"""
    router = APIRouter(prefix="/api/agent-group", tags=["agent-group"])

    # ===== 群聊会话管理 =====

    @router.get("/groups")
    def list_groups() -> dict[str, Any]:
        """列出所有群聊"""
        try:
            groups = service.list_groups()
            return {"groups": groups}
        except Exception as e:
            raise _http_error(e)

    @router.post("/groups")
    def create_group(payload: dict[str, Any]) -> dict[str, Any]:
        """创建新群聊"""
        try:
            title = payload.get("title", "").strip()
            member_package_ids = payload.get("member_package_ids", [])
            workspace_id = str(payload.get("workspace_id") or "").strip() or None

            if not title:
                raise HTTPException(status_code=400, detail="title is required")

            runtime = _agent_package_runtime(runtime_bridge)
            group = service.create_group(
                title,
                member_package_ids,
                runtime,
                workspace_id=workspace_id,
            )
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.get("/groups/{group_id}")
    def get_group(group_id: str) -> dict[str, Any]:
        """获取群聊详情"""
        try:
            group = service.get_group(group_id)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.patch("/groups/{group_id}")
    def update_group(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """更新群聊"""
        try:
            group = service.update_group(group_id, payload)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.delete("/groups/{group_id}")
    def delete_group(group_id: str) -> dict[str, Any]:
        """删除群聊"""
        try:
            result = service.delete_group(group_id)
            return {"success": result["deleted"], "group_id": group_id}
        except Exception as e:
            raise _http_error(e)

    # ===== 成员管理 =====

    @router.post("/groups/{group_id}/members")
    def add_member(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """添加成员"""
        try:
            package_id = payload.get("package_id", "").strip()
            if not package_id:
                raise HTTPException(status_code=400, detail="package_id is required")

            runtime = _agent_package_runtime(runtime_bridge)
            group = service.add_member(group_id, package_id, runtime)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.delete("/groups/{group_id}/members/{package_id}")
    def remove_member(group_id: str, package_id: str) -> dict[str, Any]:
        """移除成员"""
        try:
            result = service.remove_member(group_id, package_id)
            return {"group": result}
        except Exception as e:
            raise _http_error(e)

    # ===== 消息管理 =====

    @router.post("/groups/{group_id}/messages")
    async def send_message(group_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送用户消息"""
        try:
            content = payload.get("content", "").strip()
            client_message_id = payload.get("client_message_id", "").strip()
            target_package_ids = payload.get("target_package_ids", [])
            reply_to_message_id = str(payload.get("reply_to_message_id") or "").strip() or None
            context_references = payload.get("context_references")

            if not content:
                raise HTTPException(status_code=400, detail="content is required")
            if not client_message_id:
                raise HTTPException(status_code=400, detail="client_message_id is required")
            await asyncio.to_thread(
                service.send_user_message,
                group_id,
                content,
                client_message_id,
                target_package_ids,
                reply_to_message_id=reply_to_message_id,
                context_references=context_references,
            )
            runtime = _agent_package_runtime(runtime_bridge)
            commands = await asyncio.to_thread(service.prepare_queued_run_commands, group_id, runtime)
            for command in commands:
                await runtime_bridge.send_frontend_command(command)

            return {"group": await asyncio.to_thread(service.get_group, group_id)}
        except Exception as e:
            raise _http_error(e)

    # ===== Run 管理 =====

    @router.post("/groups/{group_id}/runs/{run_id}/cancel")
    async def cancel_run(group_id: str, run_id: str) -> dict[str, Any]:
        """Request cancellation; terminal runtime events remain the state transition source."""
        try:
            run = await asyncio.to_thread(service.get_run, run_id)
            if run is None or str(run.get("group_id") or "") != group_id:
                raise HTTPException(status_code=404, detail="group run not found")
            request_id = str(run.get("request_id") or "").strip()
            if request_id:
                await runtime_bridge.send_frontend_command(
                    FactoryFrontendCommand(
                        type="cancel_runtime_request",
                        mode="agent_group",
                        payload={"target_request_id": request_id, "reason": "user_cancelled"},
                    )
                )
            else:
                await asyncio.to_thread(service.cancel_run, run_id)
            group = await asyncio.to_thread(service.get_group, group_id)
            return {"group": group}
        except Exception as e:
            raise _http_error(e)

    @router.post("/groups/{group_id}/runs/{run_id}/resume")
    async def resume_run(group_id: str, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            run = await asyncio.to_thread(service.get_run, run_id)
            if run is None or str(run.get("group_id") or "") != group_id:
                raise HTTPException(status_code=404, detail="group run not found")
            if str(run.get("status") or "") != "awaiting_approval":
                raise HTTPException(status_code=409, detail="group run is not awaiting approval")
            request_id = uuid4().hex
            await asyncio.to_thread(service.update_run, run_id, {"request_id": request_id})
            await runtime_bridge.send_frontend_command(
                FactoryFrontendCommand(
                    type="resume_interrupt",
                    request_id=request_id,
                    mode="agent_group",
                    payload={**payload, "group_run_id": run_id, "mode": "agent_group"},
                )
            )
            return {"group": await asyncio.to_thread(service.get_group, group_id)}
        except Exception as e:
            raise _http_error(e)

    @router.post("/groups/{group_id}/runs/{run_id}/retry")
    async def retry_run(group_id: str, run_id: str) -> dict[str, Any]:
        try:
            run = await asyncio.to_thread(service.get_run, run_id)
            if run is None or str(run.get("group_id") or "") != group_id:
                raise HTTPException(status_code=404, detail="group run not found")
            await asyncio.to_thread(service.retry_run, run_id)
            runtime = _agent_package_runtime(runtime_bridge)
            commands = await asyncio.to_thread(service.prepare_queued_run_commands, group_id, runtime)
            for command in commands:
                await runtime_bridge.send_frontend_command(command)
            return {"group": await asyncio.to_thread(service.get_group, group_id)}
        except Exception as e:
            raise _http_error(e)

    # ===== Agent 列表 =====

    @router.get("/agents")
    def list_agents() -> dict[str, Any]:
        """List the same published packages exposed by the normal Agent surface."""
        try:
            runtime = _agent_package_runtime(runtime_bridge)
            packages = runtime.list_packages()
            agents = [
                {
                    "package_id": str(pkg.get("package_id") or ""),
                    "agent_name": str(pkg.get("agent_name") or pkg.get("name") or pkg.get("package_id") or ""),
                    "agent_description": pkg.get("agent_description") or pkg.get("description"),
                    "status": str(pkg.get("status") or "available"),
                }
                for pkg in packages
                if str(pkg.get("package_id") or "").strip()
            ]

            return {"agents": agents}
        except Exception as e:
            raise _http_error(e)

    return router


def _http_error(exc: Exception) -> HTTPException:
    """将异常转为 HTTP 错误"""
    if isinstance(exc, HTTPException):
        return exc

    # 简化错误处理
    detail = str(exc)
    if "not found" in detail.lower():
        return HTTPException(status_code=404, detail=detail)
    elif "already exists" in detail.lower():
        return HTTPException(status_code=409, detail=detail)
    else:
        return HTTPException(status_code=500, detail=detail)


def _agent_package_runtime(runtime_bridge: RuntimeBridge):
    adapter = runtime_bridge.adapter
    runtime = getattr(adapter, "agent_package_runtime", None) if adapter is not None else None
    if runtime is None:
        raise RuntimeError("runtime service not started")
    return runtime
