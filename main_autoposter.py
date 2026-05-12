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
from youtube_transcript_api import YouTubeTranscriptApi

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
    "travel": os.environ.get("TRAVEL_BLOG_ID")
}

gpt_client = OpenAI(api_key=OPENAI_API_KEY)
xai_client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")
SCOPES = ['https://www.googleapis.com/auth/blogger']

# ==========================================
# 2. 크롤링 및 유튜브 자막 추출
# ==========================================
def get_youtube_content(url):
    video_id = None
    if "youtu.be" in url:
        video_id = url.split("/")[-1].split("?")[0]
    elif "youtube.com" in url:
        video_id = re.search(r"v=([a-zA-Z0-9_-]+)", url).group(1)
    
    if not video_id: return "", "유튜브 영상", url
    
    print(f"📺 유튜브 영상 분석 중... (ID: {video_id})")
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
        transcript_text = " ".join([item['text'] for item in transcript_list])
        
        res = requests.get(url)
        soup = BeautifulSoup(res.text, 'html.parser')
        title = soup.title.string.replace(" - YouTube", "") if soup.title else "유튜브 영상 분석"
        
        return f"[유튜브 원본 스크립트]:\n{transcript_text[:4000]}", title, url
    except Exception as e:
        print(f"⚠️ 유튜브 자막 추출 실패: {e}")
        return "자막을 읽을 수 없는 영상입니다.", "유튜브 영상", url

def fetch_reference_content(url):
    if not url: return "", "", ""
    if "youtube.com" in url or "youtu.be" in url:
        return get_youtube_content(url)
        
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://search.naver.com/"
        }
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title = (soup.find('meta', property='og:title') or soup.find('meta', name='title') or soup.title).get('content', soup.title.text if soup.title else "참조")
        
        article_body = (soup.find('article', id='dic_area') or 
                        soup.find('div', id='dic_area') or 
                        soup.find('div', id='articeBody') or 
                        soup.find('div', id='newsct_article') or 
                        soup.find('div', class_='news_contents') or 
                        soup.find('article'))
        
        if article_body:
            for el in article_body.find_all(['script', 'style', 'em', 'span']):
                if el.name == 'span' and 'end_photo_org' in el.get('class', []): continue
                el.decompose()
            text_content = article_body.get_text(separator='\n', strip=True)
        else:
            for script in soup(["script", "style", "nav", "footer", "header", "aside", "form"]): 
                script.decompose()
            paragraphs = soup.find_all('p')
            if paragraphs:
                text_content = '\n'.join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20])
            else:
                text_content = soup.get_text(separator='\n', strip=True)
            
        return text_content[:4000], title, url
    except Exception as e:
        print(f"⚠️ 크롤링 에러: {e}")
        return "", "", url

def generate_auto_topic(category):
    print(f"🤖 [{category.upper()}] 네이버 API 최신 뉴스 검색 중...")
    search_queries = {
        "news": "오늘 주요 사회 속보", 
        "it": "오늘 IT 기술 신제품", 
        "stock": "오늘 주식 증시 특징주 시황", 
        "food": "인기 맛집", 
        "travel": "추천 국내 여행지"
    }
    query = search_queries.get(category, "오늘 핫이슈")
    
    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        try:
            api_url = "https://openapi.naver.com/v1/search/news.json"
            headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
            params = {"query": query, "display": 5, "sort": "date"}
            response = requests.get(api_url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                for item in data.get('items', []):
                    link = item.get('originallink') or item['link']
                    topic_title = html.unescape(re.sub(r'<[^>]+>', '', item['title']))
                    snippet = html.unescape(re.sub(r'<[^>]+>', '', item['description']))
                    
                    ref_content, _, _ = fetch_reference_content(link)
                    
                    # ⭐️ 본문 긁기에 실패하더라도, API가 주는 '기사 요약(snippet)'을 강제로 먹여서 환각 방지!
                    if len(ref_content) < 200:
                        ref_content = f"기사 핵심 요약: {snippet}"
                        
                    if len(ref_content) > 50:
                        print(f"✅ 팩트 확보 완료: {topic_title}")
                        return f"[최신 기사 팩트]:\n{ref_content}", topic_title, link
                        
        except Exception as e: 
            print(f"⚠️ 네이버 API 에러: {e}")
            
    return "[팩트]: 특별한 뉴스 없음", f"[{category.upper()}] 주요 브리핑", ""

# ==========================================
# 3. AI 이미지 생성 및 글 작성
# ==========================================
def create_photo_prompt(category, topic, ref_content):
    # ⭐️ 의미 없는 자연 풍경화 절대 금지 및 기사 내용 강제 반영
    system_msg = f"""
    당신은 퓰리처상을 받은 보도사진 편집장입니다. 
    다음 최신 기사 내용을 철저히 분석하여, 이 뉴스/이슈를 상징하는 4분할 컷(4-panel photo collage)용 영문 프롬프트를 작성하세요.
    
    [🚨 절대 금지 사항]
    - 기사 내용과 무관한 자연 풍경(산, 바다, 사막, 숲)은 절대로 그리지 마세요!
    - 3D CG, 텍스트(글자), 일러스트레이션 금지.
    
    [필수 포함 사항]
    - IT/주식 기사라면: 도심 빌딩, 스마트폰, 노트북, 전광판, 주식 차트 뉘앙스, 기업 로고 형태 등 비즈니스 환경.
    - 제품 기사라면: 해당 제품의 질감과 사용 환경.
    무조건 8k 해상도의 극사실주의 실사(Photorealistic)로 피사체를 정확히 묘사하세요.
    """
    res = gpt_client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"주제: {topic}\n\n기사 팩트:\n{ref_content[:1500]}"}
        ], 
        temperature=0.7
    )
    return res.choices[0].message.content.strip()

def generate_and_split_images_xai(prompt):
    final_prompt = f"A seamless photo collage of 4 panels in a 2x2 grid. {prompt} Photorealistic, cinematic lighting, no text, no borders."
    try:
        response = xai_client.images.generate(
            model="grok-imagine-image", 
            prompt=final_prompt, 
            extra_body={"aspect_ratio": "1:1", "resolution": "2k"}, 
            n=1
        )
        img_data = requests.get(response.data[0].url).content
        img = Image.open(BytesIO(img_data))
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
                
        print("✅ xAI 이미지 4장 생성 완료!")
        return base64_images
    except Exception as e: 
        print(f"❌ xAI 이미지 생성 실패: {e}")
        return []

def write_blog_post(category, base64_images, ref_content="", topic=""):
    blockquote_style = 'style="border-left: 4px solid #cc0000; padding: 15px 20px; margin: 30px 0; background-color: #fcf8f8; color: #111; font-weight: 800; font-size: 1.1em; border-radius: 0 8px 8px 0;"'
    table_style = 'style="width: 100%; border-collapse: collapse; margin: 30px 0; font-size: 0.95em; font-family: sans-serif; box-shadow: 0 0 20px rgba(0, 0, 0, 0.05); border-radius: 8px; overflow: hidden;"'
    th_style = 'style="background-color: #222; color: #ffffff; text-align: center; padding: 12px 15px; font-weight: bold;"'
    td_style = 'style="padding: 12px 15px; border-bottom: 1px solid #eeeeee; text-align: center; color: #333;"'
    
    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")
    
    # ⭐️ 마크다운(**) 절대 금지 & 분량 강제 프롬프트
    system_prompt = f"""
    당신은 '{category}' 분야의 최고 전문가이자 날카로운 1티어 인플루언서입니다.
    
    🚨 [가장 중요한 금지 규칙]
    1. 마크다운 별표(**) 기호는 절대 사용 금지! 강조할 때는 반드시 HTML <strong>텍스트</strong> 태그만 사용하세요.
    2. 'A사', '모 대기업' 등 익명 처리 절대 금지! 원문에 있는 실제 기업명(애플, 테슬라 등)과 구체적 수치를 100% 그대로 노출하세요.
    3. 글을 짧게 쓰지 마세요. 최소 1500자 이상, 5개 이상의 문단으로 아주 길고 상세하게 팩트를 해설하세요.
    
    [작성 가이드]
    - 오늘({today_str}) 기준의 가장 최신 뉴스 팩트만을 다룹니다.
    - 글의 첫 줄은 반드시 <h2>시선을 확 끄는 도발적인 제목</h2> 형태로 시작하세요.
    - 문단이 끝날 때마다 반드시 <br><br> 태그로 여백을 주세요.
    - 데이터, 수치, 기업 목록 등이 있으면 HTML <table> 태그를 써서 표(Table)로 1개 이상 정리하세요.
    - 글의 핵심 요약 한 줄은 <blockquote {blockquote_style}> 여기에 </blockquote> 로 감싸서 강렬하게 마무리하세요.
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[
            {"role": "system", "content": system_prompt}, 
            {"role": "user", "content": f"주제: {topic}\n\n[분석할 기사 팩트]:\n{ref_content}"}
        ], 
        temperature=0.85
    )
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    title = f"[{category.upper()}] 심층 브리핑"
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()
        
    # ⭐️ 파이썬 강제 사진 분산 배치 로직 (GPT가 실패해도 무조건 사이사이에 들어감)
    if base64_images:
        img_tags = [f'<div style="text-align:center; margin: 40px 0;"><img src="{b64}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 6px 12px rgba(0,0,0,0.15);"></div>' for b64 in base64_images]
        
        # GPT가 지시를 무시했거나 [IMAGE_x] 태그를 빼먹었을 경우를 대비해 본문을 <br><br> 기준으로 쪼갭니다.
        paragraphs = html_content.split('<br><br>')
        
        # 문단이 충분히 길면 사진을 일정 간격으로 흩뿌립니다.
        if len(paragraphs) >= len(img_tags):
            step = len(paragraphs) // len(img_tags)
            new_html = ""
            img_idx = 0
            for i, p in enumerate(paragraphs):
                new_html += p + "<br><br>"
                if i > 0 and i % step == 0 and img_idx < len(img_tags):
                    new_html += img_tags[img_idx] + "<br><br>"
                    img_idx += 1
            # 혹시 남은 사진이 있으면 맨 밑에 추가
            while img_idx < len(img_tags):
                new_html += img_tags[img_idx] + "<br><br>"
                img_idx += 1
            html_content = new_html
        else:
            # 글이 너무 짧으면 어쩔 수 없이 하나씩 번갈아 가며 붙입니다.
            new_html = ""
            for i, p in enumerate(paragraphs):
                new_html += p + "<br><br>"
                if i < len(img_tags):
                    new_html += img_tags[i] + "<br><br>"
            html_content = new_html
                
    return title, html_content

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
    parser.add_argument("--topic", default="")
    args = parser.parse_args()
    
    category = args.category
    if category == "auto":
        hour = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).hour
        mapping = {(7,12,17): "news", (8,13,18): "it", (9,14,19): "stock", (10,15,20): "travel", (11,16,21): "food"}
        category = next((v for k, v in mapping.items() if hour in k), "news")
        
    blog_id = BLOG_REGISTRY.get(category)
    if not blog_id: exit(1)
        
    ref_url = args.reference_url
    if ref_url:
        ref_content, topic, _ = fetch_reference_content(ref_url)
    else:
        ref_content, topic, ref_url = generate_auto_topic(category)
    
    photo_prompt = create_photo_prompt(category, topic, ref_content)
    images = generate_and_split_images_xai(photo_prompt)
    title, html_output = write_blog_post(category, images, ref_content, topic)
    
    if ref_url:
        html_output += f'<br><br><hr><div style="text-align:center; margin-top: 30px;"><p style="font-size: 1.1em; font-weight: bold;">🔗 <a href="{ref_url}" target="_blank" style="color: #0056b3; text-decoration: none;">관련 기사 원문 확인하기</a></p></div>'
        
    try:
        post_url = post_to_blogger(blog_id, title, html_output)
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚡ [{category.upper()}] 심층 포스팅 완료!\n📝 {title}\n👉 {post_url}"})
    except Exception as e:
        print(f"Error: {e}")
