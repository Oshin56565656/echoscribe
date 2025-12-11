# app/services/conversion.py
import asyncio
from pathlib import Path
from typing import Tuple

async def run_command(*cmd) -> Tuple[int, str, str]:
    """Run a subprocess command asynchronously and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, (stdout.decode().strip() if stdout else ""), (stderr.decode().strip() if stderr else "")


async def convert_opus_to_wav(input_path: Path, output_path: Path, sample_rate: int = 16000):
    """
    Convert an input audio (opus/ogg/oga/mp3/etc) to a WAV file suitable for Whisper.
    - output_path parent will be created if missing.
    - uses mono (1 channel), signed 16-bit PCM, and sets the sample rate.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",  # overwrite
        "-i", str(input_path),
        "-ac", "1",  # mono
        "-ar", str(sample_rate),  # sample rate
        "-sample_fmt", "s16",
        str(output_path),
    ]

    rc, out, err = await run_command(*cmd)
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (rc={rc})\nstdout: {out}\nstderr: {err}")
    return output_path


async def get_duration_seconds(file_path: Path) -> float:
    """
    Use ffprobe to return duration in seconds (float).
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(file_path),
    ]
    rc, out, err = await run_command(*cmd)
    if rc != 0:
        raise RuntimeError(f"ffprobe failed (rc={rc})\nstdout: {out}\nstderr: {err}")
    try:
        return float(out.strip())
    except Exception as e:
        raise RuntimeError(f"Could not parse duration from ffprobe output: {out}") from e

