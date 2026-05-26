import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import telebot

# ==========================================
# 1. 기본 설정
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN이 필요합니다. GitHub Secrets에 BOT_TOKEN을 등록하세요.")

bot = telebot.TeleBot(BOT_TOKEN)

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "input_media"
TEMP_DIR = BASE_DIR / "temp"
OUTPUTS_DIR = BASE_DIR / "outputs"

for folder in [INPUT_DIR, TEMP_DIR, OUTPUTS_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
ALL_EXTS = IMAGE_EXTS | VIDEO_EXTS

# GitHub Actions CPU 환경에서는 2가 안정적입니다. 필요하면 Secrets/Variables에 MAX_WORKERS=3 등으로 조정하세요.
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "2"))
IMAGE_SECONDS = int(os.environ.get("IMAGE_SECONDS", "3"))
VIDEO_WIDTH = int(os.environ.get("VIDEO_WIDTH", "1080"))
VIDEO_HEIGHT = int(os.environ.get("VIDEO_HEIGHT", "1920"))
FPS = int(os.environ.get("FPS", "30"))


def run_cmd(cmd, label="ffmpeg"):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        print(f"❌ {label} 실패")
        print(result.stderr[-4000:])
        raise RuntimeError(result.stderr[-1500:])
    return result


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def collect_media_files():
    return [p for p in sorted(INPUT_DIR.iterdir()) if p.is_file() and p.suffix.lower() in ALL_EXTS]


def make_image_scene(src_path: Path, out_path: Path):
    """이미지 1장을 세로 쇼츠 규격 mp4로 변환합니다."""
    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={FPS},format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(IMAGE_SECONDS),
        "-i", str(src_path),
        "-f", "lavfi", "-t", str(IMAGE_SECONDS),
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(out_path),
    ]
    run_cmd(cmd, f"이미지 씬 생성: {src_path.name}")
    return out_path


def make_video_scene(src_path: Path, out_path: Path):
    """업로드된 영상을 세로 쇼츠 규격 mp4로 정규화합니다."""
    vf = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={FPS},format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
        "-c:a", "aac", "-b:a", "128k",
        "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        str(out_path),
    ]
    run_cmd(cmd, f"영상 씬 생성: {src_path.name}")
    return out_path


def render_one_media(index_and_path):
    idx, src_path = index_and_path
    out_path = TEMP_DIR / f"scene_{idx:03d}.mp4"
    ext = src_path.suffix.lower()

    if ext in IMAGE_EXTS:
        return make_image_scene(src_path, out_path)
    if ext in VIDEO_EXTS:
        return make_video_scene(src_path, out_path)
    return None


def merge_videos(video_paths, output_path: Path):
    if not video_paths:
        raise RuntimeError("병합할 영상이 없습니다.")

    list_file = TEMP_DIR / "list_vid.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for vp in sorted(video_paths):
            # concat demuxer 안정성을 위해 절대경로 사용
            f.write(f"file '{Path(vp).resolve().as_posix()}'\n")

    # 모든 씬을 동일 규격으로 만들었으므로 우선 copy 병합
    cmd_copy = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        run_cmd(cmd_copy, "최종 병합(copy)")
    except Exception:
        # 혹시 타임베이스/코덱 불일치가 있으면 재인코딩 병합으로 복구
        cmd_reencode = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        run_cmd(cmd_reencode, "최종 병합(re-encode)")

    return output_path


def main():
    # 이전 중간 결과 정리
    for p in TEMP_DIR.glob("scene_*.mp4"):
        p.unlink(missing_ok=True)

    media_files = collect_media_files()
    if not media_files:
        raise RuntimeError("input_media 폴더에 이미지/영상이 없습니다. 텔레그램으로 먼저 업로드하세요.")

    print(f"📥 입력 파일 {len(media_files)}개 감지")
    for p in media_files:
        print(f" - {p.name}")

    scene_videos = []
    indexed_files = list(enumerate(media_files, start=1))
    worker_count = max(1, min(MAX_WORKERS, len(indexed_files)))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(render_one_media, item) for item in indexed_files]
        for future in as_completed(futures):
            result = future.result()
            if result and Path(result).exists():
                scene_videos.append(Path(result))

    scene_videos = sorted(scene_videos)
    final_video = OUTPUTS_DIR / "Final_Video.mp4"
    merge_videos(scene_videos, final_video)
    return final_video


# ==========================================
# 2. 텔레그램 핸들러
# ==========================================
@bot.message_handler(commands=["start", "help"])
def handle_start(message):
    bot.reply_to(
        message,
        "✅ 텔레그램 영상 렌더러가 실행 중입니다.\n\n"
        "1) 사진/영상/파일을 여러 개 보내세요.\n"
        "2) 모두 보낸 뒤 /run 을 입력하세요.\n"
        "3) 초기화는 /clear, 상태확인은 /status 입니다.\n\n"
        "지원: jpg, png, webp, mp4, mov, m4v, avi, mkv, webm"
    )


@bot.message_handler(commands=["clear"])
def handle_clear(message):
    for folder in [INPUT_DIR, TEMP_DIR, OUTPUTS_DIR]:
        for p in folder.iterdir():
            if p.is_file():
                p.unlink(missing_ok=True)
    bot.reply_to(message, "🧹 입력/임시/결과 파일을 정리했습니다.")


@bot.message_handler(commands=["status"])
def handle_status(message):
    files = collect_media_files()
    if not files:
        bot.reply_to(message, "📦 현재 입력 파일: 0개")
        return
    file_list = "\n".join([f"- {p.name}" for p in files[:30]])
    more = "" if len(files) <= 30 else f"\n...외 {len(files) - 30}개"
    bot.reply_to(message, f"📦 현재 입력 파일: {len(files)}개\n{file_list}{more}")


def save_telegram_file(message, file_id, filename):
    ext = Path(filename).suffix.lower()
    if ext not in ALL_EXTS:
        bot.reply_to(message, f"⚠️ 지원하지 않는 파일 형식입니다: {ext}")
        return

    file_info = bot.get_file(file_id)
    count = len(collect_media_files()) + 1
    save_path = INPUT_DIR / f"{count:03d}_{safe_filename(filename)}"

    downloaded = bot.download_file(file_info.file_path)
    with open(save_path, "wb") as f:
        f.write(downloaded)

    bot.reply_to(message, f"✅ 파일 수신 완료 ({count}개): {save_path.name}")


@bot.message_handler(content_types=["photo"])
def handle_photo(message):
    save_telegram_file(message, message.photo[-1].file_id, f"photo_{int(time.time())}.jpg")


@bot.message_handler(content_types=["video"])
def handle_video(message):
    filename = getattr(message.video, "file_name", None) or f"video_{int(time.time())}.mp4"
    save_telegram_file(message, message.video.file_id, filename)


@bot.message_handler(content_types=["document"])
def handle_document(message):
    filename = message.document.file_name or f"document_{int(time.time())}"
    save_telegram_file(message, message.document.file_id, filename)


@bot.message_handler(commands=["run"])
def run_render(message):
    chat_id = message.chat.id
    bot.reply_to(message, "⚙️ 렌더링 시작... 이미지/영상 변환 후 최종 mp4로 합칩니다.")

    try:
        final_video = main()
        size_mb = final_video.stat().st_size / 1024 / 1024
        bot.send_message(chat_id, f"✅ 렌더링 완료: {final_video.name} ({size_mb:.1f}MB)")

        with open(final_video, "rb") as f:
            # 용량이 큰 경우 send_video보다 send_document가 안정적입니다.
            bot.send_document(chat_id, f, visible_file_name="Final_Video.mp4")

    except Exception as e:
        bot.send_message(chat_id, f"❌ 렌더링 실패:\n{str(e)[:3500]}")


if __name__ == "__main__":
    print("🤖 텔레그램-깃허브 영상 렌더러 실행 중...")
    print(f"INPUT_DIR={INPUT_DIR}")
    try:
        bot.remove_webhook()
    except Exception:
        pass
    bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
