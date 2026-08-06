from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from colorgraph import __version__
from colorgraph.api.dependencies import compute_backend
from colorgraph.api.routes.creative_agent import router as creative_agent_router
from colorgraph.api.routes.jobs import router as jobs_router
from colorgraph.api.routes.operations import router as operations_router
from colorgraph.api.routes.projects import router as projects_router
from colorgraph.config import settings
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    GradeNode,
    MediaInfo,
    NodeType,
    Scene,
    ScopeLevel,
    Shot,
    SpatialScope,
    TemporalScope,
    TimeRange,
)
from colorgraph.grading.looks import look_recipe_catalog
from colorgraph.grading.ocio_pipeline import (
    OCIO_CONFIG_NAME,
    ocio_pipeline_metadata,
    resolve_display_target,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    compute_backend()
    yield


app = FastAPI(
    title="ColorGraph Local API",
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4173", "http://localhost:4173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs_router)
app.include_router(projects_router)
app.include_router(operations_router)
app.include_router(creative_agent_router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/system/device")
def system_device() -> dict:
    return compute_backend().info.model_dump(mode="json")


@app.get("/api/system/look-recipes")
def system_look_recipes() -> dict:
    return look_recipe_catalog()


@app.get("/api/grade-graphs/example", response_model=GradeGraph)
def example_grade_graph() -> GradeGraph:
    project_id = "project_demo"
    scene_id = "scene_01"
    shot_id = "shot_01"
    full_range = TimeRange(start_seconds=0, end_seconds=10)
    scope = TemporalScope(
        level=ScopeLevel.SHOT,
        project_id=project_id,
        scene_id=scene_id,
        shot_id=shot_id,
        time_range=full_range,
    )
    project_scope = TemporalScope(
        level=ScopeLevel.PROJECT,
        project_id=project_id,
    )
    output_target = resolve_display_target(ColorSpace.REC1886)
    return GradeGraph(
        id="graph_demo",
        project_id=project_id,
        project_name="ColorGraph Example",
        working_color_space=ColorSpace.ACESCG,
        output_color_space=ColorSpace.REC1886,
        media=MediaInfo(
            path="example.mp4",
            duration_seconds=10,
            width=1920,
            height=1080,
            fps=25,
            frame_count=250,
            codec="h264",
            pixel_format="yuv420p",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        scenes=[Scene(id=scene_id, index=0, label="Scene 01", shot_ids=[shot_id])],
        shots=[
            Shot(
                id=shot_id,
                scene_id=scene_id,
                index=0,
                time_range=full_range,
            )
        ],
        nodes=[
            GradeNode(
                id="input_transform",
                type=NodeType.INPUT_TRANSFORM,
                label="Input color transform",
                order=0,
                temporal_scope=project_scope,
                parameters={
                    "input_space": ColorSpace.BT709_OETF.value,
                    "working_space": ColorSpace.ACESCG.value,
                    "interchange_space": ColorSpace.ACES2065_1.value,
                    "ocio_config": OCIO_CONFIG_NAME,
                },
                metadata={"transform_version": "colorgraph.input-transform/v3"},
            ),
            GradeNode(
                id="balance_01",
                type=NodeType.BALANCE,
                label="Base Balance",
                order=10,
                temporal_scope=scope,
                spatial_scope=SpatialScope(),
                parameters={"exposure": 0.15, "temperature": -4.0},
            ),
            GradeNode(
                id="output_transform",
                type=NodeType.OUTPUT_TRANSFORM,
                label="Output color transform",
                order=20,
                temporal_scope=project_scope,
                parameters={
                    "working_space": ColorSpace.ACESCG.value,
                    "output_space": ColorSpace.REC1886.value,
                    "interchange_space": ColorSpace.ACES2065_1.value,
                    "ocio_config": OCIO_CONFIG_NAME,
                    "display": output_target.display,
                    "view": output_target.view,
                },
                metadata={"transform_version": "colorgraph.output-transform/v3"},
            ),
        ],
        metadata={
            "example": True,
            "color_pipeline": ocio_pipeline_metadata(
                ColorSpace.BT709_OETF,
                source_log_profile=None,
                output_space=ColorSpace.REC1886,
            ),
        },
    )
