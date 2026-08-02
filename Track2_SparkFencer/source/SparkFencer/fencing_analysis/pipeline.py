"""Stage orchestration shared by the CLI and the WebUI."""

import json
import os

from .config import _deep_merge, load_config

ALL_STAGES = ("perception", "analysis", "evidence", "agents", "report")


def run_pipeline(video_path, corners=None, output_dir=None, config_path=None,
                 config_overrides=None, stages=ALL_STAGES, skip_agents=False,
                 progress_callback=None):
    config = load_config(config_path)
    if config_overrides:
        config = _deep_merge(config, config_overrides)
    results = {}

    if "perception" in stages:
        from .system import FencingAnalysisSystem
        system = FencingAnalysisSystem(
            video_path, corners=corners, output_dir=output_dir, config=config
        )
        results["perception"] = system.process_video(progress_callback=progress_callback)
        output_dir = system.save_dir
    elif output_dir is None:
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        output_dir = os.path.join("outputs", video_name)

    events = None
    timeline = None
    if "analysis" in stages:
        from .analysis.events import run_analysis
        from .visualization.charts import generate_charts
        events_path, events, timeline = run_analysis(output_dir, config)
        results["events"] = events_path
        results["charts"] = generate_charts(output_dir, events, timeline)

    if events is None:
        events_path = os.path.join(output_dir, "events.json")
        if os.path.exists(events_path):
            with open(events_path, "r", encoding="utf-8") as f:
                events = json.load(f)

    manifest = None
    if "evidence" in stages and events is not None:
        from .evidence.clips import extract_evidence
        manifest_path, manifest = extract_evidence(
            output_dir, events, config, source_video=video_path,
            include_keyframes=not skip_agents,
        )
        results["evidence"] = manifest_path

    if manifest is None:
        manifest_path = os.path.join(output_dir, "evidence_manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)["events"]

    validated = None
    if "agents" in stages and not skip_agents and events is not None and manifest:
        from .agents.validator import cross_validate
        validated_path, validated = cross_validate(output_dir, events, manifest, config)
        results["validated"] = validated_path

    if "report" in stages and events is not None:
        from .agents.coach import generate_report
        report_path = generate_report(
            output_dir, events, validated, config,
            use_agent=not skip_agents,
        )
        results["report"] = report_path

    return results
