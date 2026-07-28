import logging
from typing import Optional

logger = logging.getLogger("auto_namer")

_model = None
_titulos_possiveis = [
    "Dúvida de Programação",
    "Análise de Código e Refatoração",
    "Bugs, Erros e Tracebacks",
    "Configuração de Ambiente e Deploy",
    "Criação de Novo Projeto",
    "Bate-papo e Conversa Geral",
    "Busca e Pesquisa na Web"
]
_embeddings_titulos = None

def _get_model():
    global _model, _embeddings_titulos
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
            _embeddings_titulos = _model.encode(_titulos_possiveis, convert_to_tensor=True)
            logger.info("Auto-Namer model carregado com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao carregar modelo de auto-namer: {e}")
            _model = "failed"
    return _model if _model != "failed" else None

def generate_chat_title(first_message: str) -> str:
    """Gera um título de chat baseado no primeiro prompt usando embeddings."""
    if not first_message or len(first_message.strip()) < 3:
        return "Novo Chat"
        
    model = _get_model()
    if not model:
        # Fallback genérico se falhar
        return " ".join(first_message.split()[:5]) + "..."
        
    try:
        from sentence_transformers import util
        embedding_usuario = model.encode(first_message, convert_to_tensor=True)
        scores = util.cos_sim(embedding_usuario, _embeddings_titulos)[0]
        indice_melhor_titulo = scores.argmax().item()
        return _titulos_possiveis[indice_melhor_titulo]
    except Exception as e:
        logger.error(f"Erro ao gerar título: {e}")
        return " ".join(first_message.split()[:5]) + "..."
