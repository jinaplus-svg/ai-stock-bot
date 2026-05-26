import os
import sys
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import requests
import telebot
from mutagen.mp3 import MP3

# ==========================================
# 1. 환경 변수/API 키
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
GEMINI_KEY_MAIN = os.environ.get("GEMINI_KEY_MAIN", "")
GEMINI_KEY_SPARE = os.environ.get("GEMINI_KEY_SPARE", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN이 필요합니다.")

bot = telebot.TeleBot(BOT_TOKEN)

INPUT_DIR = "./input_media"
TEMP_DIR = "./temp"
OUTPUTS_DIR = "./outputs"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# ==========================================
# 2. 이미지 처리
# ==========================================
def split_grid_2x2(image_path, output_dir, group_id):
    img = Image.open(image_path)
    w, h = img.size
    half_w, half_h = w // 2, h // 2
    margin = 8
    boxes = [
        (margin, margin, half_w - margin, half_h - margin),
        (half_w + margin, margin, w - margin, half_h - margin),
        (margin, half_h + margin, half_w - margin, h - margin),
        (half_w + margin, half_h + margin, w - margin, h - margin)
    ]
    saved_paths = []
    for i, box in enumerate(boxes):
        cropped = img.crop(box).resize((1920, 1080), Image.Resampling.LANCZOS)
        out_path = os.path.join(output_dir, f"img_g{group_id}_s{i + 1}.jpg")
        cropped.save(out_path, quality=85)
        saved_paths.append(out_path)
    return saved_paths

def generate_xai_image(prompt, aspect_ratio, save_path, resolution="1080p"):
    if not XAI_API_KEY:
        print("⚠️ XAI_API_KEY 없음")
        return False
    try:
        headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "grok-imagine-image", "prompt": prompt, "aspect_ratio": aspect_ratio, "resolution": resolution, "n": 1}
        res = requests.post("https://api.x.ai/v1/images/generations", headers=headers, json=payload, timeout=60)
        if res.status_code == 200:
            url = res.json()['data'][0]['url']
            img_data = requests.get(url).content
            with open(save_path, 'wb') as f:
                f.write(img_data)
            return save_path
    except Exception as e:
        print(f"❌ xAI 이미지 생성 실패: {e}")
    return False

# ==========================================
# 3. 씬 영상 생성
# ==========================================
def create_scene_video(image_path, audio_path, scene_idx, output_dir, bgm_path=None):
    output_path = os.path.join(output_dir, f"scene_{scene_idx:03d}.mp4")
    ffmpeg_cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', image_path,
        '-i', audio_path,
        '-c:v', 'libx264', '-tune', 'stillimage',
        '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p',
        '-shortest',
        '-threads', str(os.cpu_count()),
        output_path
    ]
    subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path

def render_all_scenes(scene_list, outputs_dir):
    scene_videos = []
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count())) as executor:
        futures = [executor.submit(create_scene_video, scene['image'], scene['audio'], idx, outputs_dir)
                   for idx, scene in enumerate(scene_list)]
        for f in as_completed(futures):
            scene_videos.append(f.result())
    return scene_videos

def merge_videos(video_paths, output_path):
    list_file = os.path.join(TEMP_DIR, "list_vid.txt")
    with open(list_file, 'w', encoding='utf-8') as f:
        for vp in video_paths:
            f.write(f"file '{os.path.basename(vp)}'\n")
    subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_file,
                    '-c', 'copy', '-movflags', '+faststart', output_path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path

# ==========================================
# 4. 메인 실행
# ==========================================
def main():
    scenes = []
    for idx, img_file in enumerate(sorted(os.listdir(INPUT_DIR))):
        if img_file.lower().endswith(('.jpg', '.png')):
            audio_file = img_file.rsplit('.',1)[0]+'.mp3'
            audio_path = os.path.join(INPUT_DIR, audio_file)
            if not os.path.exists(audio_path):
                # 더미 3초 silent mp3
                audio_path = os.path.join(TEMP_DIR, f"silent_{idx}.mp3")
                subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=2', '-t', '3', audio_path])
            scenes.append({'image': os.path.join(INPUT_DIR,img_file), 'audio': audio_path})
    
    scene_videos = render_all_scenes(scenes, OUTPUTS_DIR)
    final_video = os.path.join(OUTPUTS_DIR, "Final_Video.mp4")
    merge_videos(scene_videos, final_video)
    return final_video

# ==========================================
# 5. 텔레그램 핸들러
# ==========================================
@bot.message_handler(content_types=['photo','video'])
def handle_media(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.photo[-1].file_id if message.photo else message.video.file_id)
    ext = '.jpg' if message.photo else '.mp4'
    save_path = os.path.join(INPUT_DIR, f"{file_info.file_id}{ext}")
    with open(save_path, 'wb') as f:
        f.write(bot.download_file(file_info.file_path))
    bot.reply_to(message, f"✅ 파일 수신 완료: {save_path}")

@bot.message_handler(commands=['run'])
def run_render(message):
    chat_id = message.chat.id
    bot.reply_to(message, "⚙️ 렌더링 시작...")
    final_video = main()
    bot.send_document(chat_id, open(final_video, 'rb'))

# ==========================================
# 6. 실행
# ==========================================
if __name__ == "__main__":
    print("🤖 텔레그램-깃허브 영상 렌더러 실행 중...")
    bot.infinity_polling()
