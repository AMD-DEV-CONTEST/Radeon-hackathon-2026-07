# UI Module Agent Instructions

## Module Purpose
The `ui` module provides the interactive user interface for the Bunker project using Gradio. It serves as the primary touchpoint for users and the "wow factor" for hackathon judges, prominently displaying the privacy dashboard alongside the chat interface.

## Layout Constants
- **Chat vs Dashboard Ratio**: 2:1 (`scale=2` for left column, `scale=1` for right column).
- **Auto-Refresh**: `REFRESH_INTERVAL = 2` seconds (driven by `gr.Timer`).

## Key Methods in `BunkerGradioApp`
- `build_ui()`: Constructs the Gradio Blocks layout.
- `handle_message()`: Wires user input to the agent and updates chat history/thoughts.
- `refresh_dashboard()`: Fetches latest privacy metrics and updates dashboard components.

## Gradio Wiring
- `msg_input.submit` and `send_btn.click` both trigger `handle_message`.
- `gr.Timer.tick` and `refresh_btn.click` trigger `refresh_dashboard`.

## Adding a New Dashboard Panel
To add a new metric to the privacy dashboard:
1. Update `src/privacy/dashboard.py` (`get_dashboard_data`) to return the new metric.
2. Update `src/ui/components/privacy_dashboard.py` to add the Gradio UI element and return it in the tuple.
3. Update `src/ui/gradio_app.py` (`refresh_dashboard` output unpacking and `timer.tick` / `refresh_btn.click` outputs list) to handle the new return value.

## Theme and Styling
- Uses `gr.themes.Soft()` for a modern, sleek appearance with custom Google fonts (Inter).
- Emojis (🔒, 💬, 🤔, 📊, ⚙️) are used strategically to organize sections visually.
- *(Future enhancement)*: Dynamic coloring for the local percentage number (Green > 95%, Yellow > 80%, Red < 80%) via Gradio HTML/Markdown updates if native components don't support color injection.

## Wires Into
- `BunkerGradioApp.get_gradio_app()` is called by the application entrypoint (e.g., `main.py`) to mount or launch the server.
