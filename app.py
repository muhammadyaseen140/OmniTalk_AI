import html
import os
import shutil
import tempfile
import uuid

import streamlit as st
from dotenv import load_dotenv

from src.youtube_utils import download_youtube_audio
from src.audio_utils import transcribe_audio
from src.rag_engine import build_rag_session, generate_summary
from src.auth import require_login, logout

load_dotenv()

APP_NAME = "OmniTalk AI"

st.set_page_config(page_title=f"{APP_NAME} | Media RAG Platform", page_icon="🎙️", layout="wide")

st.markdown("""
    <style>
    .main-title { font-size: 2.2rem; font-weight: 700; }
    .sub-title { font-size: 1rem; opacity: 0.7; margin-bottom: 1.5rem; }
    </style>
""", unsafe_allow_html=True)

# ---------- Authentication gate (shows Sign In / Sign Up page until logged in) ----------
user = require_login()

# ---------- Session state ----------
st.session_state.setdefault("sessions", {})
st.session_state.setdefault("active_session_id", None)
st.session_state.setdefault("is_new_session", False)
st.session_state.setdefault("api_key", "")


def get_api_key() -> str:
    # Per-user key (kept in this browser session only), falls back to .env
    return st.session_state.api_key or os.getenv("OPENAI_API_KEY", "")


# ---------- Sidebar ----------
with st.sidebar:
    st.title("⚙️ Workspace Panel")

    st.session_state.api_key = st.text_input(
        "OpenAI API Key:", type="password",
        value=st.session_state.api_key,
        help="Used only for your current session. Overrides the .env key if entered.",
    )

    st.divider()
    st.subheader("📁 History & Sessions")

    if st.button("➕ Start New Session", use_container_width=True):
        st.session_state.active_session_id = None
        st.session_state.is_new_session = True
        st.rerun()

    if st.session_state.sessions:
        keys = list(st.session_state.sessions.keys())
        titles = [st.session_state.sessions[k]["title"] for k in keys]

        if st.session_state.is_new_session or st.session_state.active_session_id is None:
            choice = st.selectbox("Select Processed Media History:",
                                  options=["-- Create New Session --"] + titles, index=0)
            if choice != "-- Create New Session --":
                st.session_state.active_session_id = keys[titles.index(choice)]
                st.session_state.is_new_session = False
                st.rerun()
        else:
            current = keys.index(st.session_state.active_session_id)
            choice = st.selectbox("Select Processed Media History:", options=titles, index=current)
            st.session_state.active_session_id = keys[titles.index(choice)]
    else:
        st.caption("No media history logged yet.")

    st.divider()
    st.subheader("📥 Process Media Source")

    language_mode = st.radio(
        "Transcript language:",
        ["Translate to English", "Keep original language"],
    )
    input_method = st.radio("Choose Input Method:", ["YouTube Link", "Upload Audio File"])

    yt_url, uploaded_file = "", None
    if input_method == "YouTube Link":
        yt_url = st.text_input("YouTube Video URL:")
        st.caption("If YouTube blocks the download on this hosted version, use \"Upload Audio File\" instead.")
        process_btn = st.button("Extract & Process", type="primary", use_container_width=True)
    else:
        uploaded_file = st.file_uploader("Upload Audio (supports large files):", type=["mp3", "wav", "m4a"])
        process_btn = st.button("Process Audio File", type="primary", use_container_width=True)

    # ---- User profile (bottom of sidebar) ----
    st.divider()
    initial = html.escape(user["name"][:1].upper() or "?")
    st.markdown(
        '<div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.75rem;">'
        '<div style="width:2.4rem;height:2.4rem;border-radius:50%;flex-shrink:0;'
        'background:linear-gradient(135deg,#6366F1,#A855F7);color:#fff;'
        f'display:flex;align-items:center;justify-content:center;font-weight:700;">{initial}</div>'
        '<div style="line-height:1.3;min-width:0;">'
        f'<div style="font-weight:600;">{html.escape(user["name"])}</div>'
        f'<div style="font-size:.8rem;opacity:.65;overflow:hidden;text-overflow:ellipsis;">{html.escape(user["email"])}</div>'
        '</div></div>',
        unsafe_allow_html=True,
    )
    if st.button("Sign out", icon=":material/logout:", use_container_width=True):
        logout()

# ---------- Header ----------
st.markdown(f"<div class='main-title'>🎙️ {APP_NAME}</div>", unsafe_allow_html=True)
st.markdown("<div class='sub-title'>Extract insights, generate executive summaries, and chat with media content.</div>",
            unsafe_allow_html=True)

# ---------- Processing ----------
if process_btn:
    api_key = get_api_key()
    if not api_key:
        st.error("⚠️ OpenAI API Key missing! Please enter it in the sidebar.")
    elif input_method == "YouTube Link" and not yt_url.strip():
        st.warning("Please paste a YouTube URL.")
    elif input_method == "Upload Audio File" and uploaded_file is None:
        st.warning("Please upload an audio file.")
    else:
        work_dir = None
        try:
            with st.spinner("Processing media... (large files may take a few minutes)"):
                if input_method == "YouTube Link":
                    st.toast("Extracting audio from YouTube...", icon="📥")
                    audio_path, session_title = download_youtube_audio(yt_url.strip())
                    work_dir = os.path.dirname(audio_path)
                else:
                    st.toast("Saving uploaded audio...", icon="💾")
                    work_dir = tempfile.mkdtemp()
                    session_title = os.path.splitext(uploaded_file.name)[0]
                    audio_path = os.path.join(work_dir, uploaded_file.name)
                    with open(audio_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                st.toast("Transcribing with Whisper...", icon="🎙️")
                transcript = transcribe_audio(
                    audio_path, api_key,
                    translate_to_english=(language_mode == "Translate to English"),
                )
                if not transcript.strip():
                    raise RuntimeError("No speech was detected in this audio.")

                st.toast("Generating executive summary...", icon="📝")
                summary = generate_summary(transcript, api_key)

                st.toast("Creating vector index...", icon="🧠")
                rag = build_rag_session(transcript, api_key)

                session_id = f"session_{uuid.uuid4().hex[:8]}"
                st.session_state.sessions[session_id] = {
                    "title": session_title,
                    "rag": rag,
                    "summary": summary,
                    "transcript": transcript,
                    "history": [],
                }
                st.session_state.active_session_id = session_id
                st.session_state.is_new_session = False

            st.success(f"Successfully processed: '{session_title}'")
            st.rerun()
        except Exception as e:
            st.error(f"Processing Error: {e}")
        finally:
            if work_dir:
                shutil.rmtree(work_dir, ignore_errors=True)  # always clean temp files

# ---------- Active session ----------
active_id = st.session_state.active_session_id
if active_id in st.session_state.sessions and not st.session_state.is_new_session:
    data = st.session_state.sessions[active_id]

    col_hdr, col_btn = st.columns([4, 1])
    with col_hdr:
        st.subheader(f"📌 Active Session: {data['title']}")
    with col_btn:
        if st.button("🗑️ Clear Chat History", use_container_width=True):
            data["history"] = []
            st.rerun()

    with st.expander("📄 Executive Summary", expanded=True):
        st.write(data["summary"])
    with st.expander("📝 Full Transcript"):
        st.write(data["transcript"])

    st.divider()
    st.subheader("💬 Chat Now")

    for msg in data["history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander("Sources from transcript"):
                    for i, s in enumerate(msg["sources"], 1):
                        st.caption(f"Source {i}")
                        st.write(s)

    question = st.chat_input(f"Ask any question about '{data['title']}'...")
    if question:
        with st.chat_message("user"):
            st.markdown(question)

        try:
            with st.spinner("Analyzing context..."):
                prior = [{"role": m["role"], "content": m["content"]} for m in data["history"]]
                answer, sources = data["rag"].ask(question, prior)
        except Exception as e:
            st.error(f"Could not get an answer: {e}")
        else:
            data["history"].append({"role": "user", "content": question})
            data["history"].append({"role": "assistant", "content": answer, "sources": sources})
            st.rerun()
else:
    st.info("👈 Enter a YouTube URL or upload an audio file in the sidebar to begin a new session.")
