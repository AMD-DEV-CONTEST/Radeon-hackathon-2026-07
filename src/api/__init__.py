"""FastAPI backend: routes, schemas, app factory.

Why a separate package: Gradio (UI) and FastAPI (API) are independent
deployment surfaces. Some users want just the API; some want the UI;
both share the same `src.core` + `src.models` underneath.
"""
