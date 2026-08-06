"Research Assistant"

import logging
from app.ui import build_ui
from config import OLLAMA_BASE_URL, OLLAMA_MODEL
from app.embeddings import DEVICE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("research_assistant")


if __name__ == "__main__":
    logger.info("🚀 Starting Research Assistant...")
    logger.info(f"💻 Torch device for embeddings: {DEVICE}")
    logger.info(f"🤖 Ollama endpoint: {OLLAMA_BASE_URL} | model: {OLLAMA_MODEL}")
    
    ui = build_ui()
    ui.queue()  # Required for streaming generators in Gradio
    ui.launch(server_name="0.0.0.0", server_port=7860, share=False)