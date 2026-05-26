import os
import subprocess
import time
import textwrap
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import google.generativeai as genai
import telebot
from PIL import Image

# ==========================================
# 1. 기본 설정
# ==========================================
BOT_TOKEN = (
    os.environ.get("INSTA_BOT_TOKEN")
    or os.environ.get("BOT_TOKEN")
    or os.environ.get("TELEGRAM_BOT_TOKEN")
    or os.environ.get("TELEGRAM_TOKEN")
)
if not BOT_TOKEN:
    raise RuntimeError(
        "Telegram Bot Token이 필요합니다. GitHub Secrets에 INSTA_BOT_TOKEN, BOT_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_TOKEN 중 하나를 등록하세요."
    )

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

MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "2"))
IMAGE_SECONDS = int(os.environ.get("IMAGE_SECONDS", "3"))
VIDEO_WIDTH = int(os.environ.get("VIDEO_WIDTH", "1080"))
VIDEO_HEIGHT = int(os.environ.get("VIDEO_HEIGHT", "1920"))
FPS = int(os.environ.get("FPS", "30"))
CAPTION_FONT_SIZE = int(os.environ.get("CAPTION_FONT_SIZE", "68"))
AUTO_CAPTION = os.environ.get("AUTO_CAPTION", "true").lower() in {"1", "true", "yes", "y"}
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_KEYS = [
    os.environ.get("GEMINI_API_KEY"),
    os.environ.get("GOOGLE_API_KEY"),
    os.environ.get("GEMINI_KEY_MAIN"),
    os.environ.get("GEMINI_KEY_SPARE"),
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_FILE = next((p for p in FONT_CANDIDATES if Path(p).exists()), FONT_CANDIDATES[-1])


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


def get_caption_path(src_path: Path) -> Path:
    return src_path.with_suffix(src_path.suffix + ".caption.txt")


def get_caption_text(src_path: Path) -> str:
    caption_path = get_caption_path(src_path)
    if caption_path.exists():
        return caption_path.read_text(encoding="utf-8").strip()
    return ""


def write_caption_file(src_path: Path, caption: str):
    caption = (caption or "").strip()
    if not caption:
        return
    caption = caption.replace("\r", " ").replace("\t", " ")
    wrapped = "\n".join(textwrap.wrap(caption, width=16))
    get_caption_path(src_path).write_text(wrapped, encoding="utf-8")


def extract_video_frame(video_path: Path) -> Path:
    frame_path = TEMP_DIR / f"frame_{video_path.stem}_{time.time_ns()}.jpg"
    cmd = [
        "ffmpeg", "-y",
        "-ss", "00:00:01",
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(frame_path),
    ]
    try:
        run_cmd(cmd, f"영상 대표 프레임 추출: {video_path.name}")
    except Exception:
        cmd = ["ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1", "-q:v", "2", str(frame_path)]
        run_cmd(cmd, f"영상 첫 프레임 추출: {video_path.name}")
    return frame_path


def clean_ai_caption(text: str) -> str:
    text = (text or "").strip()
    text = text.replace("```", "").replace('"', "").replace("'", "")
    lines = [line.strip(" -•\t") for line in text.splitlines() if line.strip()]
    text = " ".join(lines)
    if len(text) > 55:
        text = text[:55].rstrip() + "..."
    return text


def generate_ai_caption(src_path: Path) -> str:
    if not AUTO_CAPTION or not GEMINI_KEYS:
        return ""

    analysis_image = src_path
    if src_path.suffix.lower() in VIDEO_EXTS:
        analysis_image = extract_video_frame(src_path)

    prompt = (
        "너는 인스타 릴스/유튜브 쇼츠 자막 카피라이터야. "
        "이미지를 보고 영상 하단에 넣을 짧고 자연스러운 한국어 자막을 만들어줘. "
        "조건: 1문장, 최대 25자 내외, 따옴표/해시태그/이모지 없이, 설명문 말고 바로 자막 문구만 출력."
    )

    models = []
    for m in [GEMINI_MODEL, "gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-flash-latest"]:
        if m and m not in models:
            models.append(m)

    last_error = None
    for api_key in GEMINI_KEYS:
        for model_name in models:
            try:
                genai.configure(api_key=api_key)
                model = genai.GenerativeModel(model_name=model_name)
                with Image.open(analysis_image) as img:
                    response = model.generate_content([prompt, img])
                caption = clean_ai_caption(getattr(response, "text", ""))
                if caption:
                    print(f"✅ AI 자막 생성 성공({model_name}): {caption}")
                    return caption
            except Exception as e:
                last_error = e
                print(f"⚠️ AI 자막 생성 실패({model_name}): {e}")
                continue

    if last_error:
        print(f"⚠️ 모든 Gemini 자막 생성 실패: {last_error}")
    return ""


def build_video_filter(src_path: Path) -> str:
    base_filter = (
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={FPS},format=yuv420p"
    )
    caption_text = get_caption_text(src_path)
    if not caption_text:
        return base_filter

    caption_file = get_caption_path(src_path).resolve().as_posix()
    drawtext = (
        f"drawtext=fontfile='{FONT_FILE}':"
        f"textfile='{caption_file}':"
        f"fontcolor=white:fontsize={CAPTION_FONT_SIZE}:"
        f"borderw=7:bordercolor=black:"
        f"line_spacing=14:"
        f"x=(w-text_w)/2:y=h-text_h-230:"
        f"box=1:boxcolor=black@0.55:boxborderw=30"
    )
    return f"{base_filter},{drawtext}"


def make_image_scene(src_path: Path, out_path: Path):
    vf = build_video_filter(src_path)
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
    vf = build_video_filter(src_path)
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
            f.write(f"file '{Path(vp).resolve().as_posix()}'\n")

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


def ensure_ai_captions(media_files):
    report = []
    if not AUTO_CAPTION:
        return ["AI 자막: AUTO_CAPTION=false라서 건너뜀"]
    if not GEMINI_KEYS:
        return ["AI 자막: Gemini API Key 없음. GEMINI_KEY_MAIN 또는 GEMINI_API_KEY를 등록하세요."]

    for src_path in media_files:
        existing = get_caption_text(src_path)
        if existing:
            report.append(f"{src_path.name}: 기존 자막 사용 - {existing}")
            continue
        caption = generate_ai_caption(src_path)
        if caption:
            write_caption_file(src_path, caption)
            report.append(f"{src_path.name}: AI 자막 생성 - {caption}")
        else:
            fallback = "오늘의 순간"
            write_caption_file(src_path, fallback)
            report.append(f"{src_path.name}: AI 실패, 기본 자막 사용 - {fallback}")
    return report


def main():
    for p in TEMP_DIR.glob("scene_*.mp4"):
        p.unlink(missing_ok=True)

    media_files = collect_media_files()
    if not media_files:
        raise RuntimeError("input_media 폴더에 이미지/영상이 없습니다. 텔레그램으로 먼저 업로드하세요.")

    caption_report = ensure_ai_captions(media_files)

    print(f"📥 입력 파일 {len(media_files)}개 감지")
    for p in media_files:
        print(f" - {p.name}")
    for line in caption_report:
        print(f"📝 {line}")

    scene_videos = []
    indexed_files = list(enumerate(media_files, start=1))
    worker_count = max(1, min(MAX_WORKERS, len(indexed_files)))

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(render_one_media, item) for item in indexed_files]
        for future in as_completed(futures):
            result = future.result()
            if result and Path(result).exists():
                scene_videos.append(Path(result))

    final_video = OUTPUTS_DIR / "Final_Video.mp4"
    merge_videos(sorted(scene_videos), final_video)
    return final_video, caption_report, len(media_files), len(scene_videos)


@bot.message_handler(commands=["start", "help"])
def handle_start(message):
    bot.reply_to(
        message,
        "✅ 텔레그램 영상 렌더러가 실행 중입니다.\n\n"
        "1) 사진/영상/파일을 여러 개 보내세요.\n"
        "2) 캡션을 달면 그 문구가 자막으로 들어갑니다.\n"
        "3) 캡션이 없으면 Gemini가 사진/영상 대표 프레임을 보고 자막을 자동 생성합니다.\n"
        "4) 모두 보낸 뒤 /run 을 입력하세요.\n"
        "5) 초기화는 /clear, 상태확인은 /status 입니다.\n\n"
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
    lines = []
    for p in files[:30]:
        cap = get_caption_text(p)
        cap_mark = f" / 자막: {cap}" if cap else " / 자막 없음(AI 자동 생성 예정)"
        lines.append(f"- {p.name}{cap_mark}")
    more = "" if len(files) <= 30 else f"\n...외 {len(files) - 30}개"
    bot.reply_to(message, f"📦 현재 입력 파일: {len(files)}개\n" + "\n".join(lines) + more)


def save_telegram_file(message, file_id, filename):
    ext = Path(filename).suffix.lower()
    if ext not in ALL_EXTS:
        bot.reply_to(message, f"⚠️ 지원하지 않는 파일 형식입니다: {ext}")
        return

    file_info = bot.get_file(file_id)
    # 여러 장을 동시에 올릴 때 초 단위 파일명이 충돌해서 일부가 덮어써지는 문제 방지
    unique = f"{time.time_ns()}_{message.message_id}"
    save_path = INPUT_DIR / f"{unique}_{safe_filename(filename)}"
    downloaded = bot.download_file(file_info.file_path)
    with open(save_path, "wb") as f:
        f.write(downloaded)

    manual_caption = getattr(message, "caption", None)
    if manual_caption:
        write_caption_file(save_path, manual_caption)

    total = len(collect_media_files())
    cap_status = "수동 자막 저장" if manual_caption else "AI 자막 생성 예정"
    bot.reply_to(message, f"✅ 파일 수신 완료: {save_path.name}\n📦 현재 총 {total}개 / {cap_status}")


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
    bot.reply_to(message, "⚙️ 렌더링 시작... 누락 방지를 위해 업로드 파일 수와 자막 생성 결과를 같이 보고합니다.")
    try:
        final_video, caption_report, input_count, scene_count = main()
        size_mb = final_video.stat().st_size / 1024 / 1024
        report_text = "\n".join(caption_report[:12])
        if len(caption_report) > 12:
            report_text += f"\n...외 {len(caption_report) - 12}개"
        bot.send_message(
            chat_id,
            f"✅ 렌더링 완료: {final_video.name} ({size_mb:.1f}MB)\n"
            f"📦 입력 {input_count}개 / 생성 씬 {scene_count}개\n\n"
            f"📝 자막 결과\n{report_text}"
        )
        with open(final_video, "rb") as f:
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
