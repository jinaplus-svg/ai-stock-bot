import os
import json
import argparse
import base64
import requests
import datetime
import re
import html
from io import BytesIO
from PIL import Image
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from bs4 import BeautifulSoup

# ==========================================
# 1. 설정 및 API 키 로드
# ==========================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
XAI_API_KEY = os.environ.get("XAI")
GOOGLE_OAUTH_TOKEN_STR = os.environ.get("GOOGLE_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

BLOG_REGISTRY = {
    "it": os.environ.get("IT_BLOG_ID"),
    "food": os.environ.get("FOOD_BLOG_ID"),
    "news": os.environ.get("NEWS_BLOG_ID"),
    "stock": os.environ.get("STOCK_BLOG_ID"),
    "youtube": os.environ.get("YOUTUBE_BLOG_ID")
}

gpt_client = OpenAI(api_key=OPENAI_API_KEY)
xai_client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
SCOPES = ['https://www.googleapis.com/auth/blogger']

def clean_naver_text(text):
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text)

# ==========================================
# 2. [Track 1] 네이버 API 실시간 이슈 기획 (링크 없을 때)
# ==========================================
def generate_auto_topic(category):
    print(f"🤖 [{category.upper()}] 네이버 API로 실시간 이슈 검색 중...")
    
    search_queries = {
        "news": "사회 이슈", "it": "IT 신기술", "stock": "증시 전망", 
        "food": "맛집 트렌드", "youtube": "유튜브 트렌드"
    }
    query = search_queries.get(category, "핫이슈")

    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        try:
            api_url = "https://openapi.naver.com/v1/search/news.json"
            headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
            params = {"query": query, "display": 1, "sort": "date"}
            
            response = requests.get(api_url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('items'):
                    item = data['items'][0]
                    real_title = clean_naver_text(item['title'])
                    real_desc = clean_naver_text(item['description'])
                    real_link = item['originallink'] if item.get('originallink') else item['link']
                    print(f"✅ 네이버 검색 성공: {real_title}")
                    return f"[요약]: {real_desc}", real_title, real_link
        except Exception as e:
            print(f"⚠️ 네이버 검색 오류: {e}")
            
    # 네이버 실패 시 GPT 임시 기획
    try:
        system_prompt = f"당신은 '{category}' 전문가입니다. 오늘 대중이 관심 가질 만한 최신 핫이슈를 기획하세요.\n응답 형식:\n[주제]: (주제명)\n[내용]: (내용 브리핑)"
        res = gpt_client.chat.completions.create(
            model="gpt-5.4-mini", messages=[{"role": "system", "content": system_prompt}], temperature=0.9
        )
        result = res.choices[0].message.content.strip()
        topic = re.search(r'\[주제\]:\s*(.*)', result).group(1)
        content = re.search(r'\[내용\]:\s*(.*)', result, re.DOTALL).group(1)
        return content, topic, ""
    except:
        return "오늘의 주요 브리핑", f"[{category.upper()}] 오늘의 핫이슈", ""

# ==========================================
# 3. [Track 2] 텔레그램 링크 분석기 (링크 있을 때)
# ==========================================
def fetch_reference_content(url):
    if not url: return "", "", ""
    print(f"🔗 텔레그램 링크({url}) 분석 중...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title_tag = soup.find('meta', property='og:title')
        page_title = title_tag['content'] if title_tag else (soup.title.text if soup.title else "참조 링크")
        
        desc_tag = soup.find('meta', property='og:description') or soup.find('meta', name='description')
        meta_desc = desc_tag['content'] if desc_tag else ""
        
        for script in soup(["script", "style", "nav", "footer"]): script.decompose()
        text = soup.get_text(separator=' ', strip=True)
        return f"[요약]: {meta_desc}\n\n[본문]: {text[:2500]}", page_title, url
    except Exception as e:
        print(f"⚠️ 링크 분석 실패: {e}")
        return "", "", ""

# ==========================================
# 4. 카테고리 맞춤형 메타포(은유) 프롬프트
# ==========================================
def create_metaphorical_prompt(category, topic, ref_content):
    print(f"🧠 [{category.upper()}] 맞춤형 이미지 프롬프트 구상 중...")
    system_msg = f"""
    당신은 아트 디렉터입니다. 주제 '{topic}'를 표현할 영문 이미지 프롬프트를 1문장으로 작성하세요.
    피, 폭력, 총, 글자(text) 절대 금지. 카테고리 '{category}'의 특성에 맞게 (IT는 미래적, 맛집은 웜톤, 뉴스는 시네마틱 등) 상징적으로 표현하세요.
    """
    try:
        res = gpt_client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"내용: {ref_content[:500]}"}],
            temperature=0.8
        )
        return res.choices[0].message.content.strip()
    except:
        return "abstract cinematic mood, highly detailed, soft lighting."

# ==========================================
# 5. xAI 6분할 이미지 생성
# ==========================================
def generate_and_split_images_xai(metaphor_prompt):
    print("🎨 6컷 분할 이미지 생성 중...")
    final_prompt = f"A professional 3:2 aspect ratio grid image collage divided into 6 clean scenes. {metaphor_prompt} Modern aesthetic photography style, no text."
    try:
        response = xai_client.images.generate(
            model="grok-imagine-image",
            prompt=final_prompt,
            extra_body={"aspect_ratio": "3:2", "resolution": "2k"},
            n=1
        )
        img_data = requests.get(response.data[0].url).content
        img = Image.open(BytesIO(img_data))
        
        width, height = img.size
        cell_w, cell_h = width // 3, height // 2
        margin = 25
        base64_images = []
        for row in range(2):
            for col in range(3):
                left, top = (col * cell_w) + margin, (row * cell_h) + margin
                right, bottom = left + cell_w - margin, top + cell_h - margin
                cropped = img.crop((left, top, right, bottom))
                cropped = cropped.resize((600, int(600 * (cropped.height / cropped.width))), Image.Resampling.LANCZOS)
                if cropped.mode in ('RGBA', 'P'): cropped = cropped.convert('RGB')
                buffered = BytesIO()
                cropped.save(buffered, format="JPEG", quality=85)
                base64_images.append(f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}")
        return base64_images
    except Exception as e:
        print(f"❌ 이미지 생성 실패: {e}")
        return []

# ==========================================
# 6. 통찰력 있는 1500자 원고 작성
# ==========================================
def write_blog_post(category, base64_images, ref_content="", topic=""):
    print(f"✍️ 1500자 분량의 깊이 있는 원고 작성 중...")
    system_prompt = f"""
    당신은 '{category}' 분야의 통찰력 있는 10년 차 리뷰어입니다. 
    글 길이를 1500자 내외로 넉넉하고 깊이 있게 작성하세요.
    
    [작성 규칙]
    1. 최상단에 <h2> 태그로 후킹하는 제목 1번 작성.
    2. 본문은 3~4개의 소주제로 나누고 <h3> 소제목 사용.
    3. 한 문단에 최소 3~4문장 이상 깊이 있는 비평을 담고, 문단 간격은 <br><br> 사용.
    4. 이미지 배치: [IMAGE_1] 부터 [IMAGE_6] 태그를 문장 중간중간에 골고루 분산 배치하세요.
    5. 기계적 요약 금지, 독자에게 말을 거는 친근하고 날카로운 문체 사용.
    
    [오늘의 참고 데이터]
    주제/기사제목: {topic}
    주요내용: {ref_content}
    """
    res = gpt_client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.85
    )
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    # 제목 중복 렌더링 방지
    title = f"[{category.upper()}] 오늘의 핵심 인사이트"
    h2_match = re.search(r'<h2>(.*?)</h2>', html_content)
    if h2_match:
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()

    # 이미지 태그 치환
    if base64_images:
        for i, b64 in enumerate(base64_images):
            img_tag = f'<div style="text-align:center; margin: 35px 0;"><img src="{b64}" style="max-width: 90%; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);"></div>'
            html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
    for i in range(1, 7): html_content = html_content.replace(f"[IMAGE_{i}]", "")
    return title, html_content

# ==========================================
# 7. 메인 실행부 (에러 수정 완료)
# ==========================================
def get_auto_category():
    now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    hour = now_kst.hour
    mapping = {(7, 12, 17): "news", (8, 13, 18): "it", (9, 14, 19): "stock", (10, 15, 20): "youtube", (11, 16, 21): "food"}
    for hours, cat in mapping.items():
        if hour in hours: return cat
    return "news"

def post_to_blogger(blog_id, title, content):
    token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
    service = build('blogger', 'v3', credentials=creds)
    request = service.posts().insert(blogId=blog_id, body={"title": title, "content": content}, isDraft=False)
    response = request.execute()
    return response.get('url')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=True)
    parser.add_argument("--reference_url", default="") 
    # 📌 텔레그램 리모컨 호환성을 위한 파라미터(에러 방지)
    parser.add_argument("--topic", default="", help="ignored") 
    args = parser.parse_args()
    
    category = get_auto_category() if args.category == "auto" else args.category
    blog_id = BLOG_REGISTRY.get(category)
    if not blog_id: exit(1)
        
    # 링크 유무에 따라 트랙1(네이버 API) 또는 트랙2(직접 스크래핑) 분기
    ref_url_for_post = args.reference_url
    if args.reference_url:
        ref_content, topic, _ = fetch_reference_content(args.reference_url)
    else:
        ref_content, topic, ref_url_for_post = generate_auto_topic(category)
    
    # 공통 로직 (프롬프트 -> 생성 -> 작성)
    metaphor_prompt = create_metaphorical_prompt(category, topic, ref_content)
    images = generate_and_split_images_xai(metaphor_prompt)
    title, html = write_blog_post(category, images, ref_content, topic)
    
    # 원문 링크 삽입 (네이버 오류 방지 적용)
    if ref_url_for_post:
        link_html = f'<br><br><hr><div style="text-align:center; padding: 20px; background-color: #f8f9fa; border-radius: 8px;"><p style="margin: 0;">🔗 <a href="{ref_url_for_post}" target="_blank" rel="noopener noreferrer" style="color:#0056b3; font-weight: bold; text-decoration:none;">[사건 원문 기사 확인하기]</a></p></div>'
        html += link_html
        
    try:
        post_url = post_to_blogger(blog_id, title, html)
        print(f"✅ 발행 성공: {post_url}")
        if TELEGRAM_TOKEN and CHAT_ID:
            msg = f"⚡ [{category.upper()}] 실시간 포스팅 완료!\n\n📝 {title}\n👉 {post_url}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ 오류: {e}")