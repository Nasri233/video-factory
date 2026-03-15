from flask import Flask, request, jsonify
import subprocess
import os
import requests
import tempfile
from PIL import Image, ImageDraw, ImageFont
import textwrap
from gtts import gTTS

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

# Lower resolution to save RAM
WIDTH = 540
HEIGHT = 960

def generate_voice(script, output_path):
    tts = gTTS(text=script[:500], lang='en', tld='us', slow=False)
    tts.save(output_path)

def create_text_image(home, away, date, script, output_path):
    img = Image.new('RGB', (WIDTH, HEIGHT), color=(10, 10, 30))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
        font_match = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
        font_body  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 17)
    except:
        font_title = font_match = font_body = font_small = ImageFont.load_default()

    draw.rectangle([(0, 0), (WIDTH, 70)], fill=(200, 160, 0))
    draw.text((WIDTH//2, 35), "WORLD CUP 2026", fill=(0,0,0), font=font_title, anchor="mm")
    draw.text((WIDTH//2, 130), home, fill=(255,255,255), font=font_match, anchor="mm")
    draw.text((WIDTH//2, 175), "VS", fill=(200,160,0), font=font_title, anchor="mm")
    draw.text((WIDTH//2, 220), away, fill=(255,255,255), font=font_match, anchor="mm")
    draw.text((WIDTH//2, 265), date, fill=(180,180,180), font=font_small, anchor="mm")
    draw.rectangle([(40, 285), (WIDTH-40, 288)], fill=(200,160,0))

    wrapped = textwrap.fill(script[:250], width=35)
    y = 310
    for line in wrapped.split('\n')[:12]:
        draw.text((WIDTH//2, y), line, fill=(255,255,255), font=font_body, anchor="mm")
        y += 30

    draw.rectangle([(0, HEIGHT-60), (WIDTH, HEIGHT)], fill=(200,160,0))
    draw.text((WIDTH//2, HEIGHT-30), "#WorldCup2026 #FIFA #Football", fill=(0,0,0), font=font_small, anchor="mm")
    img.save(output_path)

def create_video(script, home, away, date, output_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "voice.mp3")
        generate_voice(script, audio_path)

        bg_path = os.path.join(tmpdir, "bg.png")
        create_text_image(home, away, date, script, bg_path)

        try:
            result = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ], capture_output=True, text=True, timeout=10)
            duration = float(result.stdout.strip())
        except:
            duration = 40

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", bg_path,
            "-i", audio_path,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "35",
            "-c:a", "aac",
            "-b:a", "64k",
            "-t", str(min(duration, 60)),
            "-vf", f"scale={WIDTH}:{HEIGHT}",
            "-pix_fmt", "yuv420p",
            "-threads", "1",
            "-shortest",
            output_path
        ]

        subprocess.run(cmd, check=True, timeout=180)
        return True

def send_to_telegram(video_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, 'rb') as f:
        response = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption[:1024],
            "parse_mode": "Markdown"
        }, files={"video": f}, timeout=60)
    return response.json()

@app.route('/create-video', methods=['POST'])
def create_video_endpoint():
    data = request.json
    if not data:
        return jsonify({"error": "No data"}), 400

    script  = data.get('script', '')
    home    = data.get('home', 'Team A')
    away    = data.get('away', 'Team B')
    date    = data.get('date', '')
    caption = data.get('caption', '')

    if not script:
        return jsonify({"error": "No script"}), 400

    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
        output_path = tmp.name

    try:
        create_video(script, home, away, date, output_path)
        result = send_to_telegram(output_path, caption)
        os.unlink(output_path)
        return jsonify({"success": True, "telegram": result})
    except Exception as e:
        if os.path.exists(output_path):
            os.unlink(output_path)
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
