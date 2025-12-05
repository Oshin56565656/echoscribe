# app/api/v1.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.core.config import UPLOAD_DIR
from app.services.file_utils import gen_uuid_filename, save_upload_file, save_upload_metadata
from pathlib import Path

router = APIRouter()

# Allowed MIME types (expand if needed)
ALLOWED_MIME_TYPES = {
    "audio/ogg",
    "audio/opus",
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/oga",
    "audio/mp3",
}

# maximum file size (bytes) - same default as file_utils.DEFAULT_MAX_SIZE (8MB)
MAX_FILE_SIZE = 8 * 1024 * 1024


@router.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    # Basic MIME type validation
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported audio type: {file.content_type}")

    # Create safe uuid filename preserving extension
    stored_filename = gen_uuid_filename(file.filename)
    save_path = Path(UPLOAD_DIR) / stored_filename

    try:
        size_bytes = await save_upload_file(file, save_path, max_size=MAX_FILE_SIZE)
    except ValueError as e:
        # Too large
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Save metadata
    metadata = save_upload_metadata(
        original_name=file.filename,
        stored_name=stored_filename,
        mime_type=file.content_type,
        size_bytes=size_bytes,
    )

    return {"detail": "file uploaded successfully", **metadata}

