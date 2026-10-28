# 🎙️ OmniTalk AI

**Chat with any YouTube video or audio file.** OmniTalk AI transcribes media, generates an executive summary, and lets you ask questions about the content through a RAG (Retrieval-Augmented Generation) chatbot.

> 🎬 **Demo video:** _add your link here_  
> 🌐 **Live demo:** _add your Streamlit link here_

---

## ✨ Features

- **Two input methods:** paste a YouTube link or upload an audio file (`mp3`, `wav`, `m4a`)
- **Large file support:** long recordings are automatically split into 10-minute chunks with FFmpeg
- **Multilingual:** translate speech to English, or keep the transcript in the original language
- **Executive summary:** map-reduce summarization that works on very long transcripts
- **RAG chat with memory:** follow-up questions work ("What did he mean by that?")
- **Source transparency:** every answer shows the transcript passages it was based on
- **Multiple sessions:** process several media files and switch between them without mixing data
- **Secure key handling:** each user's OpenAI API key stays in their own session
- **User accounts:** sign up, sign in, forgot password (email code), and **Continue with Google**
- **Account security:** bcrypt-hashed passwords, brute-force lockout, expiring one-time reset codes

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| UI | Streamlit |
| Transcription | OpenAI Whisper API |
| Audio processing | FFmpeg, yt-dlp |
| Embeddings | OpenAI `text-embedding-3-small` |
| LLM | OpenAI `gpt-4o-mini` |
| Vector store | ChromaDB |
| Text splitting | LangChain |
| Authentication | SQLite, bcrypt, Streamlit OIDC (Google) |

---

## 🏗️ How It Works

```
YouTube link / Audio file
        │
        ▼
 Audio extraction (yt-dlp + FFmpeg)
        │
        ▼
 Whisper transcription (chunked if > 24 MB)
        │
        ├──► Map-reduce summary
        │
        ▼
 Text chunks ──► Embeddings ──► ChromaDB
                                   │
 User question ──► Standalone question (uses chat history)
                                   │
                                   ▼
                      Retrieve top chunks ──► LLM answer + sources
```

---

## 📁 Project Structure

```
.
├── app.py                 # Streamlit UI and session management
├── requirements.txt
├── .env.example           # Copy to .env (API key, optional SMTP settings)
├── .streamlit/
│   └── secrets.toml.example   # Copy to secrets.toml (Google login)
└── src/
    ├── __init__.py
    ├── auth.py            # Sign up / sign in / reset password / Google login
    ├── audio_utils.py     # Whisper transcription + FFmpeg chunking
    ├── youtube_utils.py   # YouTube audio download
    └── rag_engine.py      # Indexing, retrieval, chat memory, summarization
```

---

## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and available on your system `PATH`
- An [OpenAI API key](https://platform.openai.com/api-keys)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

# 2. (Recommended) Create a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

### Configuration

**OpenAI key.** Provide it in either way:

- Enter it in the app sidebar (kept only for your current session), **or**
- Copy `.env.example` to `.env` and set `OPENAI_API_KEY=sk-your-key-here`

**Forgot-password emails (optional).** Set the `SMTP_*` variables in `.env` (see `.env.example`).
Without them the app runs in *demo mode* and shows the reset code on screen, which is handy for local testing and demo videos but should not be used in production.

**Google sign-in (optional).**

1. Open [Google Cloud Console](https://console.cloud.google.com/) → *APIs & Services* → *Credentials* → *Create credentials* → *OAuth client ID* → *Web application*.
2. Add this **Authorized redirect URI**: `http://localhost:8501/oauth2callback` (and your production URL + `/oauth2callback` when you deploy).
3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in the client ID, client secret and a random `cookie_secret`.
4. Restart the app. The *Continue with Google* button becomes active.

Email/password sign-in works without any of this setup.

### Run

```bash
streamlit run app.py
```

Then open the URL shown in your terminal (usually http://localhost:8501).

---

## 📖 Usage

1. Create an account (or continue with Google) and sign in.
2. Enter your OpenAI API key in the sidebar.
3. Choose the transcript language: **Translate to English** or **Keep original language**.
4. Paste a YouTube URL or upload an audio file, then click **Process**.
5. Read the executive summary and full transcript.
6. Ask questions in the chat box and expand **Sources from transcript** to verify answers.
7. Click **Start New Session** to process another file. Previous sessions stay in the history dropdown.

---

## ⚠️ Notes & Limitations

- **Cost:** the app uses your OpenAI API key. Whisper, embeddings, and chat calls are billed by OpenAI.
- **YouTube on cloud hosting:** YouTube often blocks downloads from cloud servers (Streamlit Cloud, Render, etc.). It works reliably when run locally; the file upload method is the recommended option for hosted deployments.
- **Sessions are in-memory:** history and vector indexes are lost when the app restarts.
- **Email/password login lasts for the browser tab session:** refreshing the page asks you to sign in again. Google login persists via cookies.
- **User database:** `users.db` (SQLite) is created automatically. On hosts with ephemeral storage (e.g. Streamlit Cloud) it resets on redeploy; use a hosted database for production.
- **Accuracy:** answers are generated only from the transcript. Transcription quality depends on audio clarity.

---

## 🛣️ Roadmap

- [ ] Timestamps in source references
- [ ] Persistent storage for sessions
- [ ] Video file upload (`mp4`)
- [ ] Export summary and chat to PDF

---
