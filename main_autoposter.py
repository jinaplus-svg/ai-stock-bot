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
# 2. 실시간 데이터 가져오기
# ==========================================
def generate_auto_topic(category):
    print(f"🤖 [{category.upper()}] 네이버 API 검색 중...")
    search_queries = {
        "news": "사회 속보", "it": "IT 신기술 트렌드", "stock": "증시 주식 특징주", 
        "food": "인기 맛집 핫플", "youtube": "유튜브 크리에이터 이슈"
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
                    return f"[요약]: {clean_naver_text(item['description'])}", clean_naver_text(item['title']), item.get('originallink') or item['link']
        except Exception as e:
            print(f"⚠️ 네이버 검색 오류: {e}")
            
    system_prompt = f"당신은 '{category}' 전문가입니다. 대중의 이목을 끌 최신 핫이슈를 기획하세요.\n[주제]: (주제명)\n[내용]: (내용 브리핑)"
    res = gpt_client.chat.completions.create(model="gpt-5.4-mini", messages=[{"role": "system", "content": system_prompt}], temperature=0.9)
    result = res.choices[0].message.content.strip()
    return re.search(r'\[내용\]:\s*(.*)', result, re.DOTALL).group(1), re.search(r'\[주제\]:\s*(.*)', result).group(1), ""

def fetch_reference_content(url):
    if not url: return "", "", ""
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        title = (soup.find('meta', property='og:title') or soup.title).get('content', soup.title.text if soup.title else "참조")
        desc = (soup.find('meta', property='og:description') or soup.find('meta', name='description'))
        desc_text = desc['content'] if desc else ""
        for script in soup(["script", "style", "nav", "footer"]): script.decompose()
        return f"[요약]: {desc_text}\n\n[본문]: {soup.get_text(separator=' ', strip=True)[:2500]}", title, url
    except:
        return "", "", ""

# ==========================================
# 3. 4분할 실사 프롬프트
# ==========================================
def create_photo_prompt(category, topic, ref_content):
    print(f"🧠 실사 4분할 프롬프트 구상 중...")
    system_msg = f"""
    당신은 보도사진 편집장입니다. 주제 '{topic}'와 관련된 영문 이미지 프롬프트를 딱 1문장으로 작성하세요.
    1. 3D CG 절대 금지. 무조건 고화질 실사(Photorealistic, editorial photography).
    2. 사람들이 현장에서 자연스럽게 행동하는 모습 묘사. 폭력/글자(text) 금지.
    """
    try:
        res = gpt_client.chat.completions.create(model="gpt-5.4-mini", messages=[{"role": "system", "content": system_msg}], temperature=0.8)
        return res.choices[0].message.content.strip()
    except:
        return "Photorealistic natural scene with real people interacting, editorial photography."

# ==========================================
# 4. 2K 해상도 4분할 이미지 생성
# ==========================================
def generate_and_split_images_xai(prompt):
    print("🎨 2K 고화질 4분할(2x2) 실사 이미지 생성 중...")
    final_prompt = f"A photo collage composed of exactly 4 distinct square panels arranged in a 2x2 grid. {prompt} Photorealistic, natural everyday scenes showing real people, cinematic lighting, no text, no borders."
    try:
        response = xai_client.images.generate(model="grok-imagine-image", prompt=final_prompt, extra_body={"aspect_ratio": "1:1", "resolution": "2k"}, n=1)
        img_data = requests.get(response.data[0].url).content
        img = Image.open(BytesIO(img_data))
        
        width, height = img.size
        cell_w, cell_h = width // 2, height // 2
        margin = 15
        base64_images = []
        
        for row in range(2):
            for col in range(2):
                left, top = col * cell_w + margin, row * cell_h + margin
                right, bottom = left + cell_w - (margin * 2), top + cell_h - (margin * 2)
                cropped = img.crop((left, top, right, bottom)).resize((600, 600), Image.Resampling.LANCZOS)
                if cropped.mode in ('RGBA', 'P'): cropped = cropped.convert('RGB')
                buffered = BytesIO()
                cropped.save(buffered, format="JPEG", quality=88)
                base64_images.append(f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}")
        return base64_images
    except Exception as e:
        print(f"❌ 이미지 생성 실패: {e}")
        return []

# ==========================================
# 5. ⭐️ 가독성 극대화 블로그 원고 작성 ⭐️
# ==========================================
def write_blog_post(category, base64_images, ref_content="", topic=""):
    print(f"✍️ 가독성을 높인 트렌디한 원고 작성 중...")
    
    # 인용구(Blockquote)에 예쁜 디자인을 입히기 위한 인라인 CSS 문자열
    blockquote_style = 'style="border-left: 4px solid #0056b3; padding: 10px 15px; margin: 25px 0; background-color: #f4f8fa; color: #333; font-style: normal; font-weight: bold; border-radius: 0 8px 8px 0;"'
    
    system_prompt = f"""
    당신은 '{category}' 분야의 정보를 날카롭게 분석하는 '상위 1% 업계 내부자'입니다.
    스마트폰으로 읽기 편하도록 1000자 내외로 짧고, 타격감 있고, 가독성 있게 작성하세요.
    
    [가독성 극대화 작성 규칙 - 반드시 지킬 것!]
    1. 제목: 최상단에 <h2> 태그로 도발적인 제목 1개만 작성.
    2. 시각적 호흡: 절대 한 문단이 3문장을 넘지 않게 하세요. 문단이 끝나면 무조건 <br><br>로 넓게 띄어쓰기를 하세요. (벽돌 텍스트 절대 금지)
    3. 핵심 강조: 문단마다 가장 중요한 핵심 단어나 문장은 <strong> 태그로 굵게 표시하세요. 독자가 굵은 글씨만 읽어도 이해되게 하세요.
    4. 인용구 활용: 본문 중간에 이 기사/사건을 꿰뚫는 가장 뼈 때리는 한 문장을 <blockquote {blockquote_style}> 여기에 작성 </blockquote> 형태로 삽입하여 시선을 사로잡으세요.
    5. 3줄 요약: 글의 맨 마지막에는 <ul>과 <li> 태그를 사용해 "바쁜 분들을 위한 핵심 요약" 3가지를 깔끔하게 정리해 주세요.
    6. 어조: 딱딱한 설명문이 아니라, "여러분, 솔직히 이거 아셨나요?", "이게 진짜 무서운 이유가 뭔지 아십니까?" 처럼 독자에게 직접 말을 거는 몰입감 있는 1:1 대화체를 사용하세요.
    7. 이미지 배치: [IMAGE_1], [IMAGE_2], [IMAGE_3], [IMAGE_4] 태그를 각 문단이나 소제목 사이에 시원시원하게 분산 배치하세요.
    
    주제/기사제목: {topic}
    주요내용: {ref_content}
    """
    res = gpt_client.chat.completions.create(model="gpt-5.4-mini", messages=[{"role": "system", "content": system_prompt}], temperature=0.85)
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    title = f"[{category.upper()}] 핵심 브리핑"
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()

    # 이미지 태그 치환
    if base64_images:
        for i, b64 in enumerate(base64_images):
            img_tag = f'<div style="text-align:center; margin: 40px 0;"><img src="{b64}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);"></div>'
            html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
    
    html_content = re.sub(r'\[IMAGE_\d+\]', '', html_content)
    return title, html_content

# ==========================================
# 6. 메인 실행부
# ==========================================
def get_auto_category():
    hour = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).hour
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
    return request.execute().get('url')

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=True)
    parser.add_argument("--reference_url", default="") 
    parser.add_argument("--topic", default="", help="ignored") 
    args = parser.parse_args()
    
    category = get_auto_category() if args.category == "auto" else args.category
    blog_id = BLOG_REGISTRY.get(category)
    if not blog_id: exit(1)
        
    ref_url_for_post = args.reference_url
    if args.reference_url:
        ref_content, topic, _ = fetch_reference_content(args.reference_url)
    else:
        ref_content, topic, ref_url_for_post = generate_auto_topic(category)
    
    photo_prompt = create_photo_prompt(category, topic, ref_content)
    images = generate_and_split_images_xai(photo_prompt)
    title, html = write_blog_post(category, images, ref_content, topic)
    
    if ref_url_for_post:
        html += f'<br><br><hr><div style="text-align:center; padding: 25px; background-color: #f8f9fa; border-radius: 12px;"><p style="margin: 0; color:#555; font-size:14px;">팩트체크가 더 필요하신가요?</p><p style="margin: 8px 0 0 0;">🔗 <a href="{ref_url_for_post}" target="_blank" rel="noopener noreferrer" style="color:#0056b3; font-weight: bold; text-decoration:none;">원문 기사 바로가기</a></p></div>'
        
    try:
        post_url = post_to_blogger(blog_id, title, html)
        print(f"✅ 발행 성공: {post_url}")
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚡ [{category.upper()}] 가독성 1000% 포스팅 완료!\n\n📝 {title}\n👉 {post_url}"})
    except Exception as e:
        print(f"❌ 오류: {e}")