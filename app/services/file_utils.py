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


# --- New: conversion integration ---
from app.services import conversion  # uses the new file app/services/conversion.py
from typing import Optional

# audio extensions we want to convert (WhatsApp uses .opus inside ogg container sometimes)
CONVERT_EXTS = {".opus", ".oga", ".ogg", ".mp3", ".m4a"}


async def save_and_convert_upload(
    upload_file: UploadFile,
    dest_path: Path,
    max_size: int = DEFAULT_MAX_SIZE,
    sample_rate: int = 16000,
) -> Dict[str, Any]:
    """
    High-level helper: save the uploaded file, optionally convert to WAV and
    write metadata including converted file path + duration.
    Returns the metadata dictionary written (same shape as save_upload_metadata return).
    """
    # 1) Save original file
    size_bytes = await save_upload_file(upload_file, dest_path, max_size=max_size)

    extra = {}
    original_suffix = dest_path.suffix.lower()

    # 2) If it's a convertible extension, run conversion
    if original_suffix in CONVERT_EXTS:
        # Create converted filename (same UUID stem + .wav)
        converted_name = f"{dest_path.stem}.wav"
        # create a converted directory inside uploads (e.g., uploads/converted/)
        converted_dir = Path(UPLOAD_DIR) / "converted"
        converted_dir.mkdir(parents=True, exist_ok=True)
        converted_path = converted_dir / converted_name

        # Run conversion (async)
        try:
            await conversion.convert_opus_to_wav(dest_path, converted_path, sample_rate=sample_rate)
            duration = await conversion.get_duration_seconds(converted_path)
            extra["converted_name"] = converted_name
            # store relative paths (string) so JSON is simple
            extra["converted_path"] = str(converted_path.resolve())
            extra["duration_seconds"] = duration
        except Exception as e:
            # If conversion fails, include an error note in metadata but don't crash the server.
            extra["conversion_error"] = str(e)

    # 3) Save metadata (including extra if present)
    metadata = save_upload_metadata(
        original_name=upload_file.filename,
        stored_name=dest_path.name,
        mime_type=upload_file.content_type,
        size_bytes=size_bytes,
        extra=extra if extra else None,
    )

    # add converted fields at top-level for convenience if present
    if extra:
        if "converted_name" in extra:
            metadata["converted_name"] = extra.get("converted_name")
            metadata["converted_path"] = extra.get("converted_path")
            metadata["duration_seconds"] = extra.get("duration_seconds")
        if "conversion_error" in extra:
            metadata["conversion_error"] = extra.get("conversion_error")

    return metadata

