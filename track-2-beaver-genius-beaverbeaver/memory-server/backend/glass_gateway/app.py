from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from glass_gateway.app_state import app_state_registry
from glass_gateway.auth_middleware import UserContextMiddleware
from glass_gateway.frontend import frontend_root
from glass_gateway.routes.device_ws import router as device_ws_router
from glass_gateway.routes.auth import router as auth_router
from glass_gateway.routes.health import router as health_router
from glass_gateway.routes.memory import router as memory_router
from glass_gateway.routes.media import router as media_router
from glass_gateway.routes.openclaw_ws import router as openclaw_ws_router
from glass_gateway.routes.preview import router as preview_router
from glass_gateway.routes.project import router as project_router
from glass_gateway.routes.presence_evaluation import router as presence_evaluation_router
from glass_gateway.routes.web import router as web_router


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    states = app_state_registry.all()
    startup_background_tasks: list[asyncio.Task[None]] = []

    async def recover_pending_events(state) -> None:
        try:
            await state.memory_capsule_bridge.submit_pending_event_queues()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "sealed event recovery deferred user_id=%s: %s",
                state.settings.everos_user_id,
                exc,
            )

    async def warm_speech_presence(state) -> None:
        try:
            await state.speech_presence.warmup()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "speech presence warmup failed user_id=%s: %s",
                state.settings.everos_user_id,
                exc,
            )

    for state in states:
        state.everos_bridge.start_retry_loop()
        state.memory_capsule_bridge.start_retry_loop()
        state.correction_writeback.start_retry_loop()
        # Backlog recovery may wait on EverOS and external providers. It is
        # durable and retryable, so it must not prevent the ingestion API from
        # accepting new device traffic after a restart.
        startup_background_tasks.append(
            asyncio.create_task(recover_pending_events(state))
        )
        state.daily_review_scheduler.start()
        if state.object_perception is not None:
            await state.object_perception.start()
        if state.voice_perception is not None:
            await state.voice_perception.start()
        if state.identity_perception is not None:
            await state.identity_perception.start()
        if state.speech_presence is not None:
            # Loading the local VAD stack can take tens of seconds per user.
            # Keep HTTP/device ingestion available while those models warm in
            # the background; analyze() remains safe because the detector has
            # its own load lock and will wait for the same initialization.
            startup_background_tasks.append(
                asyncio.create_task(warm_speech_presence(state))
            )
    try:
        yield
    finally:
        for task in startup_background_tasks:
            if not task.done():
                task.cancel()
        if startup_background_tasks:
            await asyncio.gather(*startup_background_tasks, return_exceptions=True)
        for state in reversed(states):
            if state.object_perception is not None:
                await state.object_perception.stop()
            if state.identity_perception is not None:
                await state.identity_perception.stop()
            if state.voice_perception is not None:
                await state.voice_perception.stop()
            await state.everos_bridge.stop_retry_loop()
            await state.memory_capsule_bridge.stop_retry_loop()
            await state.correction_writeback.stop_retry_loop()
            await state.daily_review_scheduler.stop()
            await state.everos.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Beaver Memory Gateway", version="0.1.0", lifespan=lifespan)
    app.add_middleware(UserContextMiddleware)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(device_ws_router)
    app.include_router(media_router)
    app.include_router(openclaw_ws_router)
    app.include_router(preview_router)
    app.include_router(presence_evaluation_router)
    app.include_router(memory_router)
    app.include_router(project_router)
    app.include_router(web_router)
    app.mount(
        "/assets",
        StaticFiles(directory=frontend_root() / "assets"),
        name="beaver-assets",
    )
    return app


app = create_app()
