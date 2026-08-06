import sqlite3
import os
import uuid
import logging
import re
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class KnowledgeGraph:
    """Optional entity and relationship extraction from conversations."""
    
    def __init__(self, db_path: str = "./data/memory/knowledge.db"):
        """Initialize the KnowledgeGraph.
        
        Args:
            db_path: Path to the SQLite knowledge database.
        """
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        
    def _create_tables(self) -> None:
        """Create database tables if they do not exist."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE,
                    type TEXT,
                    description TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS relationships (
                    id TEXT PRIMARY KEY,
                    entity1_id TEXT,
                    entity2_id TEXT,
                    relation_type TEXT,
                    FOREIGN KEY(entity1_id) REFERENCES entities(id),
                    FOREIGN KEY(entity2_id) REFERENCES entities(id)
                )
            ''')
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error creating knowledge graph tables: {e}")

    def extract_entities(self, text: str, model_manager: Any = None) -> List[Dict[str, str]]:
        """Extract entities from text.
        
        Args:
            text: The text to extract from.
            model_manager: Optional LLM manager to enhance extraction.
            
        Returns:
            A list of extracted entity dictionaries.
        """
        entities = []
        try:
            # Simple regex-based extraction (Capitalized words)
            words = re.findall(r'\b[A-Z][a-z]+\b', text)
            for word in set(words):
                if len(word) > 2:
                    entities.append({"name": word, "type": "Keyword"})
                    
            if model_manager and hasattr(model_manager, 'extract_entities'):
                llm_entities = model_manager.extract_entities(text)
                if isinstance(llm_entities, list):
                    entities.extend(llm_entities)
        except Exception as e:
            logger.error(f"Error extracting entities: {e}")
            
        return entities

    def add_entity(self, name: str, entity_type: str, description: str = "") -> str:
        """Add a new entity or return the existing one's ID.
        
        Args:
            name: The name of the entity.
            entity_type: The type of the entity.
            description: Description of the entity.
            
        Returns:
            The entity ID.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT id FROM entities WHERE name = ?', (name,))
            row = cursor.fetchone()
            if row:
                return row['id']
                
            entity_id = uuid.uuid4().hex
            cursor.execute(
                'INSERT INTO entities (id, name, type, description) VALUES (?, ?, ?, ?)',
                (entity_id, name, entity_type, description)
            )
            self.conn.commit()
            return entity_id
        except sqlite3.Error as e:
            logger.error(f"Error adding entity: {e}")
            return ""

    def add_relationship(self, entity1_id: str, entity2_id: str, relation_type: str) -> str:
        """Add a relationship between two entities.
        
        Args:
            entity1_id: First entity ID.
            entity2_id: Second entity ID.
            relation_type: The type of relationship.
            
        Returns:
            The relationship ID.
        """
        relationship_id = uuid.uuid4().hex
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'INSERT INTO relationships (id, entity1_id, entity2_id, relation_type) VALUES (?, ?, ?, ?)',
                (relationship_id, entity1_id, entity2_id, relation_type)
            )
            self.conn.commit()
            return relationship_id
        except sqlite3.Error as e:
            logger.error(f"Error adding relationship: {e}")
            return ""

    def query(self, entity_name: str) -> Dict[str, Any]:
        """Query an entity and its relationships.
        
        Args:
            entity_name: The name of the entity to query.
            
        Returns:
            A dictionary with entity details and its relationships.
        """
        result = {"entity": None, "relationships": []}
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM entities WHERE name = ?', (entity_name,))
            ent_row = cursor.fetchone()
            if ent_row:
                result["entity"] = dict(ent_row)
                
                cursor.execute('''
                    SELECT r.relation_type, e.name as related_entity 
                    FROM relationships r
                    JOIN entities e ON (r.entity2_id = e.id OR r.entity1_id = e.id)
                    WHERE (r.entity1_id = ? OR r.entity2_id = ?) AND e.id != ?
                ''', (ent_row['id'], ent_row['id'], ent_row['id']))
                
                result["relationships"] = [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error querying entity: {e}")
            
        return result

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about entities and relationships.
        
        Returns:
            Dictionary with total entities and relationships.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM entities')
            total_entities = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM relationships')
            total_relationships = cursor.fetchone()[0]
            return {
                "total_entities": total_entities,
                "total_relationships": total_relationships
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting graph stats: {e}")
            return {"total_entities": 0, "total_relationships": 0}
