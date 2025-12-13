# app/api/v1.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from app.core.config import UPLOAD_DIR, DATA_DIR
from app.services.file_utils import gen_uuid_filename, save_and_convert_upload
from app.services.transcribe import transcribe_audio
from pathlib import Path
import json

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
        metadata = await save_and_convert_upload(file, save_path, max_size=MAX_FILE_SIZE)
    except ValueError as e:
        # Too large
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save/convert file: {e}")

    return {"detail": "file uploaded successfully", **metadata}


def _metadata_path_for(file_id: str) -> Path:
    return Path(DATA_DIR) / "uploads_meta" / f"{file_id}.json"


@router.get("/transcribe/{file_id}")
async def get_transcript(file_id: str):
    """
    Blocking transcription endpoint:
    - Reads metadata for converted_path (top-level, then meta['extra'], then converted_name fallback)
    - Marks transcription status in metadata (running/done/failed)
    - Runs Whisper transcription (in background thread)
    - Saves transcript to data/transcripts/{file_id}.txt
    - Returns the full transcript text in JSON
    """
    meta_path = _metadata_path_for(file_id)
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="file metadata not found")

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8") or "{}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to read metadata: {e}")

    # tolerant lookup for converted_path:
    # 1) top-level converted_path
    # 2) meta['extra'].converted_path or converted_name
    # 3) top-level converted_name fallback to uploads/converted/<name>
    converted_path = meta.get("converted_path")
    if not converted_path:
        extra = meta.get("extra") or {}
        converted_path = extra.get("converted_path") or extra.get("converted_name")

    if not converted_path:
        converted_name = meta.get("converted_name")
        if converted_name:
            converted_path = str(Path("uploads/converted") / converted_name)
        else:
            raise HTTPException(status_code=400, detail="converted audio path not available in metadata")

    # Ensure converted file exists (support absolute or relative)
    if not Path(converted_path).exists():
        # If converted_path is relative, maybe it's relative to project root; try resolve
        alt = Path(DATA_DIR).parent / converted_path if not Path(converted_path).is_absolute() else None
        if alt and alt.exists():
            converted_path = str(alt.resolve())
        else:
            raise HTTPException(status_code=404, detail="converted audio file not found")

    try:
        transcript = await transcribe_audio(converted_path, update_metadata=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="converted audio file not found")
    except Exception as e:
        # transcribe_audio already updates metadata with failure; return 500 to client
        raise HTTPException(status_code=500, detail=f"transcription failed: {e}")

    transcript_path = Path(DATA_DIR) / "transcripts" / f"{file_id}.txt"
    return {
        "file_id": file_id,
        "transcript": transcript,
        "transcript_path": str(transcript_path.resolve()),
        "status": "done",
    }

