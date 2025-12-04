from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
from app.core.config import UPLOAD_DIR

router = APIRouter()

@router.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    # basic validation
    allowed = {"audio/ogg", "audio/opus", "audio/mpeg", "audio/wav", "audio/x-wav"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported audio type")
    save_path = UPLOAD_DIR / file.filename
    # write file
    with save_path.open("wb") as f:
        content = await file.read()
        f.write(content)
    return {"filename": file.filename, "detail": "saved"}

