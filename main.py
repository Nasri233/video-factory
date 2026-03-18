from flask import Flask, request, jsonify
import subprocess
import os
import requests
import tempfile
import random
import asyncio
import edge_tts
from PIL import Image, ImageDraw, ImageFont
import textwrap

app = Flask(__name__)

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PEXELS_API_KEY   = os.environ.get("PEXELS_API_KEY")

WIDTH  = 540
HEIGHT = 960

# ── Pexels: جلب مقاطع كرة حقيقية ──────────────────────────────────────────
FOOTBALL_QUERIES = [
    "football stadium crowd",
    "soccer match action",
    "football players running",
    "world cup stadium",
    "soccer ball kick",
    "football goal celebration",
]

def fetch_pexels_videos(query: str, count: int = 4) -> list[str]:
    """يجلب روابط مقاطع فيديو من Pexels ويرجع قائمة URLs."""
    headers = {"Authorization": PEXELS_API_KEY}
    params  = {"query": query, "per_page": count, "orientation": "portrait", "size": "medium"}
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=15)
        r.raise_for_status()
        videos = r.json().get("videos", [])
        urls = []
        for v in videos:
            # نختار أصغر ملف HD لتوفير الذاكرة
            files = sorted(v.get("video_files", []), key=lambda x: x.get("width", 9999))
            for f in files:
                if f.get("width", 0) <= 720 and f.get("link"):
                    urls.append(f["link"])
                    break
        return urls
    except Exception as e:
        print(f"Pexels error: {e}")
        return []

def download_video_clip(url: str, path: str) -> bool:
    try:
        r = requests.get(url, timeout=30, stream=True)
        with open(path, "wb") as f:
            for chunk in r.iter_content(32768):
                f.write(chunk)
        return os.path.getsize(path) > 10000
    except Exception as e:
        print(f"Download error: {e}")
        return False

# ── Edge-TTS: تعليق صوتي عربي ──────────────────────────────────────────────
async def _generate_arabic_voice(text: str, path: str):
    voice = "ar-SA-HamedNeural"   # صوت عربي ذكوري احترافي
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(path)

def generate_voice(script: str, output_path: str):
    # نظّف النص ويكون عربياً
    asyncio.run(_generate_arabic_voice(script, output_path))

# ── إنشاء overlay بسيط (شريط علوي + سفلي) ─────────────────────────────────
def create_overlay_image(home: str, away: str, date: str, output_path: str):
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font_big   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
        font_med   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except:
        font_big = font_med = font_small = ImageFont.load_default()

    # شريط علوي
    draw.rectangle([(0, 0), (WIDTH, 80)], fill=(200, 160, 0, 230))
    draw.text((WIDTH // 2, 40), "🏆 WORLD CUP 2026", fill=(0, 0, 0, 255), font=font_big, anchor="mm")

    # بطاقة المباراة في المنتصف
    draw.rectangle([(20, HEIGHT // 2 - 90), (WIDTH - 20, HEIGHT // 2 + 90)], fill=(0, 0, 20, 200))
    draw.rectangle([(20, HEIGHT // 2 - 90), (WIDTH - 20, HEIGHT // 2 + 90)], outline=(200, 160, 0, 255), width=2)
    draw.text((WIDTH // 2, HEIGHT // 2 - 55), home,  fill=(255, 255, 255, 255), font=font_med, anchor="mm")
    draw.text((WIDTH // 2, HEIGHT // 2),      "VS",  fill=(200, 160, 0, 255),   font=font_big, anchor="mm")
    draw.text((WIDTH // 2, HEIGHT // 2 + 55), away,  fill=(255, 255, 255, 255), font=font_med, anchor="mm")
    draw.text((WIDTH // 2, HEIGHT // 2 + 80), date,  fill=(180, 180, 180, 255), font=font_small, anchor="mm")

    # شريط سفلي
    draw.rectangle([(0, HEIGHT - 60), (WIDTH, HEIGHT)], fill=(200, 160, 0, 230))
    draw.text((WIDTH // 2, HEIGHT - 30), "#WorldCup2026  #FIFA  #Football",
              fill=(0, 0, 0, 255), font=font_small, anchor="mm")

    img.save(output_path)

# ── تجميع الفيديو النهائي ──────────────────────────────────────────────────
def build_final_video(clips: list[str], audio_path: str, overlay_path: str,
                      output_path: str, target_duration: float = 50.0):
    """
    1. يدمج مقاطع Pexels معاً (loop إذا قصيرة)
    2. يضيف overlay شفاف فوق الفيديو
    3. يضيف التعليق الصوتي
    """
    with tempfile.TemporaryDirectory() as tmp:

        # ── الخطوة 1: اقتصاص وتوحيد كل مقطع إلى 9:16 ──
        processed = []
        for i, clip in enumerate(clips[:5]):   # أقصى 5 مقاطع لتوفير RAM
            out = os.path.join(tmp, f"clip_{i}.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", clip,
                "-vf", (
                    f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
                    f"crop={WIDTH}:{HEIGHT},"
                    f"setsar=1"
                ),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
                "-an",                    # بدون صوت أصلي
                "-t", "12",               # أقصى 12 ثانية لكل مقطع
                "-threads", "1",
                out
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)
            if result.returncode == 0:
                processed.append(out)

        if not processed:
            raise RuntimeError("No clips processed")

        # ── الخطوة 2: دمج المقاطع في ملف واحد ──
        concat_list = os.path.join(tmp, "concat.txt")
        # كرر المقاطع حتى نصل للمدة المطلوبة
        repeated = []
        total = 0
        while total < target_duration:
            for p in processed:
                repeated.append(p)
                total += 12
                if total >= target_duration:
                    break

        with open(concat_list, "w") as f:
            for p in repeated:
                f.write(f"file '{p}'\n")

        merged = os.path.join(tmp, "merged.mp4")
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-c", "copy", "-t", str(target_duration),
            merged
        ], check=True, timeout=120)

        # ── الخطوة 3: إضافة overlay + صوت ──
        cmd_final = [
            "ffmpeg", "-y",
            "-i", merged,
            "-i", overlay_path,
            "-i", audio_path,
            "-filter_complex", (
                "[0:v][1:v]overlay=0:0:format=auto[v]"
            ),
            "-map", "[v]",
            "-map", "2:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "33",
            "-c:a", "aac", "-b:a", "96k",
            "-t", str(target_duration),
            "-pix_fmt", "yuv420p",
            "-threads", "1",
            "-shortest",
            output_path
        ]
        subprocess.run(cmd_final, check=True, timeout=180)

# ── فولباك: فيديو نصي إذا فشل Pexels ──────────────────────────────────────
def build_fallback_video(script: str, home: str, away: str, date: str,
                         audio_path: str, output_path: str):
    with tempfile.TemporaryDirectory() as tmp:
        bg = os.path.join(tmp, "bg.png")
        img = Image.new("RGB", (WIDTH, HEIGHT), (10, 10, 30))
        draw = ImageDraw.Draw(img)
        try:
            font_big   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
            font_med   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except:
            font_big = font_med = font_small = ImageFont.load_default()

        draw.rectangle([(0, 0), (WIDTH, 80)], fill=(200, 160, 0))
        draw.text((WIDTH // 2, 40), "WORLD CUP 2026", fill=(0, 0, 0), font=font_big, anchor="mm")
        draw.text((WIDTH // 2, 160), home, fill=(255, 255, 255), font=font_med, anchor="mm")
        draw.text((WIDTH // 2, 210), "VS",  fill=(200, 160, 0), font=font_big, anchor="mm")
        draw.text((WIDTH // 2, 260), away,  fill=(255, 255, 255), font=font_med, anchor="mm")
        draw.text((WIDTH // 2, 300), date,  fill=(180, 180, 180), font=font_small, anchor="mm")

        wrapped = textwrap.fill(script[:300], width=32)
        y = 350
        for line in wrapped.split("\n")[:10]:
            draw.text((WIDTH // 2, y), line, fill=(220, 220, 220), font=font_small, anchor="mm")
            y += 28

        draw.rectangle([(0, HEIGHT - 60), (WIDTH, HEIGHT)], fill=(200, 160, 0))
        draw.text((WIDTH // 2, HEIGHT - 30), "#WorldCup2026 #FIFA #Football",
                  fill=(0, 0, 0), font=font_small, anchor="mm")
        img.save(bg)

        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", bg,
            "-i", audio_path,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "35",
            "-c:a", "aac", "-b:a", "64k",
            "-t", "50", "-vf", f"scale={WIDTH}:{HEIGHT}",
            "-pix_fmt", "yuv420p", "-threads", "1", "-shortest",
            output_path
        ], check=True, timeout=180)

# ── إرسال لـ Telegram ──────────────────────────────────────────────────────
def send_to_telegram(video_path: str, caption: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, "rb") as f:
        r = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption[:1024],
            "parse_mode": "Markdown"
        }, files={"video": f}, timeout=90)
    return r.json()

# ── Endpoint رئيسي ─────────────────────────────────────────────────────────
@app.route("/create-video", methods=["POST"])
def create_video_endpoint():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400

    script  = data.get("script", "")
    home    = data.get("home", "Team A")
    away    = data.get("away", "Team B")
    date    = data.get("date", "")
    caption = data.get("caption", "")

    if not script:
        return jsonify({"error": "No script"}), 400

    output_path = tempfile.mktemp(suffix=".mp4")

    try:
        with tempfile.TemporaryDirectory() as tmp:

            # 1. توليد الصوت العربي
            audio_path = os.path.join(tmp, "voice.mp3")
            generate_voice(script, audio_path)

            # 2. حساب مدة الصوت
            try:
                res = subprocess.run([
                    "ffprobe", "-v", "error", "-show_entries",
                    "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                    audio_path
                ], capture_output=True, text=True, timeout=10)
                duration = min(float(res.stdout.strip()), 60.0)
            except:
                duration = 50.0

            # 3. جلب مقاطع Pexels
            query = random.choice(FOOTBALL_QUERIES)
            video_urls = fetch_pexels_videos(query, count=4)

            clip_paths = []
            if video_urls and PEXELS_API_KEY:
                for i, url in enumerate(video_urls[:4]):
                    cp = os.path.join(tmp, f"raw_{i}.mp4")
                    if download_video_clip(url, cp):
                        clip_paths.append(cp)

            if clip_paths:
                # 4a. فيديو بلقطات حقيقية
                overlay_path = os.path.join(tmp, "overlay.png")
                create_overlay_image(home, away, date, overlay_path)
                build_final_video(clip_paths, audio_path, overlay_path, output_path, duration)
            else:
                # 4b. فولباك نصي
                build_fallback_video(script, home, away, date, audio_path, output_path)

        # 5. إرسال لـ Telegram
        result = send_to_telegram(output_path, caption)
        return jsonify({"success": True, "mode": "pexels" if clip_paths else "fallback", "telegram": result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "2.0-pexels-arabic"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
