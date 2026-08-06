"""Book management API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies.auth import get_current_user_role, require_admin
from services.audit_log import log_event
from services.database_registry import get_active_database_id, get_db_path
from services.db import get_db
import json
import logging

log = logging.getLogger(__name__)

router = APIRouter(tags=["books"])

def _get_books_db(database_id: str = None):
    """Get DB connection, resolving database_id if needed."""
    if database_id is None:
        database_id = get_active_database_id()
    return get_db(database_id)

@router.get("/api/books")
def api_list_books(database_id: str = None, role: str = Depends(get_current_user_role)):
    """List all books in a database (default: active database)."""
    db = _get_books_db(database_id)
    try:
        cursor = db.cursor()
        cursor.execute("SELECT * FROM books ORDER BY title")
        books = [dict(r) for r in cursor.fetchall()]
        return {"database_id": database_id or get_active_database_id(), "books": books}
    finally:
        db.close()

@router.post("/api/books")
def api_create_book(book_id: str = None, title: str = "", database_id: str = None, _: None = Depends(require_admin)):
    """Create a new book in the specified database."""
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    if not book_id:
        import re
        book_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", title.lower().replace(" ", "_"))
    db = _get_books_db(database_id)
    try:
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO books (book_id, title) VALUES (?, ?)",
            (book_id, title)
        )
        db.commit()
        log_event(get_db(), "book.create", f"Book {book_id} created")
        return {"status": "ok", "book_id": book_id, "title": title}
    except Exception as e:
        db.rollback()
        if "UNIQUE" in str(e):
            raise HTTPException(status_code=409, detail=f"Book '{book_id}' already exists")
        log.error("Book create failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Book create failed")
    finally:
        db.close()

@router.get("/api/books/active")
def api_get_active_book(role: str = Depends(get_current_user_role)):
    """Get the currently active book_id."""
    from services.database_registry import get_active_book_id
    return {"active_book_id": get_active_book_id()}

@router.get("/api/books/{book_id}")
def api_get_book(book_id: str, database_id: str = None, role: str = Depends(get_current_user_role)):
    """Get book details."""
    db = _get_books_db(database_id)
    try:
        cursor = db.cursor()
        cursor.execute("SELECT * FROM books WHERE book_id = ?", (book_id,))
        book = cursor.fetchone()
        if not book:
            raise HTTPException(status_code=404, detail=f"Book '{book_id}' not found")
        return {"book": dict(book)}
    finally:
        db.close()

@router.put("/api/books/{book_id}")
def api_update_book(book_id: str, title: str = None, description: str = None, author: str = None, database_id: str = None, _: None = Depends(require_admin)):
    """Update book metadata."""
    """Update book metadata."""
    db = _get_books_db(database_id)
    try:
        cursor = db.cursor()
        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if author is not None:
            updates.append("author = ?")
            params.append(author)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(book_id)
        cursor.execute(f"UPDATE books SET {', '.join(updates)} WHERE book_id = ?", params)
        db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Book '{book_id}' not found")
        log_event(db, "book.update", f"Book {book_id} updated")
        return {"status": "ok", "book_id": book_id}
    finally:
        db.close()

@router.delete("/api/books/{book_id}")
def api_delete_book(book_id: str, database_id: str = None, _: None = Depends(require_admin)):
    """Delete a book (not the default)."""
    if book_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete the default book")
    db = _get_books_db(database_id)
    try:
        cursor = db.cursor()
        cursor.execute("DELETE FROM books WHERE book_id = ?", (book_id,))
        db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Book '{book_id}' not found")
        log_event(get_db(), "book.delete", f"Book {book_id} deleted")
        return {"status": "ok", "deleted": book_id}
    finally:
        db.close()

@router.post("/api/books/activate")
def api_activate_book(book_id: str, role: str = Depends(get_current_user_role)):
    """Set the active book_id in the registry context."""
    from services.database_registry import set_active_book_id
    set_active_book_id(book_id)
    return {"status": "ok", "active_book_id": book_id}

