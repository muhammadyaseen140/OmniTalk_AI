import os
import glob
import shutil
import subprocess
import tempfile
from openai import OpenAI

MAX_DIRECT_MB = 24  # Whisper API limit is 25MB


def transcribe_audio(file_path: str, api_key: str, translate_to_english: bool = True) -> str:
    """
    Transcribes audio with OpenAI Whisper.
    - translate_to_english=True  -> English translation
    - translate_to_english=False -> transcript in the original language
    Large files are split into 10-minute chunks using system FFmpeg.
    """
    client = OpenAI(api_key=api_key)
    api = client.audio.translations if translate_to_english else client.audio.transcriptions

    def _run(path: str) -> str:
        with open(path, "rb") as f:
            return api.create(model="whisper-1", file=f).text

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb < MAX_DIRECT_MB:
        return _run(file_path)

    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "FFmpeg is not installed. Large files need FFmpeg to be split. "
            "Install FFmpeg and add it to your system PATH."
        )

    output_dir = tempfile.mkdtemp()
    try:
        command = [
            "ffmpeg", "-y", "-i", file_path,
            "-f", "segment", "-segment_time", "600",
            "-c:a", "libmp3lame", "-b:a", "32k",
            os.path.join(output_dir, "chunk_%03d.mp3"),
        ]
        try:
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        except subprocess.CalledProcessError:
            raise RuntimeError("FFmpeg could not process this audio file. The file may be corrupted.")

        chunk_files = sorted(glob.glob(os.path.join(output_dir, "chunk_*.mp3")))
        if not chunk_files:
            raise RuntimeError("FFmpeg finished but produced no audio chunks.")

        return " ".join(_run(c) for c in chunk_files)
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)
