"""
Notes tools — Simple note/todo management stored in FRIDAY_HOME.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from friday.config import config

NOTES_DIR = config.FRIDAY_HOME / "notes"
NOTES_DIR.mkdir(parents=True, exist_ok=True)


def _notes_file() -> Path:
    return NOTES_DIR / "notes.json"


def _load_notes() -> list[dict]:
    notes_file = _notes_file()
    if not notes_file.exists():
        return []
    try:
        content = notes_file.read_text(encoding="utf-8")
        if not content.strip():
            return []
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return []


def _save_notes(notes: list[dict]) -> None:
    notes_file = _notes_file()
    notes_file.write_text(json.dumps(notes, indent=2), encoding="utf-8")


def register(mcp):

    @mcp.tool()
    def create_note(title: str, content: str = "", tags: list[str] | None = None) -> dict:
        """
        Create a new note.
        Args:
            title: Note title (required)
            content: Note content (optional)
            tags: List of tags for categorization (optional)
        Returns the created note with its ID.
        """
        notes = _load_notes()
        now = datetime.now(UTC).isoformat()
        note = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "content": content,
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
            "completed": False,
        }
        notes.append(note)
        _save_notes(notes)
        return {"success": True, "note": note}

    @mcp.tool()
    def list_notes(tag: str | None = None, include_completed: bool = True) -> dict:
        """
        List all notes, optionally filtered by tag.
        Args:
            tag: Filter notes by this tag (optional)
            include_completed: Whether to include completed notes (default: True)
        Returns list of notes sorted by updated_at (newest first).
        """
        notes = _load_notes()

        if tag:
            notes = [n for n in notes if tag in n.get("tags", [])]

        if not include_completed:
            notes = [n for n in notes if not n.get("completed", False)]

        notes.sort(key=lambda n: n.get("updated_at", ""), reverse=True)
        return {"success": True, "notes": notes, "count": len(notes)}

    @mcp.tool()
    def get_note(note_id: str) -> dict:
        """
        Get a single note by its ID.
        Args:
            note_id: The note ID (short UUID)
        Returns the note or error if not found.
        """
        notes = _load_notes()
        for note in notes:
            if note["id"] == note_id:
                return {"success": True, "note": note}
        return {"success": False, "error": f"Note not found: {note_id}"}

    @mcp.tool()
    def update_note(
        note_id: str,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        completed: bool | None = None,
    ) -> dict:
        """
        Update an existing note.
        Args:
            note_id: The note ID to update
            title: New title (optional)
            content: New content (optional)
            tags: New tags list (optional)
            completed: Mark as completed/incomplete (optional)
        Returns the updated note.
        """
        notes = _load_notes()
        for _i, note in enumerate(notes):
            if note["id"] == note_id:
                if title is not None:
                    note["title"] = title
                if content is not None:
                    note["content"] = content
                if tags is not None:
                    note["tags"] = tags
                if completed is not None:
                    note["completed"] = completed
                note["updated_at"] = datetime.now(UTC).isoformat()
                _save_notes(notes)
                return {"success": True, "note": note}
        return {"success": False, "error": f"Note not found: {note_id}"}

    @mcp.tool()
    def delete_note(note_id: str) -> dict:
        """
        Delete a note by its ID.
        Args:
            note_id: The note ID to delete
        Returns success status.
        """
        notes = _load_notes()
        for i, note in enumerate(notes):
            if note["id"] == note_id:
                deleted = notes.pop(i)
                _save_notes(notes)
                return {"success": True, "deleted": deleted}
        return {"success": False, "error": f"Note not found: {note_id}"}

    @mcp.tool()
    def search_notes(query: str) -> dict:
        """
        Search notes by title or content (case-insensitive).
        Args:
            query: Search query string
        Returns matching notes.
        """
        notes = _load_notes()
        query_lower = query.lower()
        matches = [
            n
            for n in notes
            if query_lower in n.get("title", "").lower()
            or query_lower in n.get("content", "").lower()
        ]
        matches.sort(key=lambda n: n.get("updated_at", ""), reverse=True)
        return {"success": True, "notes": matches, "count": len(matches)}
