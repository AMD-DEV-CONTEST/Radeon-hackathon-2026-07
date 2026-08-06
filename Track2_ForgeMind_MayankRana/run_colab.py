
# ForgeMind - Colab Notebook Entry
# Run this in Google Colab

# !pip install -q -r requirements-colab.txt
# !pip install -q gradio langgraph chromadb sentence-transformers

from app.ui.gradio_app import create_ui
ui = create_ui()
ui.launch(share=True)  # share=True gives public URL in Colab
