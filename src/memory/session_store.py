import sqlite3
import os
import json
import uuid
import time
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

class SessionStore:
    """SQLite-backed session and message persistence."""
    
    def __init__(self, db_path: str = "./data/memory/sessions.db"):
        """Initialize the SessionStore.
        
        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
    
    def _create_tables(self) -> None:
        """Create the necessary database tables if they do not exist."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at REAL,
                    updated_at REAL,
                    title TEXT,
                    metadata TEXT
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp REAL,
                    metadata TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)')
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error creating tables: {e}")
    
    def create_session(self, title: str = "New Session", metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a new chat session.
        
        Args:
            title: The title of the session.
            metadata: Optional metadata for the session.
            
        Returns:
            The generated session ID.
        """
        session_id = uuid.uuid4().hex
        now = time.time()
        meta_str = json.dumps(metadata or {})
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'INSERT INTO sessions (id, created_at, updated_at, title, metadata) VALUES (?, ?, ?, ?, ?)',
                (session_id, now, now, title, meta_str)
            )
            self.conn.commit()
            return session_id
        except sqlite3.Error as e:
            logger.error(f"Error creating session: {e}")
            return ""
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a session by its ID.
        
        Args:
            session_id: The ID of the session.
            
        Returns:
            A dictionary containing session details, or None if not found.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM sessions WHERE id = ?', (session_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "title": row["title"],
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
                }
            return None
        except sqlite3.Error as e:
            logger.error(f"Error getting session: {e}")
            return None
    
    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent sessions.
        
        Args:
            limit: Maximum number of sessions to return.
            
        Returns:
            A list of session dictionaries.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?', (limit,))
            rows = cursor.fetchall()
            return [{
                "id": row["id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "title": row["title"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
            } for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Error listing sessions: {e}")
            return []
    
    def add_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Add a message to a session.
        
        Args:
            session_id: The ID of the session.
            role: The role of the message sender (e.g., user, assistant).
            content: The text content of the message.
            metadata: Optional metadata for the message.
            
        Returns:
            The generated message ID.
        """
        message_id = uuid.uuid4().hex
        now = time.time()
        meta_str = json.dumps(metadata or {})
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                'INSERT INTO messages (id, session_id, role, content, timestamp, metadata) VALUES (?, ?, ?, ?, ?, ?)',
                (message_id, session_id, role, content, now, meta_str)
            )
            cursor.execute(
                'UPDATE sessions SET updated_at = ? WHERE id = ?',
                (now, session_id)
            )
            self.conn.commit()
            return message_id
        except sqlite3.Error as e:
            logger.error(f"Error adding message: {e}")
            return ""
    
    def get_messages(self, session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve messages for a session.
        
        Args:
            session_id: The ID of the session.
            limit: Maximum number of messages to return.
            
        Returns:
            A list of message dictionaries.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?', (session_id, limit))
            rows = cursor.fetchall()
            return [{
                "id": row["id"],
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["timestamp"],
                "metadata": json.loads(row["metadata"]) if row["metadata"] else {}
            } for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Error getting messages: {e}")
            return []
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages.
        
        Args:
            session_id: The ID of the session.
            
        Returns:
            True if deleted successfully, False otherwise.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
            cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
            self.conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error(f"Error deleting session: {e}")
            return False
    
    def get_stats(self) -> Dict[str, int]:
        """Get statistics about sessions and messages.
        
        Returns:
            A dictionary containing total sessions and messages.
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM sessions')
            total_sessions = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM messages')
            total_messages = cursor.fetchone()[0]
            return {
                "total_sessions": total_sessions,
                "total_messages": total_messages
            }
        except sqlite3.Error as e:
            logger.error(f"Error getting stats: {e}")
            return {"total_sessions": 0, "total_messages": 0}
    
    def close(self) -> None:
        """Close the database connection."""
        try:
            self.conn.close()
        except sqlite3.Error as e:
            logger.error(f"Error closing connection: {e}")
