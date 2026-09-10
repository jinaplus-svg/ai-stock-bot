import os
import json
import argparse
import base64
import requests
import datetime
import re
import html
import hmac
import hashlib
import random
from urllib.parse import quote
from io import BytesIO
from PIL import Image
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from bs4 import BeautifulSoup

# ==========================================
# 1. 설정 및 API 키 로드
# ==========================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
XAI_API_KEY = os.environ.get("XAI")
GOOGLE_OAUTH_TOKEN_STR = os.environ.get("GOOGLE_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")

COUPANG_ACCESS_KEY = os.environ.get("COUPANG_ACCESS_KEY")
COUPANG_SECRET_KEY = os.environ.get("COUPANG_SECRET_KEY")
COUPANG_DOMAIN = "https://api-gateway.coupang.com"

BLOG_REGISTRY = {
    "it": os.environ.get("IT_BLOG_ID"),
    "food": os.environ.get("FOOD_BLOG_ID"),
    "news": os.environ.get("NEWS_BLOG_ID"),
    "stock": os.environ.get("STOCK_BLOG_ID"),
    "travel": os.environ.get("TRAVEL_BLOG_ID")
}

gpt_client = OpenAI(api_key=OPENAI_API_KEY)
xai_client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
SCOPES = ['https://www.googleapis.com/auth/blogger']

def send_telegram(text):
    if not (TELEGRAM_TOKEN and CHAT_ID):
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(f"⚠️ 텔레그램 알림 실패: {e}")


# ==========================================
# 2. 이중 방어 쌍끌이 뉴스 검색 엔진 (최신성 강제)
# ==========================================
def fetch_reference_content(url):
    if not url: return "", "", ""
    if "youtube.com" in url or "youtu.be" in url:
        try:
            video_id = url.split("/")[-1].split("?")[0] if "youtu.be" in url else re.search(r"v=([a-zA-Z0-9_-]+)", url).group(1)
            # [FIX] youtube-transcript-api 1.x부터 get_transcript() 클래스메서드가 제거됨 -> 인스턴스 fetch()로 교체
            transcript_list = YouTubeTranscriptApi().fetch(video_id, languages=['ko', 'en']).to_raw_data()
            transcript_text = " ".join([item['text'] for item in transcript_list])
            return f"[유튜브 스크립트]:\n{transcript_text[:4000]}", "유튜브 분석", url
        except:
            return "자막 추출 실패", "유튜브", url

    if TAVILY_API_KEY:
        try:
            payload = {"api_key": TAVILY_API_KEY, "query": url, "search_depth": "advanced", "include_raw_content": True}
            res = requests.post("https://api.tavily.com/search", json=payload, timeout=20)
            if res.status_code == 200:
                data = res.json()
                if data.get("results"):
                    content = data["results"][0].get("raw_content") or data["results"][0].get("content")
                    return content[:4000], data["results"][0].get("title", "참고 기사"), url
        except Exception as e:
            print(f"URL 추출 에러: {e}")
    return "", "", url


def fetch_youtube_trending_topic(category):
    """[NEW] 카테고리 관련 유튜브 인기 영상을 검색해서 자막 기반 소재를 뽑는다 (뉴스 검색과 이중화)."""
    if not YOUTUBE_API_KEY:
        return "", "", ""
    queries = {
        "news": "오늘 사회 이슈", "it": "IT 신기술 리뷰", "stock": "오늘 주식 시황 분석",
        "food": "맛집 먹방 리뷰", "travel": "국내 여행 브이로그"
    }
    query = queries.get(category, "오늘 이슈")
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        published_after = (datetime.datetime.utcnow() - datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        res = youtube.search().list(
            part="snippet", q=query, type="video", order="viewCount",
            publishedAfter=published_after, regionCode="KR", relevanceLanguage="ko", maxResults=5
        ).execute()
        for item in res.get("items", []):
            video_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            try:
                # [FIX] youtube-transcript-api 1.x 인스턴스 fetch() API로 교체 (get_transcript()는 제거됨)
                transcript = YouTubeTranscriptApi().fetch(video_id, languages=["ko", "en"]).to_raw_data()
                text = " ".join(t["text"] for t in transcript)[:4000]
            except Exception:
                text = item["snippet"].get("description", "")[:2000]
            if len(text) > 200:
                url = f"https://www.youtube.com/watch?v={video_id}"
                print(f"✅ [YouTube] 인기영상 소재 확보: {title}")
                return f"[유튜브 인기영상 스크립트]:\n{text}", title, url
    except Exception as e:
        print(f"⚠️ 유튜브 트렌드 검색 에러: {e}")
    return "", "", ""


def _text_trigrams(text):
    t = re.sub(r"\s+", "", text or "")
    return {t[i:i + 3] for i in range(len(t) - 2)} or {t}


def is_recent_duplicate(topic, recent_titles, threshold=0.35):
    """[NEW] 오늘 후보 주제가 최근 발행 제목들과 얼마나 겹치는지 문자 3-gram 자카드 유사도로 체크."""
    if not topic or not recent_titles:
        return False
    topic_grams = _text_trigrams(topic)
    for title in recent_titles:
        title_grams = _text_trigrams(title)
        if not topic_grams or not title_grams:
            continue
        overlap = len(topic_grams & title_grams) / max(1, len(topic_grams | title_grams))
        if overlap >= threshold:
            print(f"⚠️ 중복 의심 (유사도 {overlap:.2f}): '{topic}' ≈ '{title}'")
            return True
    return False


# 🚨 [v2 개선] 리뷰에서 확인된 문제 — 제목만 3-gram 유사도로 비교하면, GPT가 같은 원문 기사를
# 매번 다른 문구의 제목으로 써서 통과시켜버림(실제로 9/5, 9/6 글이 같은 원문 URL을 쓰고도
# 통과됨). 원문 URL 자체를 기록해서, 같은 기사를 소재로 다시 뽑지 않도록 직접 차단한다.
SOURCE_URL_HISTORY_FILE = "used_source_urls.json"


def _load_source_url_history():
    if not os.path.exists(SOURCE_URL_HISTORY_FILE):
        return {}
    try:
        with open(SOURCE_URL_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_source_url_history(history):
    for cat in history:
        history[cat] = history[cat][-30:]
    with open(SOURCE_URL_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def mark_source_url_used(category, url):
    if not url:
        return
    history = _load_source_url_history()
    history.setdefault(category, [])
    if url not in history[category]:
        history[category].append(url)
    _save_source_url_history(history)


def generate_auto_topic(category, recent_titles=None):
    print(f"🤖 [{category.upper()}] 최근 48시간 이내 최신 기사 팩트 수집 중...")
    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")
    recent_titles = recent_titles or []

    candidates = []  # (ref_content, title, url) 후보들을 모아서 중복 아닌 것부터 채택

    if TAVILY_API_KEY:
        try:
            search_queries = {
                "news": "한국 주요 정치 사회 속보 최신 뉴스",
                "it": "IT 테크 신기술 스마트폰 속보 최신 뉴스",
                "stock": "주식 증시 경제 특징주 시황 속보",
                "food": "한국 외식 식품 트렌드 최신 뉴스",
                "travel": "국내외 여행 관광 항공 최신 뉴스"
            }
            query = search_queries.get(category, "오늘 주요 속보")

            payload = {
                "api_key": TAVILY_API_KEY,
                "query": f"{today_str} {query}",
                "search_depth": "advanced",
                "include_raw_content": True,
                "max_results": 3,
                "topic": "news",
                "days": 2
            }
            res = requests.post("https://api.tavily.com/search", json=payload, timeout=15)
            if res.status_code == 200:
                for result in res.json().get('results', []):
                    title = result.get('title', '제목 없음')
                    content = result.get('raw_content') or result.get('content', '')
                    if len(content) > 200:
                        candidates.append((f"[Tavily 추출 원문]:\n{content[:4000]}", title, result.get('url', '')))
        except Exception as e:
            print(f"⚠️ Tavily 검색 에러: {e}")

    # [NEW] 유튜브 인기영상도 후보로 이중화
    yt_content, yt_title, yt_url = fetch_youtube_trending_topic(category)
    if yt_content:
        candidates.append((yt_content, yt_title, yt_url))

    used_urls = set(_load_source_url_history().get(category, []))
    candidates = [c for c in candidates if c[2] not in used_urls]  # 같은 원문 URL은 아예 후보에서 제외

    for content, title, url in candidates:
        if not is_recent_duplicate(title, recent_titles):
            print(f"✅ 채택된 소재: {title}")
            return content, title, url
    if candidates:
        # 전부 중복 의심이면, 그래도 완전히 막지는 않고 첫 후보로 진행 (로그로만 경고)
        print("⚠️ 모든 후보가 최근 발행분과 유사함 — 그래도 진행합니다.")
        return candidates[0]

    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        print("⚠️ Tavily/유튜브 검색 실패. 네이버 API(백업)로 최신 속보를 검색합니다.")
        try:
            queries = {"news": "사회 최신 속보", "it": "IT 신기술 최신 속보", "stock": "증시 특징주 최신 속보", "food": "외식 트렌드 최신 뉴스", "travel": "여행 관광 최신 뉴스"}
            headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
            params = {"query": queries.get(category, "최신 속보"), "display": 3, "sort": "date"}
            res = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                for item in res.json().get('items', []):
                    title = html.unescape(re.sub(r'<[^>]+>', '', item['title']))
                    desc = html.unescape(re.sub(r'<[^>]+>', '', item['description']))
                    link = item.get('originallink') or item['link']
                    if len(desc) > 30 and not is_recent_duplicate(title, recent_titles):
                        print(f"✅ [Naver] 백업 최신 팩트 확보: {title}")
                        return f"[네이버 최신 기사 요약]:\n{desc}\n\n이 기사를 바탕으로 깊이 있게 상상하여 전문가의 시각을 더해 아주 길게 작성하세요.", title, link
        except Exception as e:
            print(f"⚠️ 네이버 검색 에러: {e}")

    return "", "", ""

# ==========================================
# 3. AI 이미지 생성 및 글 작성
# ==========================================
# 🌟 [v3] 만화 캐릭터가 실사 배경에 섞여있는 스타일이 뉴스/IT/증시처럼 진지한 시사 카테고리에는
# 안 어울린다는 피드백(리뷰로 확인) — 이 카테고리들은 캐릭터 없이 순수 보도사진 스타일로,
# food/travel(라이프스타일 성격)만 기존처럼 캐릭터를 유지한다.
CHARACTER_CATEGORIES = {"food", "travel"}


def create_photo_prompt(category, topic, ref_content):
    """
    [v2] 예전엔 배경(실사)과 마스코트(초록배경 카툰)를 따로 생성해서 크로마키로 합성했음 —
    두 이미지의 화풍/조명이 안 맞아 캐릭터가 배경 위에 "붙여넣은 스티커"처럼 붕 떠 보이는
    문제가 있었음. 이제 한 번의 이미지 생성으로 실사 배경과 캐릭터를 같이 그려서, 이미지
    모델이 처음부터 조명/그림자/구도를 통일감 있게 맞추도록 한다 (합성 단계 자체가 필요 없음).
    [v3] news/it/stock은 캐릭터 없이 순수 보도사진 스타일로 분기.
    """
    use_character = category in CHARACTER_CATEGORIES

    character_rule = f"""
    🎨 [캐릭터 통합 규칙 - 매우 중요]
    4개 컷 전부에, 하나의 일관된 카툰 캐릭터가 그 실사 배경 속에 자연스럽게 녹아들어 등장해야 합니다
    (배경만 있는 컷은 안 됩니다).
    - 캐릭터 스타일: 스튜디오 지브리(Ghibli) 애니메이션풍의 부드러운 셀 셰이딩, 따뜻하고 자연스러운 색감의
      페인터리 카툰. 평면적인 흰색 단색 실루엣이나 두꺼운 검은 윤곽선의 심플 라인아트는 절대 금지 —
      배경의 조명/그림자와 어울리는 부드러운 채색과 음영이 있어야 합니다.
    - 캐릭터가 반드시 전신으로 나올 필요는 없습니다. 손, 상반신, 뒷모습, 프레임 한쪽 구석의 작은 인물 등
      장면에 자연스럽게 녹아드는 구도면 충분합니다.
    - 각 컷마다 그 상황의 감정/맥락에 맞는 반응(놀람, 진지함, 분석적 시선, 자신감 등)을 표현하되,
      실제 특정 인물이나 로고/제품을 직접 가리키거나 조작하는 모습은 그리지 마세요.
    - 얼굴/헤어스타일/의상 등 캐릭터 디자인 자체는 4컷 내내 동일하게 유지하고, 포즈/표정/구도만 컷마다 다르게 하세요.
    """ if use_character else """
    🎨 [인물/캐릭터 규칙 - 매우 중요]
    이 카테고리는 진지한 시사/분석 톤이라 만화 캐릭터를 넣지 않습니다. 4개 컷 모두 사람이 전혀
    등장하지 않는 순수 다큐멘터리 사진(사물, 공간, 데이터를 시각화한 추상적 장면 등)이거나,
    등장하더라도 100% 포토리얼리스틱한 실사 인물(카툰/일러스트 아님)만 배치하세요.
    """

    system_msg = f"""
    당신은 퓰리처상을 받은 보도사진 편집장{"이자 스튜디오 지브리풍 일러스트 감독" if use_character else ""}입니다.
    제공된 기사의 핵심 맥락(Context)을 깊이 이해하고, 이슈의 본질을 보여주는 상징적이고 생동감 넘치는 4분할 컷(4-panel photo collage) 영문 프롬프트를 작성하세요.

    🚨 [절대 금지 사항 - CRITICAL]
    - 현존 AI 기술 한계상 이미지 내 텍스트는 무조건 깨집니다. 따라서 ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO TYPOGRAPHY, NO LOGOS, NO SIGNS!
    - 영어든 한글이든 글자는 단 1개도 들어가선 안 됩니다. 글자가 필요한 간판이나 화면 대신 제품/사물의 형태, 상황의 분위기에만 집중하세요.
    - 각 컷의 배경/현장 자체는 3D CG나 일러스트가 아닌, 8k 극사실주의 보도사진(Photorealistic, documentary photography) 스타일로 묘사할 것.
    {character_rule}
    """
    res = gpt_client.chat.completions.create(
        model="gpt-4o",  # Mini에서 고성능 모델로 업그레이드 (맥락 파악 강화)
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"주제: {topic}\n내용: {ref_content}"}],
        temperature=0.7
    )
    return res.choices[0].message.content.strip()


def generate_and_split_images_xai(prompt, out_dir=".", use_character=True):
    """이미지 생성 시점에 배경(실사)+캐릭터(지브리풍 카툰)를 한 번에 같이 그려서, 별도 합성 없이
    바로 완성 이미지로 씀 (경로 리스트를 반환). [v3] use_character=False면 캐릭터 없이 순수 사진."""
    if use_character:
        final_prompt = (
            f"A seamless photo collage of 4 panels in a 2x2 grid. Each panel is a photorealistic, "
            f"documentary-style real-world scene, with ONE consistent Ghibli-style painterly cartoon "
            f"character naturally blended into that same photorealistic scene (soft cel-shading, warm "
            f"natural colors matching the scene's lighting — not a flat white silhouette or thick black "
            f"outline). The character does not need to be full-body. {prompt} "
            f"Highly realistic environment, cinematic lighting, ABSOLUTELY NO TEXT, NO WORDS, NO LOGOS, "
            f"NO LETTERS, no signs, no typography, clean visual only."
        )
    else:
        final_prompt = (
            f"A seamless photo collage of 4 panels in a 2x2 grid. Each panel is a photorealistic, "
            f"documentary-style news photograph — no cartoon or illustrated elements anywhere, no "
            f"mascot character. If people appear, they must be fully photorealistic real humans. {prompt} "
            f"Highly realistic environment, cinematic lighting, ABSOLUTELY NO TEXT, NO WORDS, NO LOGOS, "
            f"NO LETTERS, no signs, no typography, clean visual only."
        )
    try:
        response = xai_client.images.generate(
            model="grok-imagine-image",
            prompt=final_prompt,
            extra_body={"aspect_ratio": "1:1", "resolution": "2k"},
            n=1
        )
        img = Image.open(BytesIO(requests.get(response.data[0].url).content))
        w, h = img.size
        cw, ch = w // 2, h // 2
        margin = 15
        job_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_paths = []
        for r in range(2):
            for c in range(2):
                l, t = c * cw + margin, r * ch + margin
                ri, b = l + cw - (margin * 2), t + ch - (margin * 2)
                cropped = img.crop((l, t, ri, b)).resize((600, 600), Image.Resampling.LANCZOS)
                if cropped.mode in ('RGBA', 'P'): cropped = cropped.convert('RGB')
                out_path = os.path.join(out_dir, f"_bgcrop_{job_id}_{len(out_paths)}.jpg")
                cropped.save(out_path, quality=88)
                out_paths.append(out_path)
        return out_paths
    except Exception as e:
        print(f"⚠️ 배경 이미지 생성 실패: {e}")
        return []


def image_paths_to_b64(paths):
    """이미지 생성 시점에 배경+캐릭터를 이미 같이 그렸으므로, 합성 없이 그대로 base64 인코딩만 한다."""
    out = []
    for path in paths:
        with open(path, "rb") as f:
            out.append(f"data:image/jpeg;base64,{base64.b64encode(f.read()).decode()}")
    return out



# 🚨 [v2 개선] 카테고리별로 완전히 다른 구조 필요 — 예전엔 뉴스/IT/증시/맛집/여행 전부 똑같은
# "칼럼니스트 심층분석" 틀을 썼는데, 리뷰 결과 맛집 글에도 "경쟁사 비교/산업 파급력 예측" 같은
# 안 어울리는 구조가 반복되고, 원문에 없는 수치/조건이 "전문가 통찰"이란 명목으로 만들어지는
# 문제가 확인됨(예: 원문 "일부 상품에 포함" → 블로그 "포함"으로 조건 소실). 카테고리를 정보형
# (food/travel — 독자가 바로 쓸 정보가 목적)과 분석형(news/it/stock — 시사 해설이 목적)으로
# 나눠서 각각 다른 글 구조를 쓴다.
INFO_CATEGORIES = {"food", "travel"}

CATEGORY_STRUCTURE = {
    "food": """
    <h2>매장명 + 핵심 키워드가 결합된 제목</h2>
    (이 매장/음식이 왜 화제인지, 원문에 나온 사실 기반으로 2문단)
    <br><br>
    [IMAGE_1]
    <br><br>
    (메뉴 구성과 가격 — 원문에 나온 실제 메뉴명/가격만 기재. 없으면 "가격 미확인, 매장에 문의 필요"라고 쓸 것)
    <br><br>
    <table {table_style}>
      <thead><tr><th {th_style}>확인 항목</th><th {th_style}>내용</th></tr></thead>
      <tbody><tr><td {td_style}>위치/영업시간</td><td {td_style}>원문에 있으면 기재, 없으면 미확인 표시</td></tr>
      <tr><td {td_style}>예약 필요 여부</td><td {td_style}>원문 기준</td></tr></tbody>
    </table>
    <br><br>
    [IMAGE_2]
    <br><br>
    (이 매장을 고려할 때 확인해야 할 점 — 원문에 없는 맛 평가나 방문 경험은 절대 쓰지 말 것)
    <br><br>
    <blockquote {blockquote_style}>정보 요약 한 줄</blockquote>
    """,
    "travel": """
    <h2>장소/행사명 + 핵심 키워드가 결합된 제목</h2>
    (이 여행지/행사가 누구에게 맞는지, 원문 기반 2문단)
    <br><br>
    [IMAGE_1]
    <br><br>
    (일정·교통·비용 — 원문에 나온 날짜/요금/조건만 기재. "일부 상품에 한정" 같은 원문의 조건과
    예외는 절대 생략하거나 일반화하지 말고 그대로 반영할 것)
    <br><br>
    <table {table_style}>
      <thead><tr><th {th_style}>확인 항목</th><th {th_style}>내용</th></tr></thead>
      <tbody><tr><td {td_style}>예약 방법/링크</td><td {td_style}>원문 기준, 없으면 미확인 표시</td></tr>
      <tr><td {td_style}>참여 조건</td><td {td_style}>원문의 예외·제한사항 그대로</td></tr></tbody>
    </table>
    <br><br>
    [IMAGE_2]
    <br><br>
    (독자가 예약/방문 전 실제로 확인해야 할 사항)
    <br><br>
    <blockquote {blockquote_style}>정보 요약 한 줄</blockquote>
    """,
    "_default": """
    <h2>핵심 키워드 + 후킹 장치가 결합된 제목</h2>
    (독자가 겪는 상황/숫자로 3초 안에 몰입시키는 도입부 2~3문단, 문단당 3~4문장 — 앞서 정한
    "핵심 인사이트 한 가지"를 여기서부터 향해 가도록 시작할 것)
    <br><br>
    [IMAGE_1]
    <br><br>
    (원문에 있는 사실과 수치만 기반으로 한 구체적 설명 2~3문단, 문단당 3~4문장 — 원문에 없는
    수치나 조건은 절대 만들지 말 것. 도입부와 같은 사실을 표현만 바꿔 반복하지 말 것)
    <br><br>
    (선택 — 본문에 없는 추가 수치/비교 데이터가 원문에 있을 때만 아래 표를 넣고, 없으면 표 자체와
    이 문단을 통째로 생략:
    <table {table_style}>
      <thead><tr><th {th_style}>핵심 지표 / 비교 항목</th><th {th_style}>수치(출처: 원문) 및 해설</th></tr></thead>
      <tbody><tr><td {td_style}>원문에 있는 데이터만 기입 — 본문 문장 재활용 금지</td><td {td_style}>해설 — 원문 사실과 칼럼니스트 해석을 문장으로 구분</td></tr></tbody>
    </table>
    )
    <br><br>
    [IMAGE_2]
    <br><br>
    (선택 — 이 이슈의 배경/경쟁 구도를 원문이 실제로 뒷받침할 때만 3~4문단으로 쓰고, 뒷받침할 근거가
    빈약하면 이 섹션은 통째로 생략. 쓸 경우 "~로 예상된다"처럼 칼럼니스트의 해석임을 명시)
    <br><br>
    [IMAGE_3]
    <br><br>
    (선택 — 향후 전망도 원문에 근거가 있을 때만 "필자의 예측으로는" 같은 표현과 함께 2~3문단으로
    쓰고, 근거 없이 막연한 전망이 될 것 같으면 이 섹션도 생략)
    <br><br>
    [IMAGE_4]
    <br><br>
    (전체 내용을 관통하는 요약 1~2문단 — 위에서 이미 쓴 문장을 그대로 반복하지 말고, "그래서 결국
    무엇이 핵심인가"를 한 번 더 응축해서 새로운 문장으로)
    <br><br>
    <blockquote {blockquote_style}>글 전체의 주제를 관통하는 마무리 한 줄 요약</blockquote>
    """,
}


def write_blog_post(category, base64_images, ref_content="", topic=""):
    blockquote_style = 'style="border-left: 5px solid #d32f2f; padding: 18px 25px; margin: 35px 0; background-color: #fff9f9; color: #111; font-weight: 800; font-size: 1.15em; border-radius: 0 10px 10px 0; line-height: 1.6;"'
    table_style = 'style="width: 100%; border-collapse: collapse; margin: 35px 0; font-size: 0.95em; font-family: sans-serif; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05); border-radius: 8px; overflow: hidden;"'
    th_style = 'style="background-color: #1a202c; color: #ffffff; text-align: center; padding: 14px 15px; font-weight: bold;"'
    td_style = 'style="padding: 14px 15px; border-bottom: 1px solid #edf2f7; text-align: left; color: #2d3748; font-weight: 500;"' # 가독성을 위해 좌측 정렬로 변경

    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")

    persona = (
        "당신은 실제 방문·구매 경험 없이, 주어진 원문 자료만으로 독자에게 실용적인 정보를 정리해주는 "
        "에디터입니다." if category in INFO_CATEGORIES else
        "당신은 한국 최고의 탑티어 비즈니스/IT/경제 분야를 아우르는 날카로운 시각의 칼럼니스트이자, "
        "동시에 네이버/구글 검색 상위노출과 클릭을 부르는 카피라이팅에 능한 에디터입니다."
    )

    structure = CATEGORY_STRUCTURE.get(category, CATEGORY_STRUCTURE["_default"]).format(
        table_style=table_style, th_style=th_style, td_style=td_style, blockquote_style=blockquote_style,
    )

    system_prompt = f"""
    {persona}

    🚨 [사실 기반 작성 원칙 - 가장 중요, 반드시 지킬 것]
    1. 익명 처리(A사, 모 기업 등) 절대 금지! 원문에 등장하는 **실제 기업명, 인물명, 구체적 수치, 투자 금액, 확률 등 데이터**를 무조건 그대로 명시하세요.
    2. 수치·조건·예외는 원문에 있는 그대로만 쓰세요. 원문이 "일부 상품/일부 회차에만 해당"처럼 조건을
       달았다면, 그 조건을 절대 생략하거나 "전체 제공"처럼 일반화하지 마세요.
    3. 원문에 없는 수치(전환율, 비용, 성능 등)를 만들어내지 마세요. 근거 없는 수치는 아예 쓰지 않는
       편이 지어내는 것보다 낫습니다.
    4. 실제로 방문/시식/체험한 적이 없으므로 "직접 먹어보니", "방문해보니", "직원분과 대화해보니"처럼
       체험한 것처럼 쓰지 마세요. "원문에 따르면", "알려진 바로는" 같은 표현을 쓰세요.
    5. 향후 전망이나 경쟁 구도 분석처럼 원문에 없는 해석을 추가할 때는 "~로 보인다", "필자의 판단으로는"
       처럼 이것이 사실이 아니라 해설/전망이라는 것을 문장에서 드러내세요. 원문 사실과 해설을
       뒤섞어서 전부 확정된 사실처럼 쓰지 마세요.
    6. 이미지는 실제 해당 장소/제품의 사진이 아니라 분위기를 표현한 참고 이미지입니다. 이미지 속
       장면을 이 매장/제품의 실제 사진인 것처럼 구체적으로 설명하지 마세요.
    7. 마크다운 기호(```, markdown, html, **, #) 절대 금지! 오직 순수 HTML 태그만 사용.

    🚨 [분량보다 인사이트 — 가장 중요, 실측 확인된 문제] 예전엔 "최소 1800자"를 강제해서, 소스가
    짧은 단신 기사 하나뿐일 때도 억지로 분량을 채우려고 같은 사실을 표현만 바꿔 3번씩 반복하거나
    ("핵심 지표" 표에 본문과 똑같은 문장 재활용), 원문과 무관한 일반론("글로벌 경제 양극화가..."
    같은 어느 기사에나 붙일 수 있는 문장)으로 채우는 문제가 실제로 확인됐습니다. 이제 분량은
    자유입니다 — 소스에 진짜 근거가 풍부하면 1800자 넘게 써도 되고, 단신 기사 하나뿐이면 600~900자로
    짧게 끝내도 됩니다. 분량을 채우기 위한 반복·일반론·속빈 전망보다, 짧더라도 읽을 가치가 있는
    글이 우선입니다.
    - **동일한 사실을 표현만 바꿔 반복 금지.** 표(table)는 본문에 이미 쓴 문장을 그대로 옮기는 용도가
      아닙니다 — 원문에 본문과는 별개로 정리할 만한 추가 수치/비교 데이터가 있을 때만 쓰고, 없으면
      표 자체를 생략하세요.
    - 아래 [글 구조] 중 "배경/경쟁구도"와 "향후 전망" 섹션은 **선택사항**입니다. 원문에 그 내용을
      뒷받침할 진짜 근거가 있을 때만 쓰고, 없으면 해당 섹션째로 생략하세요. 억지로 채운 티가 나는
      문장보다 그 섹션이 아예 없는 게 낫습니다.

    🚨 [쓰기 전에 먼저 할 것 — 핵심 인사이트 한 가지]
    본문을 쓰기 전에, 이 소스에서 독자가 "아, 그래서 이게 왜 중요하지?"라고 느낄 만한 가장 흥미롭고
    비자명한 포인트 딱 하나를 먼저 정하세요. 글 전체를 그 포인트를 향해 구성하고, 나머지 사실은 그
    포인트를 뒷받침하는 용도로만 배치하세요. 모든 소재를 나열식으로 훑는 글보다, 하나의 관점을 깊이
    파고드는 글이 목표입니다.

    🚨 [조회수/가독성을 위한 글쓰기 규칙]
    - 제목: 핵심 키워드(회사명/종목명/사건명/매장명)를 앞쪽에 배치하고, 숫자·의외성 중 하나의 후킹
      장치를 결합하되 원문 사실과 어긋나는 과장은 넣지 마세요.
    - 도입부(첫 2문단)에서 독자가 당장 겪고 있을 법한 상황이나 원문 속 숫자로 시작하세요.
    - 문단은 3~4문장을 넘기지 마세요.
    - 상투적 문구("주목받고 있습니다" 등)는 피하고 구체적 문장으로 쓰세요.

    🚨 [글 구조 및 이미지 템플릿 - 순서와 마커는 지키되, 위에서 말한 선택 섹션은 근거 없으면 생략]
    이미지가 들어갈 자리를 본문 사이에 [IMAGE_1], [IMAGE_2] 텍스트로 정확히 명시해야 합니다. 절대 빼먹지 마세요.
    {structure}
    """

    res = gpt_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"주제: {topic}\n\n[최근 48시간 내 최신 특급 기사 팩트 원문]:\n{ref_content}"}],
        temperature=0.85
    )

    html_content = res.choices[0].message.content.strip()
    html_content = re.sub(r'^```[a-zA-Z]*\n', '', html_content)
    html_content = re.sub(r'```$', '', html_content).strip()
    if html_content.lower().startswith('markdown'): html_content = html_content[8:].strip()
    if html_content.lower().startswith('html'): html_content = html_content[4:].strip()
    html_content = html_content.replace('**', '')

    title = f"[{category.upper()}] 스페셜 브리핑"
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()

    if base64_images:
        img_tags = [f'<div style="text-align:center; margin: 45px 0;"><img src="{b64}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 10px 20px rgba(0,0,0,0.12);"></div>' for b64 in base64_images]

        # 1차: GPT가 프롬프트를 잘 지켜서 [IMAGE_X] 마커를 넣었을 경우 우선 치환
        for i, tag in enumerate(img_tags):
            marker = f"[IMAGE_{i+1}]"
            if marker in html_content:
                html_content = html_content.replace(marker, tag)

        # 2차: GPT가 마커를 빼먹어서 아직 치환 안된 이미지가 있다면, 인용구 위쪽으로 분배
        for i, tag in enumerate(img_tags):
            marker = f"[IMAGE_{i+1}]"
            if tag not in html_content:
                parts = html_content.rsplit('<blockquote', 1)
                if len(parts) == 2:
                    html_content = parts[0] + f"<br><br>{tag}<br><br><blockquote" + parts[1]
                else:
                    html_content += f"<br><br>{tag}"

    return title, html_content


# ==========================================
# 3.5 [NEW] 쿠팡 파트너스 — 관련 상품 링크 삽입
# ==========================================
def _coupang_signature(method, path, query=""):
    dt = datetime.datetime.now(datetime.timezone.utc).strftime("%y%m%d") + "T" + \
         datetime.datetime.now(datetime.timezone.utc).strftime("%H%M%S") + "Z"
    message = dt + method + path + query
    signature = hmac.new(COUPANG_SECRET_KEY.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"CEA algorithm=HmacSHA256, access-key={COUPANG_ACCESS_KEY}, signed-date={dt}, signature={signature}"


def coupang_search_products(keyword, limit=3):
    if not (COUPANG_ACCESS_KEY and COUPANG_SECRET_KEY):
        return []
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


def extract_product_keyword(category, topic, ref_content):
    """[NEW] 생성된 소재에서 쿠팡 검색에 쓸 핵심 제품/브랜드 키워드를 GPT로 짧게 추출.
    🚨 [v2 개선] 예전 프롬프트는 "관련해서 검색하면 좋을 키워드"처럼 기준이 느슨해서, 광고시장
    분석 글에 햇반, AI 산업 글에 포스기/종이컵처럼 독자와 무관한 상품이 자주 붙었음(리뷰로 확인).
    "이 글을 읽은 사람이 하려는 행동에 이 상품이 실제로 도움이 되는가"를 명시적으로 묻고,
    애매하면 NONE을 적극 고르도록 기준을 훨씬 엄격하게 바꿈."""
    try:
        res = gpt_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    f"다음은 '{category}' 카테고리 블로그 글의 소재야.\n\n"
                    f"제목: {topic}\n내용: {ref_content[:800]}\n\n"
                    "질문: 이 글을 읽은 독자가 지금 하려는 행동(구매/예약/방문 준비 등)에 실제로 "
                    "도움이 되는 쿠팡 판매 상품이 있어? 단어가 본문에 등장한다는 이유만으로 "
                    "고르지 말고, 독자에게 실질적으로 유용한 경우에만 답해.\n"
                    "있으면 구체적인 제품/브랜드 키워드 1개를 한국어 2~4단어로만 답하고, "
                    "조금이라도 애매하면 무조건 'NONE'이라고만 답해."
                )
            }],
            temperature=0.2,
        )
        keyword = res.choices[0].message.content.strip().strip('"')
        return None if keyword.upper() == "NONE" else keyword
    except Exception as e:
        print(f"⚠️ 쿠팡 키워드 추출 실패: {e}")
        return None


def inject_coupang_section(html_content, category, topic, ref_content):
    """[NEW] 본문 내용과 관련된 쿠팡 상품을 찾아 하단에 '관련 상품' 섹션으로 삽입.
    🚨 [v2 개선] news/it/stock 카테고리는 리뷰에서 확인된 "무관한 상품 추천" 사례가 전부 이
    카테고리들이었음 — 시사/기술 해설 글에 상품을 붙이는 것 자체가 구조적으로 안 맞는 경우가
    많아, food/travel(원래도 상품 연결이 자연스러운 카테고리)만 시도하도록 제한."""
    if category not in INFO_CATEGORIES:
        return html_content
    keyword = extract_product_keyword(category, topic, ref_content)
    if not keyword:
        return html_content
    products = coupang_search_products(keyword, limit=3)
    if not products:
        return html_content

    items_html = ""
    for p in products:
        name = html.escape(p.get("productName", ""))
        # 🐛 [v2 버그수정] productPrice가 float(예: 13900.0)로 올 때가 있어서 "13,900.0원"처럼
        # 소수점이 그대로 노출되던 문제(리뷰로 확인) — int로 캐스팅해서 정리.
        price = int(p.get("productPrice", 0) or 0)
        url = p.get("productUrl", "")
        image = p.get("productImage", "")
        items_html += (
            # 🌟 [v2] 다른 블로그(soloitems)와 동일하게 sponsored 속성 추가 (구글 광고링크 권장 속성)
            '<a href="' + url + '" target="_blank" rel="nofollow sponsored" '
            'style="display:block;text-decoration:none;color:#222;border:1px solid #eee;border-radius:10px;'
            'padding:14px;margin-bottom:10px;">'
            f'<img src="{image}" style="width:70px;height:70px;object-fit:cover;border-radius:6px;vertical-align:middle;margin-right:12px;">'
            f'<span style="vertical-align:middle;font-weight:600;">{name}</span>'
            f'<div style="color:#d32f2f;font-weight:700;margin-top:4px;">{price:,}원</div>'
            '</a>'
        )

    section = (
        '<br><br><hr><div style="margin-top:30px;">'
        '<h3 style="font-size:1.1em;">🛒 이 글과 함께 보면 좋은 상품</h3>'
        f'{items_html}'
        '<p style="font-size:0.8em;color:#999;">이 포스팅은 쿠팡 파트너스 활동의 일환으로, '
        '이에 따른 일정액의 수수료를 제공받습니다.</p>'
        '</div>'
    )
    return html_content + section


# ==========================================
# 3.6 [NEW] 같은 소재로 롱폼 대본 생성 + 텔레그램 전달
# ==========================================
def generate_longform_script(category, topic, ref_content):
    system_prompt = (
        "당신은 유튜브 롱폼(5~8분) 영상 대본 작가입니다. 주어진 소재로 씬 단위 나레이션 대본을 작성하세요. "
        "각 씬은 '씬 N: (화면 설명) / 대사: ...' 형식으로, 8~12개 씬으로 구성하고, "
        "도입부 후킹 → 본론 3~4개 포인트 → 마무리 요약 순서를 지키세요."
    )
    res = gpt_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt},
                  {"role": "user", "content": f"주제: {topic}\n\n참고 내용:\n{ref_content[:3000]}"}],
        temperature=0.8,
    )
    return res.choices[0].message.content.strip()


def send_longform_script_telegram(category, topic, script_text, source_note=""):
    header = f"🎬 [{category.upper()}] 오늘의 롱폼 대본 — {topic}\n{source_note}(로컬 롱폼 파이프라인에 넣어서 렌더링하세요)\n\n"
    body = header + script_text
    for i in range(0, len(body), 3800):
        send_telegram(body[i:i + 3800])


# ==========================================
# 3.7 [NEW] 분야별 지정 유튜버(슈카월드/삼프로TV 등) 영상 자막 → 재가공 롱폼
# ==========================================
CREATOR_CHANNELS = {
    "stock": [("슈카월드", "UCsJ6RuBiTVWRX156FVbeaGg"), ("삼프로TV", "UChlv4GSd7OQl3js-jkLOnFA")],
    "news": [("슈카월드", "UCsJ6RuBiTVWRX156FVbeaGg"), ("삼프로TV", "UChlv4GSd7OQl3js-jkLOnFA")],
}
CREATOR_HISTORY_FILE = "longform_creator_history.json"


def _load_creator_history():
    if not os.path.exists(CREATOR_HISTORY_FILE):
        return {"used_video_ids": []}
    try:
        with open(CREATOR_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"used_video_ids": []}


def _save_creator_history(history):
    history["used_video_ids"] = history.get("used_video_ids", [])[-50:]
    with open(CREATOR_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def fetch_creator_recent_videos(channel_id, max_results=5):
    if not YOUTUBE_API_KEY:
        return []
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        res = youtube.search().list(part="snippet", channelId=channel_id, order="date",
                                     type="video", maxResults=max_results).execute()
        return res.get("items", [])
    except Exception as e:
        print(f"⚠️ 채널 최신영상 조회 실패: {e}")
        return []


def pick_creator_source(category):
    """[NEW] 지정 채널들의 최신 영상 중 아직 안 쓴 것 하나를 골라 자막을 뽑는다."""
    channels = list(CREATOR_CHANNELS.get(category, []))
    if not channels:
        return None
    random.shuffle(channels)

    history = _load_creator_history()
    used_ids = set(history.get("used_video_ids", []))

    for creator_name, channel_id in channels:
        for item in fetch_creator_recent_videos(channel_id):
            video_id = item["id"]["videoId"]
            if video_id in used_ids:
                continue
            title = html.unescape(item["snippet"]["title"])
            try:
                transcript = YouTubeTranscriptApi().fetch(video_id, languages=["ko", "en"]).to_raw_data()
                text = " ".join(t["text"] for t in transcript)
            except Exception as e:
                print(f"⚠️ 자막 추출 실패({title}): {e}")
                continue
            if len(text) < 300:
                continue
            history.setdefault("used_video_ids", []).append(video_id)
            _save_creator_history(history)
            return {"creator": creator_name, "title": title, "transcript": text[:6000],
                    "url": f"https://www.youtube.com/watch?v={video_id}"}
    return None


def generate_longform_script_from_transcript(source):
    system_prompt = (
        "당신은 유튜브 롱폼(5~8분) 영상 대본 작가입니다. 아래는 다른 유튜버 영상의 자막 원문입니다. "
        "이 내용을 그대로 베끼지 말고, 핵심 정보/인사이트만 참고해서 완전히 새로운 관점과 표현, "
        "새로운 구성으로 재구성한 오리지널 대본을 작성하세요. 원문 문장을 그대로 가져오지 마세요(표절 금지). "
        "각 씬은 '씬 N: (화면 설명) / 대사: ...' 형식으로 8~12개 씬, 도입부 후킹 → 본론 3~4개 포인트 → 마무리 요약 순서."
    )
    res = gpt_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt},
                  {"role": "user", "content": f"참고 영상: {source['creator']} - {source['title']}\n\n자막 원문:\n{source['transcript']}"}],
        temperature=0.85,
    )
    return res.choices[0].message.content.strip()


# ==========================================
# 4. Blogger 발행 + 최근 포스트 조회(중복체크용)
# ==========================================
def _get_blogger_service():
    token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build('blogger', 'v3', credentials=creds)


def get_recent_post_titles(blog_id, max_results=5):
    """[NEW] 중복체크용 — 해당 블로그의 최근 발행 포스트 제목들을 가져온다."""
    try:
        service = _get_blogger_service()
        posts = service.posts().list(blogId=blog_id, maxResults=max_results, fetchBodies=False).execute()
        return [p.get("title", "") for p in posts.get("items", [])]
    except Exception as e:
        print(f"⚠️ 최근 포스트 조회 실패(중복체크 건너뜀): {e}")
        return []


def post_to_blogger(blog_id, title, content):
    service = _get_blogger_service()
    request = service.posts().insert(blogId=blog_id, body={"title": title, "content": content}, isDraft=False)
    return request.execute().get('url')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=True)
    parser.add_argument("--reference_url", default="")
    parser.add_argument("--topic", default="")
    parser.add_argument("--with_longform", action="store_true", help="같은 소재로 롱폼 대본도 생성해서 텔레그램으로 보냄")
    args = parser.parse_args()

    category = args.category
    if category == "auto":
        hour = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).hour
        mapping = {(7,12,17): "news", (8,13,18): "it", (9,14,19): "stock", (10,15,20): "travel", (11,16,21): "food"}
        category = next((v for k, v in mapping.items() if hour in k), "news")

    blog_id = BLOG_REGISTRY.get(category)
    if not blog_id: exit(1)

    recent_titles = get_recent_post_titles(blog_id, max_results=5)

    ref_url = args.reference_url
    if ref_url:
        ref_content, topic, _ = fetch_reference_content(ref_url)
    else:
        ref_content, topic, ref_url = generate_auto_topic(category, recent_titles=recent_titles)
        if ref_content and ref_url:
            # 🚨 [v2] 같은 원문 기사가 다음날 또 소재로 뽑히지 않도록 채택 즉시 기록
            # (자동 선정된 경우만 — --reference_url로 수동 지정한 건 기록하지 않음)
            mark_source_url_used(category, ref_url)

    if not ref_content:
        print("❌ 유효한 기사 팩트를 찾지 못해 포스팅을 중단합니다.")
        send_telegram(f"⚠️ [{category.upper()}] 백업 엔진까지 가동했으나 최근 48시간 이내의 적합한 뉴스를 찾지 못했습니다.")
        exit(0)

    photo_prompt = create_photo_prompt(category, topic, ref_content)
    image_paths = generate_and_split_images_xai(photo_prompt, use_character=(category in CHARACTER_CATEGORIES))
    images = image_paths_to_b64(image_paths)
    title, html_output = write_blog_post(category, images, ref_content, topic)

    # [NEW] 쿠팡 관련 상품 섹션 삽입 (본문 출처 링크보다 먼저)
    html_output = inject_coupang_section(html_output, category, topic, ref_content)

    if ref_url:
        html_output += f'<br><br><hr><div style="text-align:center; margin-top: 40px;"><p style="font-size: 1.15em; font-weight: bold;">🔗 <a href="{ref_url}" target="_blank" style="color: #d32f2f; text-decoration: none;">오늘의 최신 기사 원문 출처 보기</a></p></div>'

    try:
        post_url = post_to_blogger(blog_id, title, html_output)
        send_telegram(f"⚡ [{category.upper()}] 최신 심층 분석 칼럼 발행 완료!\n📝 {title}\n👉 {post_url}")
    except Exception as e:
        print(f"❌ 최종 업로드/알림 에러: {e}")
        exit(1)

    # [NEW] 롱폼 대본 생성 — 지정 유튜버 채널이 있는 카테고리는 그 채널 최신 영상을 재가공,
    # 없으면 기존처럼 블로그와 같은 소재로 생성
    if args.with_longform:
        try:
            creator_source = pick_creator_source(category)
            if creator_source:
                script = generate_longform_script_from_transcript(creator_source)
                send_longform_script_telegram(
                    category, creator_source["title"], script,
                    source_note=f"(출처: {creator_source['creator']} 영상 재가공 — {creator_source['url']})\n"
                )
            else:
                script = generate_longform_script(category, topic, ref_content)
                send_longform_script_telegram(category, topic, script, source_note="(블로그와 같은 소재로 자동 생성됨)\n")
        except Exception as e:
            print(f"⚠️ 롱폼 대본 생성/전송 실패: {e}")
