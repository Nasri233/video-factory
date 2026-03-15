from flask import Flask, request, jsonify
import subprocess
import os
import requests
import tempfile
import edge_tts
import asyncio
from PIL import Image, ImageDraw, ImageFont
import textwrap

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

async def generate_voice(script, output_path):
    communicate = edge_tts.Communicate(script, voice="en-US-GuyNeural", rate="+10%")
    await communicate.save(output_path)

def get_pexels_video(query="football soccer world cup"):
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation=portrait"
    response = requests.get(url, headers=headers)
    data = response.json()
    
    if data.get("videos"):
        for video in data["videos"]:
            for file in video["video_files"]:
                if file.get("quality") in ["hd", "sd"] and file.get("width", 0) <= 1080:
                    return file["link"]
    return None

def create_text_overlay(text, output_path, width=1080, height=1920):
    img = Image.new('RGBA', (width, height), (0, 0, 0, 180))
    draw = ImageDraw.Draw(img)
    
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 55)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40)
    except:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
    
    # Title
    draw.text((width//2, 150), "🏆 WORLD CUP 2026", fill=(255, 215, 0), font=font_large, anchor="mm")
    
    # Script text wrapped
    wrapped = textwrap.fill(text, width=30)
    lines = wrapped.split('\n')
    y = 400
    for line in lines:
        draw.text((width//2, y), line, fill=(255, 255, 255), font=font_small, anchor="mm")
        y += 60
    
    # Bottom hashtags
    draw.text((width//2, height-150), "#WorldCup2026 #FIFA #Football", fill=(255, 215, 0), font=font_small, anchor="mm")
    
    img.save(output_path)

def create_video(script, home, away, date, output_path):
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. Generate voice
        audio_path = os.path.join(tmpdir, "voice.mp3")
        asyncio.run(generate_voice(script, audio_path))
        
        # 2. Get background video from Pexels
        video_url = get_pexels_video(f"{home} {away} football soccer")
        bg_path = os.path.join(tmpdir, "background.mp4")
        
        if video_url:
            r = requests.get(video_url, stream=True)
            with open(bg_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        # 3. Create text overlay image
        overlay_path = os.path.join(tmpdir, "overlay.png")
        create_text_overlay(f"{home} vs {away}\n{date}\n\n{script[:200]}...", overlay_path)
        
        # 4. Get audio duration
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ], capture_output=True, text=True)
        duration = float(result.stdout.strip()) if result.stdout.strip() else 45
        
        # 5. Combine with FFmpeg
        if video_url and os.path.exists(bg_path):
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", bg_path,
                "-i", audio_path,
                "-i", overlay_path,
                "-filter_complex",
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg];"
                "[bg][2:v]overlay=0:0[v]",
                "-map", "[v]", "-map", "1:a",
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-shortest",
                output_path
            ]
        else:
            # Fallback: image + audio
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1", "-i", overlay_path,
                "-i", audio_path,
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac",
                "-t", str(duration),
                "-vf", "scale=1080:1920",
                output_path
            ]
        
        subprocess.run(cmd, check=True)
        return True

def send_to_telegram(video_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    with open(video_path, 'rb') as f:
        response = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "Markdown"
        }, files={"video": f})
    return response.json()

@app.route('/create-video', methods=['POST'])
def create_video_endpoint():
    data = request.json
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
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
