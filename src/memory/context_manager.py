import logging
from typing import List, Dict, Any, Optional
from .session_store import SessionStore

logger = logging.getLogger(__name__)

class ContextManager:
    """Builds context window from session history respecting token limits."""
    
    def __init__(self, session_store: Optional[Any] = None, max_tokens: int = 4096, chars_per_token: float = 4.0):
        """Initialize the ContextManager.
        
        Args:
            session_store: Optional SessionStore or MemoryConfig instance.
            max_tokens: Maximum allowed tokens for the context window.
            chars_per_token: Heuristic ratio of characters per token.
        """
        if hasattr(session_store, "max_context_tokens"):
            self.session_store = None
            self.max_tokens = getattr(session_store, "max_context_tokens", max_tokens)
            self.chars_per_token = getattr(session_store, "chars_per_token", chars_per_token)
        else:
            self.session_store = session_store
            self.max_tokens = max_tokens
            self.chars_per_token = chars_per_token
    
    def build_context(self, session_id_or_messages: Any, max_messages: int = 50) -> List[Dict[str, str]]:
        """Build a context window containing recent messages within the token limit.
        
        Args:
            session_id_or_messages: Session ID string or direct list of message dicts.
            max_messages: Maximum number of recent messages to fetch initially.
            
        Returns:
            A list of message dictionaries (role and content).
        """
        try:
            if isinstance(session_id_or_messages, list):
                messages_data = session_id_or_messages
            elif isinstance(session_id_or_messages, str) and self.session_store is not None:
                messages_data = self.session_store.get_messages(session_id_or_messages, limit=max_messages)
            else:
                messages_data = []

            if not messages_data:
                return []
            
            messages = [{"role": m["role"], "content": m["content"]} for m in messages_data if "role" in m and "content" in m]
            
            while self.count_context_tokens(messages) > self.max_tokens and messages:
                if len(messages) > 1:
                    messages.pop(0)
                else:
                    msg = dict(messages[0])
                    content = msg["content"]
                    while self.count_tokens(content) > self.max_tokens and len(content) > 0:
                        content = content[:-1]
                    msg["content"] = content
                    messages = [msg] if content else []
                    break
                
            return messages
        except Exception as e:
            logger.error(f"Error building context: {e}")
            return []
    
    def count_tokens(self, text: str) -> int:
        """Count approximate tokens in a string.

        Uses tiktoken (cl100k_base) when available; falls back to
        ``len(text) // chars_per_token`` otherwise.

        Args:
            text: The text to count.

        Returns:
            Approximate token count (minimum 1 for non-empty text).
        """
        if not text:
            return 0
        try:
            import tiktoken  # optional dependency; do not hard-require
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            return max(1, int(len(text) / self.chars_per_token))
    
    def count_context_tokens(self, messages: List[Dict[str, str]]) -> int:
        """Count approximate tokens for a list of messages.
        
        Args:
            messages: List of message dictionaries.
            
        Returns:
            Total approximate token count.
        """
        return sum(self.count_tokens(m.get("content", "")) for m in messages)
    
    def summarize_if_needed(self, messages: List[Dict[str, Any]], model_manager: Any) -> List[Dict[str, Any]]:
        """Summarize older messages if the context exceeds the token limit.
        
        Args:
            messages: List of message dictionaries.
            model_manager: The model manager instance capable of summarization.
            
        Returns:
            A list of messages with older ones replaced by a summary if needed.
        """
        try:
            if self.count_context_tokens(messages) <= self.max_tokens:
                return messages
                
            if len(messages) <= 2:
                return messages
                
            # Take the oldest half for summarization
            split_idx = len(messages) // 2
            to_summarize = messages[:split_idx]
            to_keep = messages[split_idx:]
            
            summary_text = model_manager.summarize([m.get("content", "") for m in to_summarize])
            summary_msg = {"role": "system", "content": f"Previous context summary: {summary_text}"}
            
            return [summary_msg] + to_keep
        except Exception as e:
            logger.error(f"Error during summarization: {e}")
            return messages
