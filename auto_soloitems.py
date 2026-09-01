import os
import re
import sys
import json
import time
import base64
import hmac
import hashlib
import datetime
import unicodedata
import requests
from urllib.parse import quote
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ==========================================
# 설정 — 자취템(soloitems) 쿠팡 상품 블로그 자동화
# 로컬 0817_blog_coupang_1.py의 파이프라인을 그대로 재사용하되,
# 텔레그램 버튼 선택 대신 "전일 미중복 + 랭킹 1순위 자동 채택"으로 완전자동화함.
# ==========================================
COUPANG_ACCESS_KEY = os.environ.get("COUPANG_ACCESS_KEY")
COUPANG_SECRET_KEY = os.environ.get("COUPANG_SECRET_KEY")
COUPANG_DOMAIN = "https://api-gateway.coupang.com"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
XAI_API_KEY = os.environ.get("XAI")

GOOGLE_OAUTH_TOKEN_STR = os.environ.get("SOLO_GOOGLE_TOKEN")  # [FIX] 5개 카테고리 블로그와 계정이 달라서 별도 시크릿 사용
SOLO_BLOG_ID = os.environ.get("SOLO_BLOG_ID")
SCOPES = ["https://www.googleapis.com/auth/blogger"]

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

TREND_KEYWORDS = [
    "원룸 가전", "미니 냉장고", "1인용 밥솥", "소형 세탁기", "원룸 수납",
    "휴대용 인덕션", "미니 건조기", "1인가구 전자레인지", "협탁 겸용 수납장",
    "원룸 커튼", "무선 청소기", "미니 전기밥솥", "접이식 테이블", "옷걸이 행거",
]


def send_telegram(text):
    if not (TELEGRAM_TOKEN and CHAT_ID):
        print(text)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 실패: {e}")


# ==========================================
# 1. 쿠팡 API
# ==========================================
def _coupang_signature(method, path, query=""):
    dt = datetime.datetime.now(datetime.timezone.utc).strftime("%y%m%d") + "T" + \
         datetime.datetime.now(datetime.timezone.utc).strftime("%H%M%S") + "Z"
    message = dt + method + path + query
    signature = hmac.new(COUPANG_SECRET_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, signed-date={dt}, signature={signature}"


def coupang_search_products(keyword, limit=5):
    path = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
    query = f"keyword={quote(keyword)}&limit={limit}"
    try:
        headers = {"Authorization": _coupang_signature("GET", path, query), "Content-Type": "application/json;charset=UTF-8"}
        res = requests.get(f"{COUPANG_DOMAIN}{path}?{query}", headers=headers, timeout=15)
        res.raise_for_status()
        return res.json().get("data", {}).get("productData", [])
    except Exception as e:
        print(f"⚠️ 쿠팡 상품 검색 실패({keyword}): {e}")
        return []


def scan_trending_products(top_n=8):
    import random
    candidates, seen_names = [], set()
    chosen_keywords = random.sample(TREND_KEYWORDS, k=min(3, len(TREND_KEYWORDS)))
    for kw in chosen_keywords:
        for p in coupang_search_products(kw, limit=5):
            name = p.get("productName", "")
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            candidates.append({
                "name": name, "price": p.get("productPrice", 0), "url": p.get("productUrl", ""),
                "image": p.get("productImage", ""), "category": kw, "rank": p.get("rank") or 999,
            })
    candidates.sort(key=lambda c: c["rank"])
    return candidates[:top_n]


# ==========================================
# 2. 전일 중복 체크 (main_autoposter.py와 동일한 방식)
# ==========================================
def _get_blogger_service():
    token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def get_recent_post_titles(blog_id, max_results=8):
    try:
        service = _get_blogger_service()
        posts = service.posts().list(blogId=blog_id, maxResults=max_results, fetchBodies=False).execute()
        return [p.get("title", "") for p in posts.get("items", [])]
    except Exception as e:
        print(f"⚠️ 최근 포스트 조회 실패(중복체크 건너뜀): {e}")
        return []


def _text_trigrams(text):
    t = re.sub(r"\s+", "", text or "")
    return {t[i:i + 3] for i in range(len(t) - 2)} or {t}


def is_recent_duplicate(name, recent_titles, threshold=0.35):
    if not name or not recent_titles:
        return False
    name_grams = _text_trigrams(name)
    for title in recent_titles:
        title_grams = _text_trigrams(title)
        if not name_grams or not title_grams:
            continue
        overlap = len(name_grams & title_grams) / max(1, len(name_grams | title_grams))
        if overlap >= threshold:
            return True
    return False


def pick_product_auto(candidates, recent_titles):
    for c in candidates:
        if not is_recent_duplicate(c["name"], recent_titles):
            return c
    return candidates[0] if candidates else None


# ==========================================
# 3. Gemini 블로그 대본 생성 (0817과 동일 프롬프트)
# ==========================================
BLOG_SYSTEM_PROMPT = """당신은 '자취템' 블로그(soloitems.blogspot.com)의 전문 카피라이터입니다.
타겟 독자는 1인가구/자취/원룸 생활을 하는 20~30대이며, 실용적인 정보와 솔직한 제품 추천을 원합니다.

[입력]
아래에 쿠팡 인기상품 정보(상품명, 가격, 카테고리)가 주어집니다. 이 상품을 자연스럽게 소개하는
블로그 글을 작성하되, 노골적인 광고 느낌이 아니라 "자취 생활 꿀팁/문제 해결" 관점에서 접근하세요.

[글 구조 - 반드시 이 순서]
1. intro: 자취/원룸 생활에서 흔한 불편함이나 고민을 공감가게 던지는 도입부 (100~150자)
2. problem: 그 문제를 조금 더 구체적으로 짚어주는 섹션 (150~200자)
3. solution: 해당 상품이 왜 이 문제의 해결책이 되는지 자연스럽게 소개 (200~250자, 상품명 자연스럽게 1~2회 언급)
4. tips: 실제 사용 팁이나 함께 쓰면 좋은 것들 (150~200자)
5. conclusion: 요약 + 담백한 마무리 (80~120자)

[SEO/GEO]
- seo_keywords: 이 글이 타겟할 검색 키워드 5개
- meta_description: 검색결과에 노출될 요약 (80자 내외)

[이미지 - 비용 절감을 위해 2x2 그리드 1장만 생성]
"grid_image_prompt" 필드에 아래 형식으로, 4칸 각각이 완전히 독립된 사진처럼 보이도록 구체적으로 작성하세요.
4칸이 하나로 이어지는 파노라마처럼 보이면 안 됩니다 (서로 다른 장소/구도/사물이어야 함).

형식: "A perfectly seamless 2x2 grid of 4 completely independent, unrelated photographs,
absolutely NO borders, NO white frames, NO margins between panels, each panel is a separate
photo with its own distinct location and subject. Top-left: [intro 섹션에 어울리는 구체적 장면],
Top-right: [problem 섹션에 어울리는 구체적 장면], Bottom-left: [solution 섹션 - 상품이 자연스럽게
놓인 장면], Bottom-right: [tips 섹션에 어울리는 구체적 장면]. Style: clean modern editorial
photography, soft natural lighting, cozy modern one-room apartment interior, minimal and
uncluttered composition, 100 percent photorealistic, contemporary 2020s interior and lifestyle,
no text, no logos, no visible brand names, no readable text of any kind in the image."

[캐릭터 통합 - 매우 중요, 별도 합성 없이 이미지 생성 시점에 같이 그림]
4칸 전부에 하나의 일관된 카툰 캐릭터가 그 실사 배경 속에 자연스럽게 녹아들어 등장해야 합니다
(배경만 있는 칸은 안 됩니다). grid_image_prompt 문장 안에 이 내용을 함께 녹여서 작성하세요:
- 캐릭터 스타일: 스튜디오 지브리(Ghibli) 애니메이션풍의 부드러운 셀 셰이딩, 따뜻하고 자연스러운
  색감의 페인터리 카툰이어야 합니다. 평면적인 흰색 단색 실루엣이나 두꺼운 검은 윤곽선의 심플
  라인아트는 절대 금지 — 배경의 조명/그림자와 어울리는 부드러운 채색과 음영이 있어야 합니다.
- 캐릭터가 반드시 전신으로 나올 필요는 없습니다. 손, 상반신, 뒷모습, 프레임 구석의 작은 인물 등
  장면에 자연스럽게 녹아드는 구도면 충분합니다.
- 각 칸(intro/problem/solution/tips)의 감정/상황에 어울리는 캐릭터의 반응(공감, 고민, 놀람,
  만족 등)을 표현하되, **실제 리뷰 상품(가전제품 자체)을 직접 가리키거나 안고 있거나 조작하는
  묘사는 절대 하지 마세요** — solution 칸에는 실제 상품 사진이 별도 카드로 삽입되므로, 그림 속
  캐릭터가 상품을 만지거나 들고 있으면 시각적으로 충돌합니다. 대신 빈 허공을 가리키거나 감탄하는
  표정만으로 표현하세요 (빨래더미, 양동이 같은 일반 소품은 괜찮음).
- 얼굴/헤어스타일/의상 등 캐릭터 디자인 자체는 4칸 내내 동일하게 유지하고, 포즈/표정/구도만
  칸마다 다르게 하세요.

[핵심 - 실제 상품 스펙]
[상품 정보]에 실제 스펙이 있으면 그대로 specs에 반영, 없으면 specs는 빈 배열 []로 (지어내지 말 것).

[핵심 - 형태 정확성 (이미지 할루시네이션 방지)]
이미지 생성 AI는 실제 상품 사진을 보지 못하고 이 프롬프트의 텍스트만 보고 그림을 그립니다.
그래서 "세탁기", "청소기"처럼 뭉뚱그려 쓰면 흔한 형태로 잘못 그리기 쉽습니다.
[상품 정보]에 "[형태 확인]" 섹션이 주어졌다면, 그 내용을 grid_image_prompt의 solution 패널
설명에 영어로 그대로(또는 매우 가깝게) 반영하고, 명시된 유사 형태는 "Do NOT draw ~" 식으로
명확히 배제하세요.

[출력 규칙]
특수문자(마크다운 강조기호 **, *, _, #) 쓰지 말 것. 순수 JSON만 출력.

{
  "title": "...", "meta_description": "...", "seo_keywords": ["...", "..."],
  "grid_image_prompt": "...", "specs": [{"label": "용량", "value": "4kg"}],
  "sections": [
    {"section_type": "intro", "heading": "...", "text": "..."},
    {"section_type": "problem", "heading": "...", "text": "..."},
    {"section_type": "solution", "heading": "...", "text": "..."},
    {"section_type": "tips", "heading": "...", "text": "..."},
    {"section_type": "conclusion", "heading": "...", "text": "..."}
  ]
}"""


def extract_pure_json(text):
    start = text.find("{")
    if start == -1:
        return None
    count = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            count += 1
        elif text[i] == "}":
            count -= 1
            if count == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None


def post_with_retry(url, payload, timeout=60, retries=3):
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            res = requests.post(url, json=payload, timeout=timeout)
            if res.status_code == 429:
                wait_s = 8 * attempt
                print(f"⚠️ Gemini 429, {wait_s}초 대기 후 재시도")
                time.sleep(wait_s)
                continue
            res.raise_for_status()
            return res
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if res.status_code >= 500:
                time.sleep(5 * attempt)
                continue
            raise
        except Exception as e:
            last_exc = e
            time.sleep(3)
    raise last_exc or RuntimeError("Gemini API 호출 실패")


def fetch_product_specs_via_search(product_name):
    if not GEMINI_API_KEY:
        return ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    prompt = (
        f"'{product_name}' 실제 판매 중인 상품의 정확한 스펙을 웹에서 검색해서 알려주세요.\n"
        "용량/사이즈/전력/무게/주요 기능 등 확인 가능한 항목만 4~6개, '항목명: 값' 형식으로 한 줄씩.\n"
        "확실하지 않은 항목은 빼세요. 목록만 출력하세요."
    )
    payload = {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}
    try:
        res = post_with_retry(url, payload, timeout=60)
        return res.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"⚠️ 스펙 검색 실패(스펙 없이 진행): {e}")
        return ""


# 🌟 이미지 생성 AI가 헷갈리기 쉬운 형태(하위 유형)를 상품명에서 미리 감지해서,
# "이 형태다 / 저 형태는 절대 아니다"를 명시적으로 프롬프트에 못박기 위한 사전.
SHAPE_HINT_KEYWORDS = {
    "통돌이": "This is a TOP-LOADING vertical washing machine — the lid opens from the TOP, "
              "drum is seen from above. Do NOT draw a front-loading drum washer with a round glass door.",
    "드럼": "This is a FRONT-LOADING drum washing machine with a round glass door on the front. "
            "Do NOT draw a top-loading vertical washer.",
    "벽걸이": "This unit is WALL-MOUNTED, fixed to the wall. Do NOT draw it as a freestanding "
              "floor unit.",
    "로봇청소기": "This is a low, flat, round disc-shaped ROBOT vacuum sitting on the floor. "
                "Do NOT draw an upright or stick vacuum being held by a person.",
    "스틱청소기": "This is an UPRIGHT STICK vacuum held by a person's hand while standing. "
                "Do NOT draw a round robot vacuum on the floor.",
    "무선": "This device is CORDLESS — no visible power cable connected to it.",
    "미니": "This is a COMPACT/SMALL-SIZED unit, notably smaller than standard full-size versions "
            "of this appliance type.",
}


def get_shape_hint(product_name):
    hints = [v for k, v in SHAPE_HINT_KEYWORDS.items() if k in (product_name or "")]
    return " ".join(hints)


def generate_blog_script(product, specs_text=""):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    product_info = f"상품명: {product['name']}\n가격: {product['price']}원\n카테고리: {product['category']}"
    if specs_text:
        product_info += f"\n\n[웹 검색으로 확인된 실제 스펙]\n{specs_text}"
    shape_hint = get_shape_hint(product.get("name", ""))
    if shape_hint:
        product_info += (
            f"\n\n[형태 확인 - grid_image_prompt의 solution 패널에 이 내용을 영어로 그대로 반영, "
            f"헷갈리는 유사 형태는 절대 그리지 않도록 명시]\n{shape_hint}"
        )
    full_prompt = f"{BLOG_SYSTEM_PROMPT}\n\n[상품 정보]\n{product_info}"
    payload = {
        "contents": [{"parts": [{"text": full_prompt}]}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.9, "maxOutputTokens": 8192},
    }
    try:
        res = post_with_retry(url, payload, timeout=120)
        text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
        json_data = extract_pure_json(text)
        if not json_data:
            return None, f"JSON 파싱 실패: {text[-300:]}"
        return json_data, None
    except Exception as e:
        return None, str(e)


def sanitize_text(text):
    if not text:
        return text
    normalized = unicodedata.normalize("NFC", text)
    cleaned = re.sub(r"[*_~`#‘’“”]+", "", normalized)
    return re.sub(r"\s+", " ", cleaned).strip()


def to_hashtag(keyword):
    if not keyword:
        return ""
    cleaned = re.sub(r"[^0-9A-Za-z가-힣]", "", re.sub(r"\s+", "", keyword))
    return f"#{cleaned}" if cleaned else ""


# ==========================================
# 4. 이미지 생성 (xAI) — base64 직접 임베딩 (외부 호스팅 미사용: 과거 이미지 미노출 문제 재발 방지)
# ==========================================
def generate_xai_image(prompt, save_path, aspect_ratio="16:9", resolution="2k"):
    if not XAI_API_KEY:
        return False
    for attempt in range(3):
        try:
            headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}
            payload = {"model": "grok-imagine-image", "prompt": prompt, "aspect_ratio": aspect_ratio,
                       "resolution": resolution, "n": 1}
            res = requests.post("https://api.x.ai/v1/images/generations", headers=headers, json=payload, timeout=60)
            if res.status_code == 200:
                img_data = requests.get(res.json()["data"][0]["url"]).content
                with open(save_path, "wb") as f:
                    f.write(img_data)
                return True
            print(f"⚠️ xAI 이미지 생성 실패(시도 {attempt+1}/3): HTTP {res.status_code}")
        except Exception as e:
            print(f"⚠️ xAI 이미지 생성 예외(시도 {attempt+1}/3): {e}")
        time.sleep(3)
    return False


def split_grid_2x2(image_path, job_id):
    from PIL import Image
    img = Image.open(image_path)
    w, h = img.size
    half_w, half_h = w // 2, h // 2
    margin = 8
    boxes = [
        (margin, margin, half_w - margin, half_h - margin),
        (half_w + margin, margin, w - margin, half_h - margin),
        (margin, half_h + margin, half_w - margin, h - margin),
        (half_w + margin, half_h + margin, w - margin, h - margin),
    ]
    out_paths = []
    for i, box in enumerate(boxes):
        cropped = img.crop(box).resize((720, 405), Image.Resampling.LANCZOS)
        out_path = f"./_grid_{job_id}_{i}.jpg"
        cropped.save(out_path, quality=82)
        out_paths.append(out_path)
    return out_paths


def image_file_to_data_uri(path):
    try:
        with open(path, "rb") as f:
            raw = f.read()
        return f"data:image/jpeg;base64,{base64.b64encode(raw).decode('utf-8')}"
    except Exception as e:
        print(f"⚠️ base64 인코딩 실패({path}): {e}")
        return None


# ==========================================
# 5. HTML 조립
# ==========================================
FTC_DISCLOSURE = (
    "<p style='font-size:13px;color:#888;'>"
    "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
    "</p>"
)


def build_json_ld(title, description, image_url):
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": title,
          "description": description, "image": image_url or "", "author": {"@type": "Organization", "name": "자취템"}}
    return f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'


def build_blog_html(script_data, section_images, product, deeplink):
    title = script_data.get("title", product["name"])
    desc = script_data.get("meta_description", "")
    sections = script_data.get("sections", [])

    parts = [FTC_DISCLOSURE, build_json_ld(title, desc, product.get("image", ""))]

    for i, sec in enumerate(sections):
        heading = sanitize_text(sec.get("heading", ""))
        text = sanitize_text(sec.get("text", ""))
        parts.append(f"<h3>{heading}</h3>")
        parts.append(f"<p>{text}</p>")
        if i < len(section_images) and section_images[i]:
            parts.append(f'<p><img src="{section_images[i]}" style="max-width:100%;height:auto;" /></p>')
        if sec.get("section_type") == "solution" and deeplink:
            price_str = f"{product['price']:,}원" if product.get("price") else ""
            product_img = product.get("image", "")
            img_html = (f'<img src="{product_img}" style="width:100%;display:block;object-fit:cover;max-height:320px;" />'
                        if product_img else "")
            specs = script_data.get("specs", [])
            specs_html = ""
            if specs:
                rows = "".join(
                    f"<tr><td style='padding:4px 10px 4px 0;color:#888;white-space:nowrap;'>{sanitize_text(s.get('label',''))}</td>"
                    f"<td style='padding:4px 0;color:#333;'>{sanitize_text(s.get('value',''))}</td></tr>"
                    for s in specs if s.get("label") and s.get("value")
                )
                if rows:
                    specs_html = f"<table style='font-size:14px;margin:8px 0 10px 0;border-collapse:collapse;'>{rows}</table>"
            parts.append(
                "<a href='" + deeplink + "' target='_blank' rel='nofollow noopener sponsored' style='text-decoration:none;color:inherit;'>"
                "<div style='border:1px solid #e5e5e5;border-radius:14px;overflow:hidden;margin:20px 0;max-width:520px;"
                "box-shadow:0 1px 4px rgba(0,0,0,0.06);'>"
                f"{img_html}<div style='padding:14px 16px;'>"
                f"<p style='font-weight:bold;font-size:16px;margin:0 0 6px 0;'>{product['name']}</p>"
                f"<p style='font-size:15px;color:#555;margin:0 0 4px 0;'>{price_str}</p>{specs_html}"
                "<p style='font-size:13px;color:#3182f6;margin:4px 0 0 0;'>쿠팡에서 확인하기 →</p></div></a>"
            )

    if deeplink:
        parts.append(
            "<p style='margin:26px 0 10px 0;text-align:center;'>"
            f"<a href='{deeplink}' target='_blank' rel='nofollow noopener sponsored' "
            "style='display:inline-block;background:#3182f6;color:#fff;padding:13px 22px;border-radius:8px;"
            f"text-decoration:none;font-weight:bold;font-size:15px;'>🛒 {product['name']} 최저가 확인하기</a></p>"
        )

    hashtags = " ".join(to_hashtag(k) for k in script_data.get("seo_keywords", []) if to_hashtag(k))
    if hashtags:
        parts.append(f"<p style='font-size:13px;color:#3182f6;'>{hashtags}</p>")

    return "\n".join(parts)


def upload_to_blogger(title, content_html):
    service = _get_blogger_service()
    post = service.posts().insert(blogId=SOLO_BLOG_ID, body={"title": title, "content": content_html}).execute()
    return post.get("url")


# ==========================================
# 메인
# ==========================================
def main():
    print("1) 최근 포스트 조회 중...")
    recent_titles = get_recent_post_titles(SOLO_BLOG_ID)
    print(f"   최근 제목 {len(recent_titles)}건 확보")

    print("2) 쿠팡 인기상품 스캔 중...")
    candidates = scan_trending_products(top_n=8)
    print(f"   후보 {len(candidates)}건")
    if not candidates:
        print("❌ 후보 없음")
        send_telegram("❌ [자취템] 쿠팡 인기상품을 가져오지 못했습니다.")
        return

    product = pick_product_auto(candidates, recent_titles)
    print(f"✅ 3) 선택된 상품: {product['name']}")

    print("4) 상품 스펙 검색 중...")
    specs_text = fetch_product_specs_via_search(product["name"])
    print(f"   스펙 텍스트 길이: {len(specs_text)}")

    print("5) Gemini 블로그 대본 생성 중...")
    script_data, err = generate_blog_script(product, specs_text)
    if err or not script_data:
        print(f"❌ 대본 생성 실패: {err}")
        send_telegram(f"❌ [자취템] 대본 생성 실패: {err}")
        return
    print(f"   제목: {script_data.get('title')}")

    job_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sections = script_data.get("sections", [])
    grid_prompt = script_data.get("grid_image_prompt", "")
    section_images = [None] * len(sections)

    grid_order = ["intro", "problem", "solution", "tips"]

    print("6) xAI 배경 그리드 이미지 생성 중...")
    crop_paths = None
    if grid_prompt:
        grid_path = f"./_bloggrid_{job_id}.jpg"
        if generate_xai_image(grid_prompt, grid_path, aspect_ratio="16:9"):
            print("   배경 이미지 생성 성공, 4분할 중...")
            crop_paths = split_grid_2x2(grid_path, job_id)
        else:
            print("⚠️ 배경 이미지 생성 실패, 이미지 없이 진행")
    else:
        print("⚠️ grid_image_prompt 없음")

    if crop_paths:
        # 캐릭터가 이미지 생성 시점에 배경과 같이 그려지므로, 별도 합성 없이 그대로 인코딩만 한다.
        crop_urls = [image_file_to_data_uri(fp) for fp in crop_paths]
        for i, sec in enumerate(sections):
            if sec.get("section_type") in grid_order:
                section_images[i] = crop_urls[grid_order.index(sec.get("section_type"))]

    deeplink = product.get("url", "")
    content_html = build_blog_html(script_data, section_images, product, deeplink)
    title = script_data.get("title", product["name"])
    print(f"7) HTML 조립 완료 (길이 {len(content_html)})")

    print("8) 블로거 발행 중...")
    try:
        link = upload_to_blogger(title, content_html)
        print(f"✅ 발행 완료: {link}")
        send_telegram(f"✅ [자취템] 자동 발행 완료!\n📦 상품: {product['name']}\n📝 {title}\n👉 {link}")
    except Exception as e:
        print(f"❌ 발행 실패: {e}")
        send_telegram(f"❌ [자취템] 발행 실패: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise
