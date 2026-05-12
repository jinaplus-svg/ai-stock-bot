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
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]): script.decompose()
            text_content = soup.get_text(separator='\n', strip=True)
            
        return f"[기사/본문 핵심 팩트 원문]:\n{text_content[:4000]}", title, url
    except Exception as e:
        print(f"⚠️ 크롤링 에러: {e}")
        return "", "", url

def generate_auto_topic(category):
    print(f"🤖 [{category.upper()}] 네이버 API 검색 및 기사 본문 심층 분석 중...")
    search_queries = {"news": "사회 속보", "it": "IT 신기술 트렌드", "stock": "증시 주식 특징주", "food": "인기 맛집 핫플", "travel": "여행 가볼만한곳 추천 숙소"}
    query = search_queries.get(category, "핫이슈")
    
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
                    
                    ref_content, _, _ = fetch_reference_content(link)
                    
                    if len(ref_content) > 300:
                        print(f"✅ 팩트 알맹이 확보 완료 (최신 기사): {topic_title}")
                        return ref_content, topic_title, link
                        
        except Exception as e: 
            print(f"⚠️ 네이버 API/크롤링 에러: {e}")
            
    return "오늘의 주요 브리핑 내용입니다.", f"[{category.upper()}] 주요 브리핑", ""

# ==========================================
# 3. AI 이미지 생성 및 글 작성
# ==========================================
def create_photo_prompt(category, topic, ref_content):
    system_msg = f"""
    당신은 퓰리처상을 받은 보도사진 편집장입니다. 
    다음 최신 기사 내용을 철저히 분석하여, 이 뉴스/이슈의 핵심 장면을 가장 직관적이고 상징적으로 보여주는 4분할 컷(4-panel photo collage)용 영문 프롬프트를 작성하세요.
    
    [필수 지시사항]
    - 기사 본문에 특정 인물, 기업, 장소, 기술, 제품, 경제 상황(상승/하락)이 등장한다면 그 특징을 정확히 시각화하여 프롬프트에 반영할 것. 
    - 3D CG, 일러스트레이션 절대 금지. 무조건 8k 해상도의 극사실주의 실사(Photorealistic)로 묘사할 것.
    - 텍스트나 글자는 사진에 포함되지 않게 할 것.
    """
    res = gpt_client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"주제: {topic}\n\n기사 핵심 내용:\n{ref_content[:1500]}"}
        ], 
        temperature=0.7
    )
    return res.choices[0].message.content.strip()

def generate_and_split_images_xai(prompt):
    final_prompt = f"A seamless photo collage of 4 panels in a 2x2 grid. {prompt} Photorealistic, cinematic lighting, natural scenes, no text, no borders."
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
    
    # ⭐️ "A사, B사 금지" 및 "실제 이름과 수치 무조건 사용" 명령 추가!
    system_prompt = f"""
    당신은 '{category}' 분야의 최고 전문가이자, 거침없고 날카로운 통찰력을 가진 1티어 인플루언서입니다.
    스마트폰 가독성을 극대화하여 1:1 대화체(해요체/합쇼체 혼용)로 작성하세요.
    
    [핵심 지시사항 - 엣지 있는 팩트 폭격 & 표 삽입]
    1. 🚨 [익명 처리 절대 금지 & 리얼한 팩트 노출]: 기사에 등장하는 기업명을 절대로 'A사', 'B사', '모 대기업' 등으로 뭉뚱그려 익명 처리하지 마세요! 
       원문에 있는 **실제 기업명(예: 삼성전자, 애플 등), 정확한 실명, 실제 수치(매출액, 주가, 퍼센트, 날짜 등)**를 가감 없이 100% 리얼하고 객관적으로 그대로 작성하세요.
    2. [최신 트렌드 & 날카로운 인사이트]: 방금 나온 최신 뉴스입니다. 객관적 팩트를 바탕으로, 이 사건의 이면이나 향후 전망에 대해 본인만의 도발적이고 예리한 의견을 덧붙이세요.
    3. [시각적 자료(표) 필수 활용]: 수치, 비교 데이터, 일정, 관련주/기업 목록 등은 반드시 HTML <table> 태그를 사용하여 가독성 높은 표로 1개 이상 정리하세요.
       (표 스타일 가이드 적용 필수):
       <table {table_style}>
         <thead><tr><th {th_style}>항목1</th><th {th_style}>항목2</th></tr></thead>
         <tbody><tr><td {td_style}>실제 기업명/데이터</td><td {td_style}>정확한 수치</td></tr></tbody>
       </table>
    4. [가독성 및 포맷]:
       - 글의 첫 줄은 <h2>시선을 확 끄는 도발적인 제목</h2> 형태로 작성하세요.
       - 문단이 끝날 때마다 반드시 <br><br> 태그를 넣어 여백을 넉넉하게 주세요.
       - 중요한 실제 기업명이나 핵심 수치는 <strong> 텍스트 </strong> 로 강조하세요.
    5. 본문 내용 흐름에 맞춰 [IMAGE_1], [IMAGE_2], [IMAGE_3], [IMAGE_4] 텍스트를 문맥에 맞게 골고루 흩뿌려서 배치하세요.
    6. 글의 뼈때리는 핵심 요약 한 줄은 <blockquote {blockquote_style}> 여기에 </blockquote> 로 감싸서 강렬하게 마무리하세요.
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[
            {"role": "system", "content": system_prompt}, 
            {"role": "user", "content": f"주제: {topic}\n\n[분석할 최신 기사 원문 팩트]:\n{ref_content}"}
        ], 
        temperature=0.85
    )
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    title = f"[{category.upper()}] 심층 브리핑"
    
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()
        
    if base64_images:
        for i, b64 in enumerate(base64_images):
            img_tag = f'<div style="text-align:center; margin: 40px 0;"><img src="{b64}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 6px 12px rgba(0,0,0,0.15);"></div>'
            
            if f"[IMAGE_{i+1}]" in html_content:
                html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
            else:
                html_content += f"<br><br>{img_tag}"
                
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
        html_output += f'<br><br><hr><div style="text-align:center; margin-top: 30px;"><p style="font-size: 1.1em; font-weight: bold;">🔗 <a href="{ref_url}" target="_blank" style="color: #0056b3; text-decoration: none;">관련 상세 기사 원문 보러가기</a></p></div>'
        
    try:
        post_url = post_to_blogger(blog_id, title, html_output)
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚡ [{category.upper()}] 엣지있는 심층 포스팅 완료!\n📝 {title}\n👉 {post_url}"})
    except Exception as e:
        print(f"Error: {e}")
