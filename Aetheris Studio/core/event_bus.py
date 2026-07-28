import asyncio
from typing import Callable, Dict, List, Any

class EventBus:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.subscribers = {}  # type: Dict[str, List[Callable]]
        return cls._instance
        
    def subscribe(self, topic: str, callback: Callable[[Any], None]):
        """Subscribe a callback to a topic."""
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        if callback not in self.subscribers[topic]:
            self.subscribers[topic].append(callback)
            
    def publish(self, topic: str, payload: Any = None):
        """Publish a message to a topic."""
        if topic in self.subscribers:
            for callback in self.subscribers[topic]:
                try:
                    # Se for corrotina, criamos task, senão chamamos síncrono
                    if asyncio.iscoroutinefunction(callback):
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(callback(payload))
                        except RuntimeError:
                            # Se não houver loop ativo nesta thread, ignora ou roda de outro jeito
                            asyncio.run(callback(payload))
                    else:
                        callback(payload)
                except Exception as e:
                    import logging
                    logging.getLogger("event_bus").error(f"Erro no listener {callback} do topico {topic}: {e}")

# Singleton instance for easy import
bus = EventBus()
