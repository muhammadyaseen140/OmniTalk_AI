import os
import re
import shutil
import tempfile
import yt_dlp


def _friendly_error(detail: str) -> str:
    low = detail.lower()
    if "ffmpeg" in low or "ffprobe" in low:
        return "FFmpeg is not installed on this server. Add a packages.txt file containing 'ffmpeg' (hosted) or install FFmpeg (local)."
    if any(k in low for k in ("sign in", "not a bot", "429", "403", "forbidden", "cookies")):
        return ("YouTube blocked the download from this server (common on cloud hosting). "
                "Please use the 'Upload Audio File' option instead.")
    if any(k in low for k in ("private", "unavailable", "removed", "not available")):
        return "This video is private or unavailable."
    if "unsupported url" in low or "is not a valid url" in low:
        return "That doesn't look like a valid YouTube URL."
    return "Could not download this video."


def download_youtube_audio(url: str) -> tuple[str, str]:
    """
    Downloads YouTube audio as low-bitrate mp3.
    Returns (file_path, video_title). The caller must delete
    os.path.dirname(file_path) when finished.
    """
    temp_dir = tempfile.mkdtemp()
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "32",
        }],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "YouTube Audio")
    except yt_dlp.utils.YoutubeDLError as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        detail = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "").strip()
        raise RuntimeError(f"{_friendly_error(detail)}\n\nTechnical detail: {detail[:300]}")

    for name in os.listdir(temp_dir):
        if name.endswith(".mp3"):
            return os.path.join(temp_dir, name), title

    shutil.rmtree(temp_dir, ignore_errors=True)
    raise RuntimeError("Failed to extract audio from the YouTube URL.")
