"""Optional Gradio demo UI."""

from typing import List

from .config import Settings
from .runtime import build_agent


def available_incidents(settings: Settings) -> List[str]:
    return sorted(path.stem for path in settings.incident_dir.glob("*.json"))


def run_investigation(
    query: str, incident: str, approve_remediation: bool
) -> str:
    settings = Settings.from_env()
    agent = build_agent(settings, incident)
    try:
        response = agent.investigate(
            query=query or agent.environment.prompt,
            approve_remediation=approve_remediation,
        )
    finally:
        agent.close()

    lines = [
        f"## Status: `{response.status}`",
        "",
        response.summary,
        "",
        "### Plan",
    ]
    lines.extend(
        f"- **{step.status}** — {step.title}" for step in response.plan
    )
    lines.extend(["", "### Evidence"])
    lines.extend(
        f"- `{item.source}` ({item.score:.4f}) — {item.excerpt}"
        for item in response.evidence
    )
    lines.extend(["", "### Tool results"])
    lines.extend(
        f"- `{item.name}` — **{item.status}**"
        for item in response.tool_results
    )
    return "\n".join(lines)


def launch() -> None:
    try:
        import gradio as gr
    except ImportError as error:
        raise RuntimeError(
            "Install the demo dependency with: pip install -e '.[demo]'"
        ) from error

    settings = Settings.from_env()
    incidents = available_incidents(settings)
    if not incidents:
        raise RuntimeError(
            f"No incident fixtures found in {settings.incident_dir}"
        )

    with gr.Blocks(title="Radeon Sentinel") as demo:
        gr.Markdown(
            "# Radeon Sentinel\n"
            "Privacy-first local incident response. All remediation is "
            "simulated and requires explicit approval."
        )
        incident = gr.Dropdown(
            choices=incidents,
            value=incidents[0],
            label="Synthetic incident",
        )
        query = gr.Textbox(
            label="Investigation request",
            placeholder="Investigate the incident and cite local evidence.",
            lines=3,
        )
        approve = gr.Checkbox(
            value=False,
            label="Approve simulated remediation",
        )
        run_button = gr.Button("Investigate", variant="primary")
        output = gr.Markdown()
        run_button.click(
            fn=run_investigation,
            inputs=[query, incident, approve],
            outputs=output,
        )
    demo.launch(server_name="127.0.0.1")


if __name__ == "__main__":
    launch()
