# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs


project_root = Path.cwd()
src_root = project_root / "src"
scripts_root = project_root / "scripts"
xgboost_binaries = collect_dynamic_libs("xgboost")
xgboost_datas = collect_data_files("xgboost", includes=["VERSION", "py.typed"])
polars_binaries = collect_dynamic_libs("_polars_runtime_compat") + collect_dynamic_libs("_polars_runtime_32")
polars_datas = (
    collect_data_files("polars")
    + collect_data_files("_polars_runtime_compat")
    + collect_data_files("_polars_runtime_32")
    + collect_data_files("fastexcel")
)
skill_catalog = src_root / "xenix" / "services" / "agent" / "skills" / "catalog.json"
knowledge_binaries = []
knowledge_datas = []
knowledge_hiddenimports = []
for package_name in (
    "docling",
    "docling_core",
    "docling_ibm_models",
    "lancedb",
    "pypdfium2",
    "pikepdf",
    "pptx",
    "zstandard",
    "msoffcrypto",
):
    package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    knowledge_datas += package_datas
    knowledge_binaries += package_binaries
    knowledge_hiddenimports += package_hiddenimports


def collect_xenix_worker_source():
    source_root = src_root / "xenix"
    entries = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(source_root)
        if relative_path.parts[:3] == ("services", "agent", "skills"):
            continue
        if relative_path.parts[:2] in {("services", "amd"), ("resources", "amd")}:
            continue
        if relative_path in {
            Path("ui/amd_setup.py"),
            Path("ui/amd_capability_tasks.py"),
        }:
            continue
        if "__pycache__" in relative_path.parts or path.suffix == ".pyc":
            continue
        entries.append((str(path), str(Path("xenix_worker_source") / "xenix" / relative_path.parent)))
    return entries


def collect_generic_xenix_resources():
    resource_root = src_root / "xenix" / "resources"
    entries = []
    for path in sorted(resource_root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(resource_root)
        if relative_path.parts[:1] == ("amd",):
            continue
        entries.append((str(path), str(Path("xenix/resources") / relative_path.parent)))
    return entries


def collect_radeon_runtime():
    amd_resources = src_root / "xenix" / "resources" / "amd"
    amd_services = src_root / "xenix" / "services" / "amd"
    amd_ui = src_root / "xenix" / "ui" / "amd_setup.py"
    amd_tasks = src_root / "xenix" / "ui" / "amd_capability_tasks.py"
    required_paths = (amd_resources, amd_services, amd_ui, amd_tasks)
    if any(not path.exists() for path in required_paths):
        raise SystemExit("Radeon Edition build is incomplete.")
    return [
        (str(amd_resources), "xenix/resources/amd"),
    ], [
        "xenix.services.amd.composition",
        "xenix.ui.amd_setup",
    ]


amd_datas, amd_hiddenimports = collect_radeon_runtime()

a = Analysis(
    [str(scripts_root / "run_packaged.py")],
    pathex=[str(src_root)],
    binaries=xgboost_binaries + polars_binaries + knowledge_binaries,
    datas=[
        (str(src_root / "xenix" / "translations"), "xenix/translations"),
        (str(skill_catalog), "xenix/services/agent/skills"),
    ]
    + collect_generic_xenix_resources()
    + amd_datas
    + collect_xenix_worker_source()
    + xgboost_datas
    + polars_datas
    + knowledge_datas,
    hiddenimports=[
        "xenix._generated_release_config",
        "xenix.services.agent.chatbot_events",
        "xenix.services.agent.completion_guard",
        "xenix.services.agent.harness_service",
        "xenix.services.agent.lazy_tools",
        "xenix.services.agent.providers",
        "xenix.services.agent.settings",
        "xenix.services.agent.skill_catalog",
        "xenix.services.agent.tool_presentations",
        "xenix.services.agent.tools",
        "xenix.services.artifact_service",
        "xenix.services.agent.composition",
        "xenix.services.data_cleaning",
        "xenix.services.data_transform",
        "xenix.services.dataset_service",
        "xenix.services.dataset_export_service",
        "xenix.services.embedding_provider_factory",
        "xenix.services.lazy_ml_service",
        "xenix.services.lazy_services",
        "xenix.services.link_router",
        "xenix.services.llm",
        "xenix.services.ml.worker_settings",
        "xenix.services.ml_service",
        "xenix.services.ml_task_service",
        "xenix.services.embedding_service",
        "xenix.services.knowledge_canonical",
        "xenix.services.knowledge_content_store",
        "xenix.services.knowledge_derivation_service",
        "xenix.services.knowledge_import_service",
        "xenix.services.knowledge_import_worker",
        "xenix.services.knowledge_index_service",
        "xenix.services.knowledge_formats",
        "xenix.services.knowledge_projection",
        "xenix.services.knowledge_task_query",
        "xenix.services.knowledge_workspace_service",
        "xenix.services.knowledge_packaged_smoke",
        "xenix.services.knowledge_pipeline",
        "xenix.services.knowledge_semantic_service",
        "xenix.services.knowledge_service",
        "xenix.services.knowledge_task_logs",
        "xenix.services.knowledge_vector_store",
        "xenix.services.paddle_ocr_service",
        "xenix.services.ocr.settings",
        "xenix.services.settings_store",
        "xenix.services.storage",
        "xenix.services.storage.layout",
        "fastexcel",
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
        "opentelemetry.exporter.otlp.proto.grpc.metric_exporter",
        "opentelemetry.exporter.otlp.proto.grpc._log_exporter",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
        "polars",
        "_polars_runtime_compat",
        "_polars_runtime_compat._polars_runtime",
        "_polars_runtime_32",
        "_polars_runtime_32._polars_runtime",
    ] + knowledge_hiddenimports + amd_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xenix",
    version=str(project_root / "build" / "xenix-version-info.txt"),
    icon=str(project_root / "logo.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="xenix",
)
