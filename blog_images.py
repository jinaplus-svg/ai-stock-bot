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
        print(f"⚠️ 카드 요약 파싱 실패: {raw[:120]!r}")
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


# ------------------------------------------------------------------
# [v9] 데이터 도표 — 글 본문에 실제로 나온 숫자만으로 그린다(없으면 만들지 않음)
# ------------------------------------------------------------------
def extract_chart_spec(gemini_text, title, body_text):
    """본문에 나온 수치 중 비교·비중을 한눈에 보여줄 만한 것 하나를 도표 사양(JSON)으로 뽑는다."""
    raw = gemini_text(
        None,
        f"글 제목: {title}\n본문:\n{body_text[:6000]}\n\n"
        "이 본문에 '직접 적힌 숫자'만 사용해서, 독자가 한눈에 이해하기 좋은 도표 1개를 설계해줘.\n"
        "- 비중(합이 100%인 구성)이면 pie, 항목 간 크기 비교면 bar\n"
        "- 항목 2~6개, 값은 본문에 적힌 숫자 그대로(계산·추정·반올림 금지)\n"
        "- 본문에 그런 숫자 묶음이 없으면 type을 none으로\n"
        'JSON으로만: {"type":"pie|bar|none","title":"도표 제목(20자 이내)","labels":["..."],"values":[숫자],"unit":"%|원|만원|시간|배 등"}',
        temperature=0.1, max_output_tokens=800,
    )
    try:
        spec = json.loads(re.search(r"\{.*\}", raw, re.DOTALL).group(0))
    except Exception:
        return None
    if spec.get("type") not in ("pie", "bar"):
        return None
    labels, values = spec.get("labels") or [], spec.get("values") or []
    if not (2 <= len(labels) == len(values) <= 6):
        return None
    try:
        values = [float(v) for v in values]
    except Exception:
        return None
    # 🚨 지어낸 숫자 방지: 모든 값이 본문에 그대로 적혀 있어야 한다
    flat = body_text.replace(",", "")
    for v in values:
        s = str(int(v)) if v == int(v) else str(v)
        if s not in flat:
            print(f"⚠️ 도표 값 {s}이(가) 본문에 없어 도표를 만들지 않음")
            return None
    if spec["type"] == "pie" and not (95 <= sum(values) <= 105):
        spec["type"] = "bar"
    spec["values"] = values
    return spec


def render_chart(spec, category, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for p in _FONT_CANDIDATES["regular"]:
        if os.path.exists(p):
            font_manager.fontManager.addfont(p)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=p).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False
    top, bottom, accent = THEME.get(category, THEME["news"])
    base = tuple(c / 255 for c in top)
    palette = [base, tuple(c / 255 for c in accent), (0.58, 0.64, 0.72), (0.99, 0.73, 0.45),
               (0.53, 0.81, 0.62), (0.80, 0.60, 0.85)]
    labels, values, unit = spec["labels"], spec["values"], spec.get("unit", "")

    height = 5.6 if spec["type"] == "pie" else 1.6 + 0.75 * len(values)  # 막대 수에 맞춰 높이 조절
    fig, ax = plt.subplots(figsize=(10, height), dpi=120)
    fig.patch.set_facecolor("white")
    if spec["type"] == "pie":
        wedges, _t, autot = ax.pie(values, colors=palette[:len(values)], startangle=90, counterclock=False,
                                   autopct=lambda p: f"{p:.0f}%", pctdistance=0.72,
                                   wedgeprops={"width": 0.48, "edgecolor": "white", "linewidth": 2})
        for t in autot:
            t.set_color("white"); t.set_fontsize(15); t.set_fontweight("bold")
        ax.legend(wedges, [f"{l}  {v:g}{unit}" for l, v in zip(labels, values)], loc="center left",
                  bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=14)
        ax.set_aspect("equal")
    else:
        y = range(len(labels))[::-1]
        bars = ax.barh(list(y), values, color=[palette[0]] * len(values), height=0.55)
        ax.set_yticks(list(y)); ax.set_yticklabels(labels, fontsize=14)
        for b, v in zip(bars, values):
            ax.text(b.get_width(), b.get_y() + b.get_height() / 2, f"  {v:g}{unit}", va="center", fontsize=14,
                    color="#1e293b", fontweight="bold")
        ax.set_xlim(0, max(values) * 1.25)
        for s in ("top", "right", "bottom"):
            ax.spines[s].set_visible(False)
        ax.set_xticks([])
    ax.set_title(spec.get("title", ""), fontsize=19, fontweight="bold", color="#0f172a", loc="left", pad=16)
    fig.text(0.99, 0.02, "본문 수치로 그린 도표", ha="right", fontsize=10, color="#94a3b8")
    fig.tight_layout()
    fig.savefig(out_path, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out_path


# ------------------------------------------------------------------
# [v10] 여행 코스 동선도 — 본문에 순서대로 적힌 장소만으로 그린다(없으면 만들지 않음)
# ------------------------------------------------------------------
def extract_route_spec(gemini_text, title, body_text):
    raw = gemini_text(
        None,
        f"글 제목: {title}\n본문:\n{body_text[:6000]}\n\n"
        "이 본문이 '방문 순서가 있는 여행 코스/일정'을 소개하고 있으면, 본문에 적힌 장소명을 순서대로 뽑아줘.\n"
        "- 일자(또는 코스)별 최대 4개 구간, 구간마다 장소 2~5개\n"
        "- 장소명은 본문 표기 그대로(새로 만들거나 바꾸지 말 것), 12자 이내로 짧게\n"
        "- 이동수단·소요시간이 본문에 있으면 move에 짧게(예: '버스 20분'), 없으면 빈 문자열\n"
        "- 코스가 아닌 글(보험·준비물·제도 설명 등)이면 days를 빈 배열로\n"
        'JSON으로만: {"title":"도표 제목(20자 이내)","days":[{"label":"1일차","stops":["장소"],"move":""}]}',
        temperature=0.1, max_output_tokens=1000,
    )
    try:
        spec = json.loads(re.search(r"\{.*\}", raw, re.DOTALL).group(0))
    except Exception:
        return None
    days = [d for d in (spec.get("days") or []) if len(d.get("stops") or []) >= 2][:4]
    if not days:
        return None
    flat = body_text.replace(" ", "")
    for d in days:
        d["stops"] = [str(s).strip() for s in d["stops"]][:5]
        for s in d["stops"]:
            if s.replace(" ", "") not in flat:  # 🚨 본문에 없는 장소는 그리지 않는다
                print(f"⚠️ 동선도 장소 '{s}'가 본문에 없어 동선도를 만들지 않음")
                return None
    spec["days"] = days
    return spec


def render_route(spec, category, out_path):
    top, bottom, accent = THEME.get(category, THEME["travel"])
    days = spec["days"]
    row_h, head_h = 150, 120
    h = head_h + row_h * len(days) + 50
    img = Image.new("RGB", (W, h), (248, 250, 252))
    d = ImageDraw.Draw(img)
    pad = 56
    d.text((pad, 42), spec.get("title") or "코스 한눈에 보기", font=_font("bold", 40), fill=(15, 23, 42))
    d.line((pad, 104, W - pad, 104), fill=(226, 232, 240), width=2)

    f_label, f_stop, f_move = _font("bold", 26), _font("regular", 26), _font("regular", 20)
    label_w = 130
    for r, day in enumerate(days):
        y = head_h + r * row_h + 20
        cy = y + 44
        d.rounded_rectangle((pad, cy - 26, pad + label_w - 16, cy + 26), radius=26, fill=top)
        lb = str(day.get("label", f"{r + 1}구간"))[:6]
        d.text((pad + (label_w - 16 - d.textlength(lb, font=f_label)) / 2, cy - 16), lb, font=f_label, fill=(255, 255, 255))

        stops = day["stops"]
        area_x0, area_x1 = pad + label_w + 10, W - pad
        n = len(stops)
        gap = 44
        box_w = (area_x1 - area_x0 - gap * (n - 1)) / n
        for i, s in enumerate(stops):
            x0 = area_x0 + i * (box_w + gap)
            d.rounded_rectangle((x0, cy - 38, x0 + box_w, cy + 38), radius=14, fill=(255, 255, 255),
                                outline=top, width=3)
            fs = f_stop  # 긴 장소명은 두 줄로(필요하면 글자 크기를 줄여서) 모두 보이게
            lines = _wrap(d, s, fs, box_w - 16, 2)
            if lines[-1].endswith("…"):
                fs = _font("regular", 21)
                lines = _wrap(d, s, fs, box_w - 12, 2)
            lh = fs.size + 4
            ty = cy - (lh * len(lines)) / 2 - 2
            for ln in lines:
                d.text((x0 + (box_w - d.textlength(ln, font=fs)) / 2, ty), ln, font=fs, fill=(30, 41, 59))
                ty += lh
            if i < n - 1:  # 화살표
                ax0, ax1 = x0 + box_w + 8, x0 + box_w + gap - 8
                d.line((ax0, cy, ax1, cy), fill=accent if sum(accent) < 600 else top, width=4)
                d.polygon([(ax1, cy), (ax1 - 10, cy - 8), (ax1 - 10, cy + 8)], fill=top)
        mv = str(day.get("move") or "").strip()
        if mv:
            d.text((area_x0, cy + 46), f"이동: {mv[:40]}", font=f_move, fill=(100, 116, 139))
    note = "본문에 소개된 순서대로 정리"
    d.text((W - pad - d.textlength(note, font=f_move), h - 40), note, font=f_move, fill=(148, 163, 184))
    img.save(out_path, "PNG", optimize=True)
    return out_path
