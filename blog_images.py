# -*- coding: utf-8 -*-
"""[v8] 블로그 이미지 — 2026-09-28.

예전 방식의 문제(실측):
  - 2x2 콜라주 한 장을 잘라 600px 조각 4장으로 쓰고, base64 문자열로 본문에 통째로 넣었다
    → 글 하나가 수백 KB로 무거워지고, 구글 이미지 검색에 잡히지 않고, 화질도 낮았다.
  - '여행 가방 옆 사람' 같은 장식용 삽화라 정보 가치가 없었다.
새 방식:
  1) 대표 카드(맨 위): 제목 + 핵심 3줄을 직접 그린 정보 카드. 검색 결과·공유 썸네일로도 쓰인다.
     AI 이미지 모델은 글자가 깨지므로 Pillow로 그린다.
  2) 본문 사진(중간 1장): 주제와 직접 관련된 실사 장면 한 장을 16:9 고해상도로 생성.
  3) 두 파일 모두 이 공개 저장소에 커밋하고 jsDelivr CDN 주소(커밋 해시 고정)로 연결한다.
     실패하면 base64로 대체해 발행 자체는 막지 않는다.
"""
import os
import re
import io
import json
import base64
import hashlib
import datetime
import subprocess

import requests
from PIL import Image, ImageDraw, ImageFont

REPO = "jinaplus-svg/ai-stock-bot"
IMG_DIR = "blog_images"
W, H = 1200, 675

THEME = {  # (배경 위, 배경 아래, 강조색)
    "travel": ((15, 118, 110), (19, 78, 74), (94, 234, 212)),
    "stock": ((30, 58, 138), (15, 23, 42), (147, 197, 253)),
    "food": ((194, 65, 12), (124, 45, 18), (253, 186, 116)),
    "it": ((91, 33, 182), (46, 16, 101), (196, 181, 253)),
    "news": ((51, 65, 85), (15, 23, 42), (203, 213, 225)),
}
BLOG_NAME = {"travel": "떠나기 전 여행 노트", "stock": "차근차근 투자 공부 노트",
             "food": "음식·요리 노트", "it": "IT·디지털 노트", "news": "생활정보 노트"}

_FONT_CANDIDATES = {
    "bold": ["/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
             "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
             "C:/Windows/Fonts/malgunbd.ttf"],
    "regular": ["/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
                "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                "C:/Windows/Fonts/malgun.ttf"],
}


def _font(kind, size):
    for p in _FONT_CANDIDATES[kind]:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise RuntimeError("한글 폰트 없음 — 워크플로우에서 fonts-nanum 설치 필요")


def _wrap(draw, text, font, max_w, max_lines):
    """한글은 단어 단위 줄바꿈이 어색할 때가 많아 공백 기준으로 먼저 자르고, 넘치면 글자 단위로 자른다."""
    lines, cur = [], ""
    for word in text.split(" "):
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = word
        while draw.textlength(cur, font=font) > max_w:
            cut = len(cur)
            while cut > 1 and draw.textlength(cur[:cut], font=font) > max_w:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def make_title_card(category, title, points, out_path):
    top, bottom, accent = THEME.get(category, THEME["news"])
    img = Image.new("RGB", (W, H), top)
    px = img.load()
    for y in range(H):  # 세로 그라데이션
        t = y / (H - 1)
        c = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        for x in range(W):
            px[x, y] = c
    d = ImageDraw.Draw(img)

    pad = 64
    d.rounded_rectangle((pad, 48, pad + 14, 88), radius=4, fill=accent)
    d.text((pad + 30, 50), BLOG_NAME.get(category, ""), font=_font("regular", 30), fill=(255, 255, 255))

    for size in (60, 54, 48):  # 제목이 2줄 안에 잘리지 않고 들어가는 가장 큰 크기
        f_title = _font("bold", size)
        if not _wrap(d, title, f_title, W - pad * 2, 2)[-1].endswith("…"):
            break
    f_pt = _font("regular", 34)
    num_f = _font("bold", 26)
    title_lines = _wrap(d, title, f_title, W - pad * 2, 2)
    pts = points[:3]
    box_h, gap, line_h = 84, 12, int(f_title.size * 1.3)
    block = len(title_lines) * line_h + 36 + len(pts) * (box_h + gap)
    y = 108 + max(0, (H - 108 - 64 - block) // 2)  # 블로그명 아래~날짜 위 사이에서 세로 가운데
    for line in title_lines:
        d.text((pad, y), line, font=f_title, fill=(255, 255, 255))
        y += line_h
    y += 36
    for i, p in enumerate(pts):
        d.rounded_rectangle((pad, y, W - pad, y + box_h), radius=16, fill=(255, 255, 255))
        cy = y + box_h // 2
        d.ellipse((pad + 22, cy - 22, pad + 66, cy + 22), fill=top)
        num = str(i + 1)
        d.text((pad + 44 - d.textlength(num, font=num_f) / 2, cy - 15), num, font=num_f, fill=(255, 255, 255))
        text = _wrap(d, p, f_pt, W - pad * 2 - 120, 1)[0]
        d.text((pad + 88, cy - 20), text, font=f_pt, fill=(30, 41, 59))
        y += box_h + gap

    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime("%Y.%m.%d 기준 정리")
    f_small = _font("regular", 24)
    d.text((W - pad - d.textlength(stamp, font=f_small), H - 44), stamp, font=f_small, fill=(226, 232, 240))
    img.save(out_path, "PNG", optimize=True)
    return out_path


def generate_scene_photo(xai_client, gemini_text, category, title, out_path):
    """주제와 직접 관련된 실사 장면 한 장(16:9). 글자·로고·클로즈업 얼굴 없이."""
    prompt = gemini_text(
        None,
        f"블로그 글 제목: {title}\n이 글의 본문 중간에 넣을 사진 한 장의 영어 이미지 프롬프트를 2문장으로 써줘. 조건: "
        "주제를 한눈에 보여주는 구체적인 실제 장면(장소·사물·상황), 사실적인 사진, 자연광, 사람은 멀리 작게 또는 뒷모습만, "
        "글자·간판·로고·숫자 없음. 프롬프트만 답해.",
        temperature=0.6, max_output_tokens=600,
    )
    final = (f"{prompt.strip()} Photorealistic editorial photograph, 35mm, natural light, high detail. "
             "ABSOLUTELY NO TEXT, NO LETTERS, NO LOGOS, NO SIGNS, NO NUMBERS.")
    res = xai_client.images.generate(model="grok-imagine-image", prompt=final,
                                     extra_body={"aspect_ratio": "16:9", "resolution": "2k"}, n=1)
    img = Image.open(io.BytesIO(requests.get(res.data[0].url, timeout=60).content)).convert("RGB")
    if img.width > 1400:
        img = img.resize((1400, int(img.height * 1400 / img.width)), Image.Resampling.LANCZOS)
    img.save(out_path, "JPEG", quality=84, optimize=True, progressive=True)
    return out_path


def card_points(gemini_text, title, summary_text):
    """대표 카드용 핵심 3줄(각 22자 이내)."""
    raw = gemini_text(
        None,
        f"제목: {title}\n요약: {summary_text[:600]}\n\n이 글의 핵심을 카드에 넣을 짧은 문장 3개로 줄여줘. "
        "각 22자 이내, 명사형 또는 짧은 서술. JSON 배열로만: [\"..\",\"..\",\"..\"]",
        temperature=0.3, max_output_tokens=600,
    )
    try:
        pts = json.loads(re.search(r"\[.*\]", raw, re.DOTALL).group(0))
        return [str(p).strip() for p in pts if str(p).strip()][:3]
    except Exception:
        return []


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=120)


def publish_files(paths, category):
    """저장소에 커밋·푸시하고 jsDelivr 주소를 돌려준다. 실패 시 None(호출부에서 base64 대체)."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return None
    day = datetime.datetime.utcnow().strftime("%Y/%m")
    rels = []
    for p in paths:
        digest = hashlib.sha1(open(p, "rb").read()).hexdigest()[:12]
        rel = f"{IMG_DIR}/{category}/{day}/{digest}{os.path.splitext(p)[1]}"
        os.makedirs(os.path.dirname(rel), exist_ok=True)
        os.replace(p, rel)
        rels.append(rel)
    _git("config", "user.name", "content-schedule-bot")
    _git("config", "user.email", "content-schedule-bot@users.noreply.github.com")
    _git("add", *rels)
    if _git("commit", "-m", f"blog images ({category}) [skip ci]").returncode != 0:
        return None
    for _ in range(3):
        if _git("push").returncode == 0:
            sha = _git("rev-parse", "HEAD").stdout.strip()
            return [f"https://cdn.jsdelivr.net/gh/{REPO}@{sha}/{r}" for r in rels]
        _git("pull", "--rebase")
    return None


def to_data_uri(path):
    mime = "image/png" if path.endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(open(path, 'rb').read()).decode()}"
