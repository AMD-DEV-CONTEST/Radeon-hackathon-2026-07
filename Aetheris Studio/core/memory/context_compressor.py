import logging
import json
from typing import List, Dict

# Budget constants based on the spec
SYSTEM_PROMPT_BUDGET = 300
RAG_BUDGET = 600
AT_REFERENCE_BUDGET = 800
HISTORY_BUDGET = 1000
RESPONSE_BUDGET = 1024

logger = logging.getLogger("context_compressor")

def count_tokens(text: str) -> int:
    """Estimativa rápida: len(text.split()) * 1.3. Sem tokenizador pesado."""
    if not text:
        return 0
    return int(len(text.split()) * 1.3)

def should_compress(history: List[Dict]) -> bool:
    """True se o total de tokens do histórico ultrapassar 850 (85% de 1000)."""
    total = sum(msg.get("token_count", count_tokens(msg.get("content", ""))) for msg in history)
    return total > 850

def compress_history(chat_id: str, history: List[Dict]) -> List[Dict]:
    """
    Compacta quando próximo do limite de 1000 tokens.
    1. Mantém as últimas 4 mensagens intactas.
    2. Envia as mensagens anteriores ao LLM com o prompt adequado.
    3. Substitui as mensagens antigas por uma única role="system": "[RESUMO]: {resumo}"
    4. Salva o resumo via update_chat_summary.
    5. Retorna: [mensagem_resumo] + últimas_4_mensagens.
    """
    if len(history) <= 4:
        return history
        
    recent_messages = history[-4:]
    older_messages = history[:-4]
    
    try:
        from core.utils.vte_bridge import generate_once, VTE_DEFAULT_MODEL
        from core.utils.settings import get_setting
        from core.memory.chat_history import update_chat_summary

        text_to_summarize = "\n".join([f"{m['role']}: {m['content']}" for m in older_messages])
        prompt = (
            "Resuma a conversa abaixo em até 200 tokens, preservando: "
            "decisões importantes, fatos, código mencionado e referências futuras. Sem saudações.\n\n"
            f"Conversa:\n{text_to_summarize}"
        )

        model_name = get_setting("default_model") or VTE_DEFAULT_MODEL
        resumo = generate_once(model_name, [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=256)

        if not resumo:
            raise ValueError("Resposta vazia do modelo ao resumir.")
            
        update_chat_summary(chat_id, resumo)
        
        resumo_msg = {
            "role": "system",
            "content": f"[RESUMO]: {resumo}",
            "token_count": count_tokens(f"[RESUMO]: {resumo}"),
            "compressed": True
        }
        
        return [resumo_msg] + recent_messages
        
    except Exception as e:
        logger.error(f"Falha ao compactar histórico via LLM: {e}. Aplicando hard trim.")
        from core.memory.chat_history import HISTORY_TOKEN_LIMIT
        
        safe_history = []
        total_tokens = 0
        
        for msg in reversed(history):
            t_count = msg.get("token_count", count_tokens(msg.get("content", "")))
            if total_tokens + t_count <= HISTORY_TOKEN_LIMIT:
                safe_history.insert(0, msg)
                total_tokens += t_count
            else:
                break
                
        return safe_history

def build_context_window(chat_id: str, new_message: str = "") -> List[Dict]:
    """
    Chamada antes de cada inferência para obter a janela de contexto persistida.
    """
    from core.memory.chat_history import load_chat_history
    
    history = load_chat_history(chat_id)
    if not history:
        return []
        
    if should_compress(history):
        history = compress_history(chat_id, history)
        
    return history
