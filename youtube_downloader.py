"""
Simple YouTube Downloader - Streamlit App
Paste a YouTube URL, pick a resolution (or audio-only), and download.
"""

import streamlit as st
import yt_dlp
import os
import re
import tempfile

# ---------- Page Setup ----------
st.set_page_config(page_title="YouTube Downloader", page_icon="🎬", layout="centered")
st.title("🎬 YouTube Downloader")
st.caption("Paste a YouTube link, choose your format, and download.")

# ---------- Helpers ----------
def sanitize_filename(name: str) -> str:
    """Remove characters that are illegal in filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    # YouTube blocks the default web client aggressively from cloud IPs.
    # Falling back through android/ios/web tvhtml5 clients raises the success rate.
    "extractor_args": {
        "youtube": {"player_client": ["android", "ios", "web", "tv_embedded"]},
    },
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    },
    "retries": 5,
    "fragment_retries": 5,
}


def get_video_info(url: str) -> dict:
    """Fetch metadata + available formats without downloading."""
    ydl_opts = {**YDL_BASE_OPTS, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def parse_formats(info: dict):
    """
    Build two lists:
      - video_options: unique video resolutions (with audio merged on download)
      - audio_options: audio-only streams
    """
    formats = info.get("formats", [])
    video_seen = {}
    audio_options = []

    for f in formats:
        # Video streams (have a height)
        if f.get("vcodec") != "none" and f.get("height"):
            height = f["height"]
            ext = f.get("ext", "mp4")
            label = f"{height}p ({ext})"
            # keep only the best entry per resolution
            if height not in video_seen:
                video_seen[height] = {"label": label, "height": height, "ext": ext}

        # Audio-only streams
        elif f.get("vcodec") == "none" and f.get("acodec") != "none":
            abr = f.get("abr") or 0
            ext = f.get("ext", "m4a")
            audio_options.append(
                {
                    "label": f"{int(abr)} kbps ({ext})" if abr else f"audio ({ext})",
                    "format_id": f["format_id"],
                    "ext": ext,
                    "abr": abr,
                }
            )

    # sort: video high → low, audio high → low bitrate
    video_options = sorted(video_seen.values(), key=lambda x: x["height"], reverse=True)
    audio_options = sorted(audio_options, key=lambda x: x["abr"], reverse=True)
    return video_options, audio_options


def download_media(url: str, output_dir: str, choice: dict, progress_placeholder):
    """Download the chosen format into output_dir. Returns the final filepath."""

    def hook(d):
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "").strip()
            speed = d.get("_speed_str", "").strip()
            progress_placeholder.info(f"⬇️ Downloading... {pct} at {speed}")
        elif d["status"] == "finished":
            progress_placeholder.success("✅ Download finished. Processing...")

    if choice["type"] == "video":
        # merge best audio with chosen video height
        format_str = (
            f"bestvideo[height<={choice['height']}]+bestaudio/best[height<={choice['height']}]"
        )
        ydl_opts = {
            **YDL_BASE_OPTS,
            "format": format_str,
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "progress_hooks": [hook],
        }
    else:  # audio
        ydl_opts = {
            **YDL_BASE_OPTS,
            "format": "bestaudio/best",
            "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
            "progress_hooks": [hook],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if choice["type"] == "audio":
            filename = os.path.splitext(filename)[0] + ".mp3"
        elif choice["type"] == "video":
            filename = os.path.splitext(filename)[0] + ".mp4"
    return filename


# ---------- UI ----------
url = st.text_input("🔗 YouTube URL", placeholder="https://www.youtube.com/watch?v=...")

# Session state to keep info between reruns
if "info" not in st.session_state:
    st.session_state.info = None
    st.session_state.video_opts = []
    st.session_state.audio_opts = []

if st.button("🔍 Fetch video info", type="primary", width="stretch"):
    if not url.strip():
        st.warning("Please paste a YouTube URL first.")
    else:
        try:
            with st.spinner("Fetching video info..."):
                info = get_video_info(url.strip())
                v_opts, a_opts = parse_formats(info)
                st.session_state.info = info
                st.session_state.video_opts = v_opts
                st.session_state.audio_opts = a_opts
        except Exception as e:
            st.error(f"Could not fetch video: {e}")

# After fetching, show options
if st.session_state.info:
    info = st.session_state.info
    st.divider()

    col1, col2 = st.columns([1, 2])
    with col1:
        if info.get("thumbnail"):
            st.image(info["thumbnail"], width="stretch")
    with col2:
        st.subheader(info.get("title", "Untitled"))
        st.write(f"**Channel:** {info.get('uploader', 'Unknown')}")
        duration = info.get("duration", 0)
        if duration:
            mins, secs = divmod(duration, 60)
            st.write(f"**Duration:** {mins}:{secs:02d}")
        if info.get("view_count"):
            st.write(f"**Views:** {info['view_count']:,}")

    st.divider()
    st.subheader("Choose format")

    mode = st.radio("Format type", ["Video (with audio)", "Audio only (mp3)"], horizontal=True)

    choice = None
    if mode == "Video (with audio)":
        if st.session_state.video_opts:
            labels = [opt["label"] for opt in st.session_state.video_opts]
            picked = st.selectbox("Resolution", labels)
            chosen = next(o for o in st.session_state.video_opts if o["label"] == picked)
            choice = {"type": "video", "height": chosen["height"]}
        else:
            st.warning("No video formats found.")
    else:
        if st.session_state.audio_opts:
            st.info("Audio will be extracted as MP3 at the best available quality (192 kbps).")
            choice = {"type": "audio"}
        else:
            st.warning("No audio formats found.")

    if choice and st.button("⬇️ Prepare download", type="primary", width="stretch"):
        progress_placeholder = st.empty()
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                final_path = download_media(url.strip(), tmp_dir, choice, progress_placeholder)
                with open(final_path, "rb") as f:
                    file_bytes = f.read()
            st.success("🎉 Ready! Click below to save to your device.")
            st.download_button(
                label="💾 Download file",
                data=file_bytes,
                file_name=os.path.basename(final_path),
                mime="video/mp4" if choice["type"] == "video" else "audio/mpeg",
                width="stretch",
            )
        except Exception as e:
            msg = str(e)
            if "403" in msg or "Forbidden" in msg or "Sign in" in msg:
                st.error(
                    "YouTube blocked this request from the server. This is common "
                    "on cloud-hosted apps because YouTube rate-limits datacenter IPs. "
                    "Try again in a minute, try a different video, or run the app locally."
                )
            else:
                st.error(f"Download failed: {e}")

# ---------- Footer ----------
st.divider()
with st.expander("💡 Tips & notes"):
    st.markdown(
        """
        - **Large videos may take a while** — the file is prepared on the server
          before the download button appears.
        - **MP3 audio** is extracted at 192 kbps for a good size/quality balance.
        - **Only download content you have the right to download.** Please respect
          creators' copyright and YouTube's Terms of Service.
        """
    )

st.caption("Built by Godsgift Olomu")
