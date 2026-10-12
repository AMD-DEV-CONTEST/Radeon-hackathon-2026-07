import os
import json
import logging
from warden.config import WardenConfig
from warden.rag.retriever import WardenRetriever

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def populate_rag():
    data_path = os.path.join("data", "owasp_llm_top10.json")
    if not os.path.exists(data_path):
        logger.error(f"Data file not found: {data_path}")
        return

    with open(data_path, "r") as f:
        owasp_data = json.load(f)

    config = WardenConfig.from_env()
    retriever = WardenRetriever(db_path=config.rag_db_path)
    
    if not retriever.initialize() or not retriever.is_available():
        logger.warning("RAG retriever is not available (ChromaDB missing). Cannot populate.")
        return

    pattern_dicts = []
    
    for item in owasp_data:
        for pat in item.get("patterns", []):
            pattern_dicts.append({
                "text": pat,
                "type": "injection",
                "severity": "high",
                "source": "owasp_top10",
                "category": item["id"],
                "description": item["description"]
            })
            
    if pattern_dicts:
        retriever.add_patterns(pattern_dicts)
        logger.info(f"Successfully populated RAG with {len(pattern_dicts)} OWASP patterns.")
    else:
        logger.info("No patterns found to populate.")

if __name__ == "__main__":
    populate_rag()
