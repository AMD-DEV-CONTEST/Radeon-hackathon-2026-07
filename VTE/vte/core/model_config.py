# vte/core/model_config.py

class ModelConfig:
    """
    Wrapper unificado para acessar configurações do modelo.
    Funciona com metadados GGUF (dicionário) ou objetos config do HuggingFace.
    """
    
    def __init__(self, model):
        self.model = model
        self._metadata = self._extract_metadata()
    
    def _extract_metadata(self) -> dict:
        """Extrai metadados do modelo (GGUF ou HuggingFace)"""
        # Tenta 1: Metadados GGUF (padrão VTE)
        if hasattr(self.model, 'metadata'):
            return self.model.metadata
        elif hasattr(self.model, '_metadata'):
            return self.model._metadata
        
        # Tenta 2: Config do HuggingFace
        elif hasattr(self.model, 'config'):
            return self._hf_config_to_dict(self.model.config)
        
        # Fallback: dicionário vazio
        return {}
    
    def _hf_config_to_dict(self, config) -> dict:
        """Converte config do HuggingFace para dicionário"""
        if hasattr(config, 'to_dict'):
            return config.to_dict()
        return vars(config)
    
    def get(self, key: str, default=None):
        """Acessa configuração com fallback"""
        # Mapeia chaves do HuggingFace para GGUF
        key_mapping = {
            'hidden_size': 'embedding_length',
            'num_attention_heads': 'attention.head_count',
            'num_key_value_heads': 'attention.head_count_kv',
            'num_hidden_layers': 'block_count',
            'intermediate_size': 'feed_forward_length',
            'vocab_size': 'tokenizer.ggml.tokens',  # Será processado specially
            'max_position_embeddings': 'context_length',
        }
        
        # Tenta chave original
        if key in self._metadata:
            value = self._metadata[key]
            # Processa vocab_size specially (pode ser lista de tokens)
            if key == 'tokenizer.ggml.tokens' and isinstance(value, list):
                return len(value)
            return value
        
        # Tenta chave mapeada
        mapped_key = key_mapping.get(key)
        if mapped_key and mapped_key in self._metadata:
            value = self._metadata[mapped_key]
            if mapped_key == 'tokenizer.ggml.tokens' and isinstance(value, list):
                return len(value)
            return value
        
        # Fallback para default
        return default
    
    # Propriedades convenientes
    @property
    def hidden_size(self) -> int:
        return int(self.get('hidden_size', 1536))
    
    @property
    def num_attention_heads(self) -> int:
        return int(self.get('num_attention_heads', 16))
    
    @property
    def num_key_value_heads(self) -> int:
        return int(self.get('num_key_value_heads', 2))
    
    @property
    def num_hidden_layers(self) -> int:
        return int(self.get('num_hidden_layers', 28))
    
    @property
    def intermediate_size(self) -> int:
        return int(self.get('intermediate_size', 8960))
    
    @property
    def vocab_size(self) -> int:
        return int(self.get('vocab_size', 151936))
    
    @property
    def max_position_embeddings(self) -> int:
        return int(self.get('max_position_embeddings', 32768))
    
    @property
    def head_dim(self) -> int:
        return self.hidden_size // self.num_attention_heads
