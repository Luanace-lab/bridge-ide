"""WhatsApp Media Service — downloads media from Go Bridge and stores locally.

Used by whatsapp_watcher.py to handle incoming media messages.
Go Bridge API: POST /api/download {message_id, chat_jid} → {success, filename, path}
Local storage: Backend/uploads/wa_{uuid8}_{filename} (served via /files/)
"""

import os
import shutil
import sqlite3
import uuid

import httpx

# Max file size for download (50 MB)
_MAX_FILE_SIZE = 50 * 1024 * 1024

# Uploads dir (same as CHAT_UPLOADS_DIR in server.py)
_UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def download_whatsapp_media(
    message_id: str,
    chat_jid: str,
    bridge_url: str = "http://localhost:8080",
    api_token: str = "",
) -> dict:
    """Call Go Bridge /api/download to decrypt and save media.

    Returns: {success: bool, filename: str, source_path: str, error: str}
    """
    try:
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        resp = httpx.post(
            f"{bridge_url}/api/download",
            json={"message_id": message_id, "chat_jid": chat_jid},
            headers=headers,
            timeout=15.0,
        )
        if resp.status_code != 200:
            return {"success": False, "filename": "", "source_path": "", "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        if not data.get("success"):
            return {"success": False, "filename": "", "source_path": "", "error": data.get("message", "unknown error")}
        return {
            "success": True,
            "filename": data.get("filename", ""),
            "source_path": data.get("path", ""),
            "error": "",
        }
    except Exception as exc:
        return {"success": False, "filename": "", "source_path": "", "error": str(exc)}


def store_media_locally(
    source_path: str,
    original_filename: str,
    prefix: str = "wa",
) -> dict:
    """Copy media from Go Bridge store/ to Backend/uploads/ for serving via /files/.

    Returns: {ok: bool, local_path: str, url_path: str, filename: str, error: str}
    """
    if not source_path or not os.path.isfile(source_path):
        return {"ok": False, "local_path": "", "url_path": "", "filename": "", "error": f"source not found: {source_path}"}

    # Check file size
    file_size = os.path.getsize(source_path)
    if file_size > _MAX_FILE_SIZE:
        return {"ok": False, "local_path": "", "url_path": "", "filename": "", "error": f"file too large: {file_size} bytes (max {_MAX_FILE_SIZE})"}

    os.makedirs(_UPLOADS_DIR, exist_ok=True)

    # Sanitize filename
    safe_name = "".join(c for c in original_filename if c.isalnum() or c in "._-")
    if not safe_name:
        safe_name = "media"
    uid = uuid.uuid4().hex[:8]
    dest_name = f"{prefix}_{uid}_{safe_name}"
    dest_path = os.path.join(_UPLOADS_DIR, dest_name)

    try:
        shutil.copy2(source_path, dest_path)
        return {
            "ok": True,
            "local_path": dest_path,
            "url_path": f"/files/{dest_name}",
            "filename": dest_name,
            "error": "",
        }
    except Exception as exc:
        return {"ok": False, "local_path": "", "url_path": "", "filename": "", "error": str(exc)}


def get_media_metadata(
    db_path: str,
    message_id: str,
    chat_jid: str,
) -> dict:
    """Read media_type, filename, file_length from SQLite for pre-download check.

    Returns: {media_type: str, filename: str, file_length: int, error: str}
    """
    if not db_path or not os.path.exists(db_path):
        return {"media_type": "", "filename": "", "file_length": 0, "error": f"db not found: {db_path}"}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT media_type, filename, file_length FROM messages WHERE id = ? AND chat_jid = ?",
            (message_id, chat_jid),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"media_type": "", "filename": "", "file_length": 0, "error": "message not found"}
        return {
            "media_type": row[0] or "",
            "filename": row[1] or "",
            "file_length": row[2] or 0,
            "error": "",
        }
    except Exception as exc:
        return {"media_type": "", "filename": "", "file_length": 0, "error": str(exc)}
