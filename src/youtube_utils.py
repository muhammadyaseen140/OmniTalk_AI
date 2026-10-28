import os
import tempfile
import yt_dlp


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
    except yt_dlp.utils.DownloadError:
        raise RuntimeError(
            "Could not download this video. Check the URL, make sure the video is public, "
            "and that FFmpeg is installed. (YouTube may also block downloads from cloud servers.)"
        )

    for name in os.listdir(temp_dir):
        if name.endswith(".mp3"):
            return os.path.join(temp_dir, name), title

    raise RuntimeError("Failed to extract audio from the YouTube URL.")
