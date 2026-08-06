import asyncio
import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.agent.graph import build_graph
from LLM.llm import LLM
from backend.agent.nodes.manim_coder import process_all_scenes
from backend.agent.state import create_initial_state

DB_PATH = Path("./data/edumanim.db")
JOB_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
generation_lock = asyncio.Lock()
active_generation_job_id: Optional[str] = None


def get_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            conversation_id TEXT,
            user_query TEXT,
            status TEXT NOT NULL,
            plan_json TEXT,
            script_json TEXT,
            final_video_path TEXT,
            error TEXT,
            created_at TIMESTAMP,
            completed_at TIMESTAMP
        )
        """
    )
    existing_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    for column_name, column_type in (
        ("script_json", "TEXT"),
        ("progress_stage", "TEXT"),
        ("progress_message", "TEXT"),
    ):
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column_name} {column_type}")
    conn.commit()
    conn.close()


class JobPubSub:
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, job_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(job_id, []).append(queue)
        return queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue):
        subs = self._subscribers.get(job_id, [])
        if queue in subs:
            subs.remove(queue)

    async def publish(self, job_id: str, event: dict):
        for queue in self._subscribers.get(job_id, []):
            await queue.put(event)


pubsub = JobPubSub()
running_tasks: dict[str, asyncio.Task] = {}
app_loop: Optional[asyncio.AbstractEventLoop] = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_job(job_id: str, **fields):
    conn = get_db()
    columns = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)
    conn.commit()
    conn.close()


def get_job(job_id: str) -> Optional[sqlite3.Row]:
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    return row


async def publish_job_event(job_id: str, event: dict):
    await pubsub.publish(job_id, event)


def publish_job_event_sync(job_id: str, event: dict):
    if app_loop is None:
        asyncio.run(publish_job_event(job_id, event))
        return

    future = asyncio.run_coroutine_threadsafe(publish_job_event(job_id, event), app_loop)
    future.result()


async def release_generation_slot(job_id: str):
    async with generation_lock:
        global active_generation_job_id
        if active_generation_job_id == job_id:
            active_generation_job_id = None


def run_agent_pipeline_sync(job_id: str, user_query: str, voice: str, video_quality: str, conversation_id: Optional[str]):
    try:
        update_job(job_id, status="running", error=None)
        publish_job_event_sync(job_id, {"type": "status", "status": "running"})

        llm = LLM()
        graph = build_graph(llm, voice=voice, video_quality=video_quality)
        state = create_initial_state(
            user_query=user_query,
            conversation_id=conversation_id,
        )

        publish_job_event_sync(
            job_id,
            {
                "type": "progress",
                "stage": "scripting",
                "message": "Writing narration script...",
            },
        )

        update_job(
            job_id,
            progress_stage="scripting",
            progress_message="Writing narration script...",
        )

        state = graph.scriptwriter_node(state)

        script_data = state.get("script")
        if script_data is not None:
            update_job(
                job_id,
                script_json=json.dumps(script_data, ensure_ascii=False),
            )

        update_job(
            job_id,
            script_json=json.dumps(script_data, ensure_ascii=False),
            progress_stage="narration",
            progress_message="Synthesizing narration audio...",
        )
        publish_job_event_sync(
            job_id,
            {
                "type": "progress",
                "stage": "narration",
                "message": "Synthesizing narration audio...",
            },
        )

        print("Starting TTS synthesis...")
        state = asyncio.run(graph.tts(state))
        print("TTS synthesis completed.")

        total_scenes = max(len(state.get("scenes", [])), 1)

        def progress_callback(event_type: str, payload: dict):
            if event_type == "manim_scene_done":
                scene_id = payload.get("scene_id", 0)
                progress = payload.get("progress", 0)
                message = f"Rendering scene {scene_id}/{total_scenes}..."
                update_job(
                    job_id,
                    progress_stage=f"rendering_{scene_id}",
                    progress_message=message,
                )
                publish_job_event_sync(
                    job_id,
                    {
                        "type": "progress",
                        "stage": f"rendering_{scene_id}",
                        "scene_id": scene_id,
                        "message": message,
                        "progress": progress,
                    },
                )

        state = asyncio.run(process_all_scenes(
            state,
            llm=graph.llm,
            output_dir="output",
            max_retries=4,
            progress_callback=progress_callback,
        ))

        publish_job_event_sync(
            job_id,
            {
                "type": "progress",
                "stage": "assembling",
                "message": "Assembling final video...",
            },
        )
        update_job(
            job_id,
            progress_stage="assembling",
            progress_message="Assembling final video...",
        )
        state = graph.assembler(state)

        final_video_path = state.get("final_video_path")
        if final_video_path:
            final_video_path = str(Path(final_video_path).expanduser().resolve())
            update_job(
                job_id,
                status="completed",
                final_video_path=final_video_path,
                error=None,
                progress_stage="completed",
                progress_message="Video generation completed",
                completed_at=now(),
            )
            publish_job_event_sync(
                job_id,
                {
                    "type": "status",
                    "status": "completed",
                    "final_video_path": final_video_path,
                },
            )
        else:
            error_message = "; ".join(state.get("errors", [])) or "Agent pipeline completed without a final video"
            update_job(
                job_id,
                status="failed",
                error=error_message,
                progress_stage="failed",
                progress_message=error_message,
                completed_at=now(),
            )
            publish_job_event_sync(
                job_id,
                {"type": "status", "status": "failed", "error": error_message},
            )
    except asyncio.CancelledError:
        update_job(
            job_id,
            status="cancelled",
            progress_stage="cancelled",
            progress_message="Job cancelled",
            completed_at=now(),
        )
        publish_job_event_sync(job_id, {"type": "status", "status": "cancelled"})
        raise
    except Exception as exc:
        update_job(
            job_id,
            status="failed",
            error=str(exc),
            progress_stage="failed",
            progress_message=str(exc),
            completed_at=now(),
        )
        publish_job_event_sync(job_id, {"type": "status", "status": "failed", "error": str(exc)})
    finally:
        if app_loop is None:
            asyncio.run(release_generation_slot(job_id))
        else:
            asyncio.run_coroutine_threadsafe(release_generation_slot(job_id), app_loop).result()
        running_tasks.pop(job_id, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_loop
    app_loop = asyncio.get_running_loop()
    init_db()
    yield


app = FastAPI(title="EduManim API", lifespan=lifespan)


class CreateJobRequest(BaseModel):
    user_query: str
    voice: str
    video_quality: str
    conversation_id: Optional[str] = None


class JobResponse(BaseModel):
    id: str
    conversation_id: Optional[str]
    user_query: str
    status: str
    script_json: Optional[str]
    progress_stage: Optional[str]
    progress_message: Optional[str]
    final_video_path: Optional[str]
    error: Optional[str]
    created_at: str
    completed_at: Optional[str]


def row_to_response(row: sqlite3.Row) -> JobResponse:
    return JobResponse(
        id=row["id"],
        conversation_id=row["conversation_id"],
        user_query=row["user_query"],
        status=row["status"],
        script_json=row["script_json"],
        progress_stage=row["progress_stage"],
        progress_message=row["progress_message"],
        final_video_path=row["final_video_path"],
        error=row["error"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


@app.post("/api/jobs", response_model=JobResponse)
async def create_job(payload: CreateJobRequest):
    global active_generation_job_id

    async with generation_lock:
        if active_generation_job_id is not None:
            raise HTTPException(
                status_code=409,
                detail="Another video generation is already running",
            )

        job_id = str(uuid.uuid4())
        conn = get_db()
        conn.execute(
            """
            INSERT INTO jobs (id, conversation_id, user_query, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, payload.conversation_id, payload.user_query, "queued", now()),
        )
        conn.commit()
        conn.close()

        row = get_job(job_id)
        if row is None:
            raise HTTPException(status_code=500, detail="Job could not be created")

        active_generation_job_id = job_id

    task = asyncio.create_task(
        asyncio.to_thread(
            run_agent_pipeline_sync,
            job_id,
            payload.user_query,
            payload.voice,
            payload.video_quality,
            payload.conversation_id,
        )
    )
    running_tasks[job_id] = task

    return row_to_response(row)


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str):
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return row_to_response(row)


@app.delete("/api/jobs/{job_id}", response_model=JobResponse)
async def cancel_job(job_id: str):
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Job already {row['status']}")

    task = running_tasks.get(job_id)
    if task:
        task.cancel()
    else:
        update_job(job_id, status="cancelled", completed_at=now())

    updated_row = get_job(job_id)
    if updated_row is None:
        raise HTTPException(status_code=500, detail="Job disappeared during cancellation")
    return row_to_response(updated_row)


@app.websocket("/api/ws/jobs/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str):
    row = get_job(job_id)
    if row is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    queue = pubsub.subscribe(job_id)
    try:
        await websocket.send_text(
            json.dumps({"type": "status", "status": row["status"]})
        )
        while True:
            event = await queue.get()
            await websocket.send_text(json.dumps(event))
            if event.get("type") == "status" and event.get("status") in (
                "completed",
                "failed",
                "cancelled",
            ):
                break
    except WebSocketDisconnect:
        pass
    finally:
        pubsub.unsubscribe(job_id, queue)


@app.get("/api/videos/{job_id}")
async def stream_video(job_id: str):
    row = get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] != "completed" or not row["final_video_path"]:
        raise HTTPException(status_code=409, detail="Video not ready yet")

    video_path = Path(row["final_video_path"])
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file missing on disk")

    return FileResponse(video_path, media_type="video/mp4", filename=video_path.name)


@app.get("/api/videos")
async def list_videos():
    conn = get_db()
    rows = conn.execute(
        "SELECT id, final_video_path, completed_at FROM jobs WHERE status = 'completed'"
    ).fetchall()
    conn.close()
    return [
        {"job_id": r["id"], "video_path": r["final_video_path"], "completed_at": r["completed_at"]}
        for r in rows
    ]


@app.get("/health")
async def health():
    return {"status": "ok"}
