"""One Gradio page per capability: text2image, img2img, style_transfer.

Each page exports a `build()` function that returns a `gr.Blocks` (or
context manager) so the top-level `app.py` can compose them into a
multi-tab / sidebar layout.
"""
