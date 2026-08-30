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
def create_photo_prompt(category, topic, ref_content):
    system_msg = f"""
    당신은 퓰리처상을 받은 보도사진 편집장입니다.
    제공된 기사의 핵심 맥락(Context)을 깊이 이해하고, 이슈의 본질을 보여주는 상징적이고 생동감 넘치는 4분할 컷(4-panel photo collage) 영문 프롬프트를 작성하세요.

    🚨 [절대 금지 사항 - CRITICAL]
    - 현존 AI 기술 한계상 이미지 내 텍스트는 무조건 깨집니다. 따라서 ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO TYPOGRAPHY, NO LOGOS, NO SIGNS!
    - 영어든 한글이든 글자는 단 1개도 들어가선 안 됩니다. 글자가 필요한 간판이나 화면 대신 사람의 표정, 제품의 형태, 상황의 분위기에만 집중하세요.
    - 3D CG, 일러스트레이션 금지. 오직 8k 극사실주의 보도사진(Photorealistic, documentary photography) 스타일로 묘사할 것.
    """
    res = gpt_client.chat.completions.create(
        model="gpt-4o",  # Mini에서 고성능 모델로 업그레이드 (맥락 파악 강화)
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"주제: {topic}\n내용: {ref_content}"}],
        temperature=0.7
    )
    return res.choices[0].message.content.strip()

def generate_and_split_images_xai(prompt):
    final_prompt = f"A seamless photo collage of 4 panels in a 2x2 grid. {prompt} Highly highly realistic, documentary photography, cinematic lighting, ABSOLUTELY NO TEXT, NO WORDS, NO LOGOS, NO LETTERS, no signs, no typography, clean visual only."
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
        base64_images = []
        for r in range(2):
            for c in range(2):
                l, t = c * cw + margin, r * ch + margin
                ri, b = l + cw - (margin * 2), t + ch - (margin * 2)
                cropped = img.crop((l, t, ri, b)).resize((600, 600), Image.Resampling.LANCZOS)
                if cropped.mode in ('RGBA', 'P'): cropped = cropped.convert('RGB')
                buf = BytesIO()
                cropped.save(buf, format="JPEG", quality=88)
                base64_images.append(f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}")
        return base64_images
    except:
        return []

def write_blog_post(category, base64_images, ref_content="", topic=""):
    blockquote_style = 'style="border-left: 5px solid #d32f2f; padding: 18px 25px; margin: 35px 0; background-color: #fff9f9; color: #111; font-weight: 800; font-size: 1.15em; border-radius: 0 10px 10px 0; line-height: 1.6;"'
    table_style = 'style="width: 100%; border-collapse: collapse; margin: 35px 0; font-size: 0.95em; font-family: sans-serif; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05); border-radius: 8px; overflow: hidden;"'
    th_style = 'style="background-color: #1a202c; color: #ffffff; text-align: center; padding: 14px 15px; font-weight: bold;"'
    td_style = 'style="padding: 14px 15px; border-bottom: 1px solid #edf2f7; text-align: left; color: #2d3748; font-weight: 500;"' # 가독성을 위해 좌측 정렬로 변경

    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")

    system_prompt = f"""
    당신은 한국 최고의 탑티어 비즈니스/IT/경제/여행 분야를 아우르는 날카로운 시각의 칼럼니스트입니다.

    🚨 [핵심 지시 사항 - 전문가의 통찰과 구체성]
    1. 익명 처리(A사, 모 기업 등) 절대 금지! 원문에 등장하는 **실제 기업명, 인물명, 구체적 수치, 투자 금액, 확률 등 데이터**를 무조건 그대로 명시하세요.
    2. 기사 내용을 단순 요약하는 것은 20% 이내로 제한합니다.
    3. 나머지 80%는 전문가적 관점에서의 **날카로운 비평, 이면의 의도 분석, 경쟁사와의 비교, 향후 산업/우리 실생활에 미칠 파급력에 대한 심층 뇌피셜**로 꽉 채우세요. (최소 2500자 이상 작성)
    4. 마크다운 기호(```, markdown, html, **, #) 절대 금지! 오직 순수 HTML 태그만 사용.

    🚨 [글 구조 및 이미지 템플릿 - 반드시 아래 순서와 마커를 100% 지키세요!]
    이미지가 들어갈 자리를 본문 사이에 [IMAGE_1], [IMAGE_2] 텍스트로 정확히 명시해야 합니다. 절대 빼먹지 마세요.

    <h2>시선을 훅 끄는 도발적인 제목</h2>
    (독자에게 말을 건네듯 "여러분 혹시 오늘 이 소식 들으셨나요?" 로 시작하며 이슈의 핵심을 던지는 흥미진진한 도입부 2~3문단)
    <br><br>
    [IMAGE_1]
    <br><br>
    (표면적인 기사 내용의 팩트와 등장 기업/수치에 대한 구체적 설명 2~3문단)
    <br><br>
    <table {table_style}>
      <thead><tr><th {th_style}>핵심 지표 / 비교 항목</th><th {th_style}>구체적 수치 및 전문가 코멘트</th></tr></thead>
      <tbody><tr><td {td_style}>실제 데이터 기입</td><td {td_style}>분석 내용</td></tr></tbody>
    </table>
    <br><br>
    [IMAGE_2]
    <br><br>
    (이 이슈의 이면에 숨겨진 의도, 경쟁사들의 대응, 그리고 칼럼니스트로서의 날카로운 비판이나 긍정적 평가 3~4문단)
    <br><br>
    [IMAGE_3]
    <br><br>
    (이 기술이나 사건이 향후 1~3년 뒤 일반 소비자나 시장 판도를 어떻게 뒤흔들 것인지에 대한 통찰력 있는 예측 2~3문단)
    <br><br>
    [IMAGE_4]
    <br><br>
    (전체 내용을 관통하는 뼈때리는 요약 1~2문단)
    <br><br>
    <blockquote {blockquote_style}>글 전체의 주제를 관통하는 가장 엣지있고 철학적인 마무리 한 줄 요약</blockquote>
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
    """[NEW] 생성된 소재에서 쿠팡 검색에 쓸 핵심 제품/브랜드 키워드를 GPT로 짧게 추출."""
    try:
        res = gpt_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    f"다음은 '{category}' 카테고리 블로그 소재야. 이 내용과 관련해서 쿠팡에서 검색하면 좋을 "
                    f"구체적인 제품/브랜드 키워드 1개만 한국어 2~4단어로 답해. 관련 상품이 마땅치 않으면 'NONE'이라고만 답해.\n\n"
                    f"제목: {topic}\n내용: {ref_content[:800]}"
                )
            }],
            temperature=0.3,
        )
        keyword = res.choices[0].message.content.strip().strip('"')
        return None if keyword.upper() == "NONE" else keyword
    except Exception as e:
        print(f"⚠️ 쿠팡 키워드 추출 실패: {e}")
        return None


def inject_coupang_section(html_content, category, topic, ref_content):
    """[NEW] 본문 내용과 관련된 쿠팡 상품을 찾아 하단에 '관련 상품' 섹션으로 삽입."""
    keyword = extract_product_keyword(category, topic, ref_content)
    if not keyword:
        return html_content
    products = coupang_search_products(keyword, limit=3)
    if not products:
        return html_content

    items_html = ""
    for p in products:
        name = html.escape(p.get("productName", ""))
        price = p.get("productPrice", 0)
        url = p.get("productUrl", "")
        image = p.get("productImage", "")
        items_html += (
            '<a href="' + url + '" target="_blank" rel="nofollow" '
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


def send_longform_script_telegram(category, topic, script_text):
    header = f"🎬 [{category.upper()}] 오늘의 롱폼 대본 — {topic}\n(같은 소재로 자동 생성됨. 로컬 롱폼 파이프라인에 넣어서 렌더링하세요)\n\n"
    body = header + script_text
    for i in range(0, len(body), 3800):
        send_telegram(body[i:i + 3800])


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

    if not ref_content:
        print("❌ 유효한 기사 팩트를 찾지 못해 포스팅을 중단합니다.")
        send_telegram(f"⚠️ [{category.upper()}] 백업 엔진까지 가동했으나 최근 48시간 이내의 적합한 뉴스를 찾지 못했습니다.")
        exit(0)

    photo_prompt = create_photo_prompt(category, topic, ref_content)
    images = generate_and_split_images_xai(photo_prompt)
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

    # [NEW] 같은 소재로 롱폼 대본도 만들어서 텔레그램 전달 (렌더링은 로컬 파이프라인에서)
    if args.with_longform:
        try:
            script = generate_longform_script(category, topic, ref_content)
            send_longform_script_telegram(category, topic, script)
        except Exception as e:
            print(f"⚠️ 롱폼 대본 생성/전송 실패: {e}")
