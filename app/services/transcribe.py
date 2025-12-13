# app/services/transcribe.py
import os
import json
from pathlib import Path
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import torch
import whisper

from app.core.config import DATA_DIR

# Module-level globals for model caching and executor
_MODEL = None
_MODEL_LOCK = asyncio.Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=2)  # tune as needed

def _get_transcripts_dir() -> Path:
    p = Path(DATA_DIR) / "transcripts"
    p.mkdir(parents=True, exist_ok=True)
    return p

def _get_metadata_path(file_id: str) -> Path:
    return Path(DATA_DIR) / "uploads_meta" / f"{file_id}.json"

async def _load_model():
    """
    Load the Whisper model once; move to CUDA if available.
    This executes the blocking load in the threadpool to avoid blocking the event loop.
    """
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    async with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL

        model_name = os.getenv("WHISPER_MODEL", "small")
        loop = asyncio.get_event_loop()

        def _sync_load():
            # whisper.load_model may move model to GPU if torch detects cuda.
            m = whisper.load_model(model_name)
            if torch.cuda.is_available():
                try:
                    m.to("cuda")
                except Exception:
                    # best-effort; ignore if already on cuda or mapping differs
                    pass
            return m

        _MODEL = await loop.run_in_executor(_EXECUTOR, _sync_load)
        return _MODEL

def _read_metadata(meta_path: Path) -> dict:
    try:
        raw = meta_path.read_text(encoding="utf-8")
        return json.loads(raw) if raw else {}
    except Exception:
        return {}

def _write_metadata(meta_path: Path, meta: dict) -> None:
    try:
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # non-fatal; metadata write errors shouldn't break transcription return
        pass

async def transcribe_audio(path: str, update_metadata: bool = True) -> str:
    """
    Transcribe an audio file at `path` and return transcript text.

    - path: filesystem path to WAV/other converted audio (string).
    - update_metadata: if True, we will attempt to update data/uploads_meta/{file_id}.json
      with status/timestamps/transcript path.

    Returns:
        transcript_text (str)
    Raises:
        FileNotFoundError if input file is missing
    """
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    file_id = path_obj.stem
    transcripts_dir = _get_transcripts_dir()
    transcript_path = transcripts_dir / f"{file_id}.txt"
    meta_path = _get_metadata_path(file_id)

    # quick return if transcript already exists
    if transcript_path.exists():
        if update_metadata and meta_path.exists():
            meta = _read_metadata(meta_path)
            meta.setdefault("transcription_status", "done")
            meta.setdefault("transcript_path", str(transcript_path.resolve()))
            meta.setdefault("transcript_saved_at", datetime.utcnow().isoformat() + "Z")
            _write_metadata(meta_path, meta)
        return transcript_path.read_text(encoding="utf-8")

    # update metadata: running
    if update_metadata and meta_path.exists():
        meta = _read_metadata(meta_path)
        meta["transcription_status"] = "running"
        meta["transcription_started_at"] = datetime.utcnow().isoformat() + "Z"
        _write_metadata(meta_path, meta)

    # load model
    model = await _load_model()
    loop = asyncio.get_event_loop()

    def _sync_transcribe(p):
        # whisper's transcribe returns dict with "text" and segments
        return model.transcribe(str(p))

    try:
        result = await loop.run_in_executor(_EXECUTOR, _sync_transcribe, path_obj)
        transcript_text = result.get("text", "").strip()
    except Exception as e:
        # update metadata: failed
        if update_metadata and meta_path.exists():
            meta = _read_metadata(meta_path)
            meta["transcription_status"] = "failed"
            meta["transcription_error"] = str(e)
            meta["transcription_finished_at"] = datetime.utcnow().isoformat() + "Z"
            _write_metadata(meta_path, meta)
        raise

    # save transcript
    try:
        transcript_path.write_text(transcript_text, encoding="utf-8")
    except Exception:
        # if writing fails, still attempt to update metadata and return text
        pass

    # update metadata: done
    if update_metadata and meta_path.exists():
        try:
            meta = _read_metadata(meta_path)
        except Exception:
            meta = {}
        meta["transcription_status"] = "done"
        meta["transcription_finished_at"] = datetime.utcnow().isoformat() + "Z"
        meta["transcript_path"] = str(transcript_path.resolve())
        meta["transcript_saved_at"] = datetime.utcnow().isoformat() + "Z"
        # store a snippet to preview quickly
        meta["transcript_snippet"] = transcript_text[:512]
        _write_metadata(meta_path, meta)

    return transcript_text

