"""
Gradio UI for the Research Assistant.
"""
import gradio as gr
from app.ingestion import ingest_documents
from app.generation import rag_answer_stream
from config import UPLOAD_DIR
import os
import glob
import logging

logger = logging.getLogger(__name__)


def clear_vector_db() -> str:
    """Delete the persisted Chroma collection and reset state."""
    from app.vectorstore import _vectorstore
    
    try:
        from app.vectorstore import get_vectorstore
        vs = get_vectorstore()
        vs.delete_collection()
    except Exception as e:
        logger.warning(f"delete_collection failed (may be already empty): {e}")
    
    # Reset in-memory handle
    import app.vectorstore
    app.vectorstore._vectorstore = None
    
    # Clear uploaded files
    for f in glob.glob(os.path.join(UPLOAD_DIR, "*")):
        try:
            os.remove(f)
        except Exception:
            pass
    
    logger.info("Vector database and uploaded files cleared.")
    return "Vector database cleared. Upload new documents to start again."


def build_ui() -> gr.Blocks:
    """Build and return the Gradio interface."""
    with gr.Blocks(title="Local Research Assistant (ROCm)") as demo:
        gr.Markdown(
            """
            # 📚 Local Research Assistant
            Fully local RAG pipeline: **PyPDF2 → LangChain chunking →
            sentence-transformers embeddings → ChromaDB → Ollama (Llama 3.2)**.
            
            🔒 No data leaves your machine. Runs on AMD GPU via ROCm.
            """
        )
        
        with gr.Row():
            with gr.Column(scale=1):
                file_upload = gr.File(
                    label="Upload PDF research paper(s)",
                    file_types=[".pdf"],
                    file_count="multiple",
                )
                load_btn = gr.Button("Load Documents", variant="primary")
                load_status = gr.Textbox(
                    label="Index status", interactive=False, lines=3
                )
                clear_db_btn = gr.Button("Clear Vector Database", variant="stop")
                
                gr.Markdown("---")
                sources_panel = gr.Markdown(
                    label="Retrieved sources",
                    value="_Ask a question to see retrieved chunks here._"
                )
            
            with gr.Column(scale=2):
                chatbot = gr.Chatbot(label="Chat", height=500)
                question_box = gr.Textbox(
                    label="Ask a question about your documents",
                    placeholder="e.g. What method did the authors use for evaluation?",
                    lines=2,
                )
                with gr.Row():
                    ask_btn = gr.Button("Send", variant="primary")
                    clear_chat_btn = gr.Button("Clear Chat")
        
        # Event wiring
        def on_load_documents(files):
            if not files:
                return "No files selected."
            file_paths = [f.name if hasattr(f, "name") else f for f in files]
            return ingest_documents(file_paths)
        
        load_btn.click(fn=on_load_documents, inputs=[file_upload], outputs=[load_status])
        clear_db_btn.click(fn=clear_vector_db, outputs=[load_status])
        
        def on_ask(question, history):
            if not question or not question.strip():
                yield history, "", "_Enter a question first._"
                return
            
            history = history + [[question, ""]]
            for partial_answer, sources_md in rag_answer_stream(
                question, [(h[0], h[1]) for h in history[:-1]]
            ):
                history[-1][1] = partial_answer
                yield history, "", sources_md
        
        ask_btn.click(
            fn=on_ask,
            inputs=[question_box, chatbot],
            outputs=[chatbot, question_box, sources_panel],
        )
        question_box.submit(
            fn=on_ask,
            inputs=[question_box, chatbot],
            outputs=[chatbot, question_box, sources_panel],
        )
        
        def on_clear_chat():
            return [], "_Ask a question to see retrieved chunks here._"
        
        clear_chat_btn.click(fn=on_clear_chat, outputs=[chatbot, sources_panel])
    
    return demo