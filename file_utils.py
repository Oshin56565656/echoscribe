# app/services/file_utils.py
import uuid
from pathlib import Path
from typing import Dict, Any
import aiofiles
from fastapi import UploadFile
import os
from datetime import datetime
from app.core.config import UPLOAD_DIR, DATA_DIR

# default max size (bytes) - 8 MB
DEFAULT_MAX_SIZE = 8 * 1024 * 1024


def gen_uuid_filename(original_name: str) -> str:
    """
    Generate a safe uuid filename preserving the original extension (if any).
    Returns something like: 3f1a2b...e4f.opus
    """
    ext = Path(original_name).suffix or ""
    return f"{uuid.uuid4().hex}{ext}"


async def save_upload_file(
    upload_file: UploadFile,
    dest_path: Path,
    max_size: int = DEFAULT_MAX_SIZE,
) -> int:
    """
    Save an UploadFile to dest_path asynchronously in chunks.
    Returns the number of bytes written.

    Raises ValueError if file exceeds max_size.
    """
    total = 0
    # Ensure parent exists
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Read in chunks to avoid loading whole file into memory
    chunk_size = 1024 * 1024  # 1 MB
    async with aiofiles.open(dest_path, "wb") as out_file:
        while True:
            chunk = await upload_file.read(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > max_size:
                # cleanup partial file
                await out_file.close()
                try:
                    dest_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise ValueError(f"File size exceeds max limit of {max_size} bytes")
            await out_file.write(chunk)
    # reset file pointer (in case caller wants to reuse UploadFile, optional)
    try:
        await upload_file.seek(0)
    except Exception:
        pass
    return total


def save_upload_metadata(
    original_name: str,
    stored_name: str,
    mime_type: str,
    size_bytes: int,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Save JSON metadata for an uploaded file into data/uploads_meta/<uuid>.json
    Returns the metadata dict written.
    """
    file_id = Path(stored_name).stem
    meta_dir = DATA_DIR / "uploads_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "file_id": file_id,
        "original_name": original_name,
        "stored_name": stored_name,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
    }
    if extra:
        metadata["extra"] = extra

    meta_path = meta_dir / f"{file_id}.json"
    # write synchronously (small file) using built-in open
    with meta_path.open("w", encoding="utf-8") as f:
        import json
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return metadata

