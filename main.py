from flask import Flask, request, jsonify
import subprocess
import os
import requests
import tempfile
from PIL import Image, ImageDraw, ImageFont
import textwrap
import urllib.parse

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

def generate_voice_gtts(script, output_path):
    # Use Google Translate TTS (free, no API key needed)
    text = urllib.parse.quote(script[:200])
    url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={text}&tl=en&client=tw-ob"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers)
    with open(output_path, 'wb') as f:
        f.write(response.content)

def get_pexels_video(query="football soccer"):
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=portrait"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        if data.get("videos"):
            for video in data["videos"]:
                for file in video["video_files"]:
                    if file.get("quality") in ["hd", "sd"] and file.get("width", 9999) <= 1080:
                        return file["link"]
    except:
        pass
    return None

def create_text_image(home, away, date, script, output_path, width=1080, height=1920):
    img = Image.new('RGB', (width, height), color=(10, 10, 30))
    draw = ImageDraw.Draw(img)
    
    # Gradient background effect
    for i in range(height):
        r = int(10 + (i/height) * 20)
        g = int(10 + (i/height) * 10)
        b = int(30 + (i/height) * 40)
        draw.line([(0, i), (width, i)], fill=(r, g, b))
    
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 65)
        font_match = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 55)
        font_body = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 38)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    except:
        font_title = font_match = font_body = font_small = ImageFont.load_default()
    
    # Top banner
    draw.rectangle([(0, 0), (width, 130)], fill=(200, 160, 0))
    draw.text((width//2, 65), "🏆 WORLD CUP 2026", fill=(0, 0, 0), font=font_title, anchor="mm")
    
    # Match
    draw.text((width//2, 250), home, fill=(255, 255, 255), font=font_match, anchor="mm")
    draw.text((width//2, 330), "VS", fill=(200, 160, 0), font=font_title, anchor="mm")
    draw.text((width//2, 420), away, fill=(255, 255, 255), font=font_match, anchor="mm")
    
    # Date
    draw.text((width//2, 510), date, fill=(180, 180, 180), font=font_small, anchor="mm")
    
    # Divider
    draw.rectangle([(80, 550), (width-80, 555)], fill=(200, 160, 0))
    
    # Script text
    wrapped = textwrap.fill(script[:300], width=32)
    lines = wrapped.split('\n')
    y = 600
    for line in lines[:10]:
        draw.text((width//2, y), line, fill=(255, 255, 255), font=font_body, anchor="mm")
        y += 55
    
    # Bottom
    draw.rectangle([(0, height-120), (width, height)], fill=(200, 160, 0))
    draw.text((width//2, height-60), "#WorldCup2026 #FIFA #Football", fill=(0, 0, 0), font=font_small, anchor="mm")
    
    img.save(output_path)

def create_video(script, home, away, date, output_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Generate voice
        audio_path = os.path.join(tmpdir, "voice.mp3")
        generate_voice_gtts(script, audio_path)
        
        # 2. Create background image
        bg_image_path = os.path.join(tmpdir, "background.png")
        create_text_image(home, away, date, script, bg_image_path)
        
        # 3. Try to get Pexels video
        video_url = get_pexels_video(f"football soccer world cup")
        bg_video_path = os.path.join(tmpdir, "bg_video.mp4")
        has_video = False
        
        if video_url:
            try:
                r = requests.get(video_url, stream=True, timeout=30)
                with open(bg_video_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                has_video = True
            except:
                has_video = False
        
        # 4. Get audio duration
        try:
            result = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path
            ], capture_output=True, text=True, timeout=10)
            duration = float(result.stdout.strip())
        except:
            duration = 45
        
        # 5. Create video with FFmpeg
        if has_video:
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", bg_video_path,
                "-loop", "1", "-i", bg_image_path,
                "-i", audio_path,
                "-filter_complex",
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[bg];"
                "[bg][1:v]overlay=0:0:alpha=0.7[v]",
                "-map", "[v]", "-map", "2:a",
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", "-shortest",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", bg_image_path,
                "-i", audio_path,
                "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac",
                "-t", str(duration),
                "-vf", "scale=1080:1920",
                "-shortest",
                output_path
            ]
        
        subprocess.run(cmd, check=True, timeout=120)
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
        return jsonify({"error": "No data provided"}), 400
    
    script = data.get('script', '')
    home = data.get('home', 'Team A')
    away = data.get('away', 'Team B')
    date = data.get('date', '')
    caption = data.get('caption', '')
    
    if not script:
        return jsonify({"error": "No script provided"}), 400
    
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
    return jsonify({"status": "ok", "service": "video-factory"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
