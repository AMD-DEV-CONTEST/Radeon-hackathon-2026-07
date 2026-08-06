"""
LLM generation via Ollama API with RAG prompt.
"""
import json
import logging
import requests
from typing import Generator, List, Tuple
from app.retrieval import retrieve_relevant_chunks, format_context, format_sources_markdown
from config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

RAG_PROMPT_TEMPLATE = """You are a helpful research assistant. Use ONLY the context below \
to answer the user's question. If the answer is not contained in the context, say you \
don't know rather than making something up. Be concise and cite which source/chunk you \
used when relevant.

Context:
{context}

Chat history:
{history}

Question: {question}

Answer:"""


def build_history_string(chat_history: List[Tuple[str, str]], max_turns: int = 5) -> str:
    """Serialize chat history into plain text for the prompt."""
    if not chat_history:
        return "(no previous conversation)"
    
    recent = chat_history[-max_turns:]
    lines = []
    for user_msg, assistant_msg in recent:
        lines.append(f"User: {user_msg}")
        if assistant_msg:
            lines.append(f"Assistant: {assistant_msg}")
    
    return "\n".join(lines)


def stream_ollama_response(prompt: str) -> Generator[str, None, None]:
    """Stream completion from Ollama API."""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": True,
    }
    
    try:
        with requests.post(url, json=payload, stream=True, timeout=120) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line.decode("utf-8"))
                except Exception:
                    continue
                
                token = chunk.get("response", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break
    
    except requests.exceptions.ConnectionError:
        logger.error("Could not connect to Ollama. Is `ollama serve` running?")
        yield "\n\n[ERROR] Could not connect to Ollama. Run `ollama serve` and `ollama pull llama3.2`."
    except Exception as e:
        logger.error(f"Ollama generation failed: {e}")
        yield f"\n\n[ERROR] Generation failed: {e}"


def rag_answer_stream(
    question: str, chat_history: List[Tuple[str, str]]
) -> Generator[Tuple[str, str], None, None]:
    """
    Full RAG pipeline: retrieve → build prompt → stream generation.
    Yields (partial_answer, sources_markdown) tuples.
    """
    retrieved = retrieve_relevant_chunks(question)
    context = format_context(retrieved)
    sources_md = format_sources_markdown(retrieved)
    history_str = build_history_string(chat_history)
    
    prompt = RAG_PROMPT_TEMPLATE.format(
        context=context if context else "(no indexed documents / no relevant context found)",
        history=history_str,
        question=question,
    )
    
    partial = ""
    for token in stream_ollama_response(prompt):
        partial += token
        yield partial, sources_md