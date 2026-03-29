from flask import Flask, request, jsonify
import subprocess
import os
import requests
import tempfile
import random
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
import textwrap
import yt_dlp

app = Flask(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

WIDTH  = 540
HEIGHT = 960

MUSIC_URLS = [
    "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
    "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3",
    "https://www.soundhelix.com/examples/mp3/SoundHelix-Song-3.mp3",
]

HOOK_TEMPLATES = [
    "Nobody believed him...",
    "This moment changed everything.",
    "They said it was impossible.",
    "The whole world stopped.",
    "History was made here.",
    "No one saw this coming.",
    "This is why he's the GOAT.",
    "The greatest moment ever.",
    "They will never forget this.",
    "One touch. One legend.",
]

# ── yt-dlp: تحميل فيديو من YouTube ─────────────────────────────────────────
def download_youtube_video(youtube_url: str, output_path: str) -> bool:
    ydl_opts = {
        'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
        'outtmpl': output_path,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'noplaylist': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        return os.path.exists(output_path) and os.path.getsize(output_path) > 10000
    except Exception as e:
        print(f"yt-dlp error: {e}")
        return False

# ── تحميل موسيقى خلفية ──────────────────────────────────────────────────────
def download_music(output_path: str) -> bool:
    url = random.choice(MUSIC_URLS)
    try:
        r = requests.get(url, timeout=30, stream=True)
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(32768):
                f.write(chunk)
        return os.path.getsize(output_path) > 1000
    except Exception as e:
        print(f"Music download error: {e}")
        return False

# ── Hook إنجليزي فوق الفيديو ────────────────────────────────────────────────
def create_hook_overlay(hook_text: str, output_path: str):
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font_hook  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except:
        font_hook = font_small = ImageFont.load_default()

    # شريط Hook علوي - خلفية شبه شفافة
    draw.rectangle([(0, 0), (WIDTH, 100)], fill=(0, 0, 0, 180))

    # نص Hook بالإنجليزية
    wrapped = textwrap.fill(hook_text, width=22)
    y = 20
    for line in wrapped.split("\n"):
        draw.text((WIDTH // 2, y), line,
                  fill=(255, 215, 0, 255),
                  font=font_hook,
                  anchor="mm")
        y += 45

    # شريط سفلي للهاشتاقات
    draw.rectangle([(0, HEIGHT - 70), (WIDTH, HEIGHT)], fill=(0, 0, 0, 180))
    draw.text((WIDTH // 2, HEIGHT - 35),
              "#Football #GOAT #WC2026 #Soccer",
              fill=(255, 255, 255, 200),
              font=font_small,
              anchor="mm")

    img.save(output_path)

# ── تجميع الفيديو النهائي ────────────────────────────────────────────────────
def build_final_video(raw_video: str, music_path: str, overlay_path: str,
                      output_path: str, start_time: float = 0, duration: float = 75.0):
    """
    - يقص الفيديو من start_time لمدة duration ثانية
    - يحوله إلى 9:16
    - يضيف Hook overlay
    - يضيف موسيقى درامية بـ fade in/out
    - بدون صوت أصلي (يتفادى حقوق الملكية)
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_time),
        "-i", raw_video,
        "-i", overlay_path,
        "-i", music_path,
        "-filter_complex",
        (
            f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,setpts=PTS-STARTPTS[base];"
            f"[base][1:v]overlay=0:0:format=auto[v];"
            f"[2:a]afade=t=in:st=0:d=2,afade=t=out:st={duration-3}:d=3,"
            f"volume=0.4[a]"
        ),
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(duration),
        "-pix_fmt", "yuv420p",
        "-threads", "2",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {result.stderr.decode()[-500:]}")

# ── إرسال لـ Telegram ────────────────────────────────────────────────────────
def send_to_telegram(video_path: str, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, "rb") as f:
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption[:1024],
            "parse_mode": "Markdown"
        }, files={"video": f}, timeout=120)
    return r.json()

# ── Endpoint الجديد: YouTube → TikTok ───────────────────────────────────────
@app.route("/create-football-video", methods=["POST"])
def create_football_video():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400

    youtube_url = data.get("youtube_url", "")
    hook        = data.get("hook", random.choice(HOOK_TEMPLATES))
    caption     = data.get("caption", "⚽ Football moment 🔥\n\n#Football #Soccer #WC2026")
    start_time  = float(data.get("start_time", 10))
    duration    = float(data.get("duration", 75))
    duration    = max(60.0, min(90.0, duration))

    if not youtube_url:
        return jsonify({"error": "youtube_url required"}), 400

    output_path = tempfile.mktemp(suffix=".mp4")

    try:
        with tempfile.TemporaryDirectory() as tmp:

            # 1. تحميل الفيديو من YouTube
            raw_video = os.path.join(tmp, "raw.mp4")
            if not download_youtube_video(youtube_url, raw_video):
                return jsonify({"error": "Failed to download YouTube video"}), 500

            # 2. تحميل موسيقى درامية
            music_path = os.path.join(tmp, "music.mp3")
            has_music = download_music(music_path)

            # 3. إنشاء Hook overlay
            overlay_path = os.path.join(tmp, "overlay.png")
            create_hook_overlay(hook, overlay_path)

            # 4. تجميع الفيديو
            if has_music:
                build_final_video(raw_video, music_path, overlay_path,
                                  output_path, start_time, duration)
            else:
                # بدون موسيقى إذا فشل التحميل
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start_time),
                    "-i", raw_video,
                    "-i", overlay_path,
                    "-filter_complex",
                    (
                        f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                        f"crop={WIDTH}:{HEIGHT},setsar=1[base];"
                        f"[base][1:v]overlay=0:0:format=auto[v]"
                    ),
                    "-map", "[v]",
                    "-an",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                    "-t", str(duration),
                    "-pix_fmt", "yuv420p",
                    "-threads", "2",
                    output_path
                ]
                subprocess.run(cmd, check=True, timeout=300)

        # 5. إرسال لـ Telegram
        result = send_to_telegram(output_path, caption)
        return jsonify({
            "success": True,
            "hook": hook,
            "duration": duration,
            "telegram": result
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)

# ── Endpoint القديم (نبقيه لعدم كسر n8n الحالي) ──────────────────────────────
@app.route("/create-video", methods=["POST"])
def create_video_endpoint():
    return jsonify({"error": "Deprecated. Use /create-football-video"}), 410

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "version": "3.0-youtube-tiktok",
        "endpoints": ["/create-football-video", "/health"]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
