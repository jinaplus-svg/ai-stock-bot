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
# 2. 크롤링 및 유튜브 자막 추출 (알맹이 추출 강화!)
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
        
        return f"[유튜브 자막 내용]:\n{transcript_text[:3500]}", title, url
    except Exception as e:
        print(f"⚠️ 유튜브 자막 추출 실패: {e}")
        return "자막을 읽을 수 없는 영상입니다.", "유튜브 영상", url

def fetch_reference_content(url):
    if not url: return "", "", ""
    if "youtube.com" in url or "youtu.be" in url:
        return get_youtube_content(url)
        
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title = (soup.find('meta', property='og:title') or soup.find('meta', name='title') or soup.title).get('content', soup.title.text if soup.title else "참조")
        
        # ⭐️ 기사 본문(알맹이)만 쏙 빼내는 로직 (쓸데없는 메뉴/광고 텍스트 제외)
        article_body = soup.find('div', id='dic_area') or soup.find('div', id='articeBody') or soup.find('div', class_='news_contents') or soup.find('article')
        
        if article_body:
            text_content = article_body.get_text(separator=' ', strip=True)
        else:
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]): script.decompose()
            text_content = soup.get_text(separator=' ', strip=True)
            
        return f"[본문 핵심 내용]: {text_content[:3500]}", title, url
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
            params = {"query": query, "display": 3, "sort": "sim"} # 관련도 높은 기사 3개 검색
            response = requests.get(api_url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                for item in data.get('items', []):
                    link = item.get('originallink') or item['link']
                    topic_title = html.unescape(re.sub(r'<[^>]+>', '', item['title']))
                    
                    # ⭐️ 단순히 요약만 가져오지 않고, 실제 기사 링크로 들어가서 3500자를 긁어옵니다!
                    ref_content, _, _ = fetch_reference_content(link)
                    
                    # 알맹이가 충분히 있는 기사를 찾으면 즉시 채택!
                    if len(ref_content) > 300:
                        print(f"✅ 알맹이 확보 완료: {topic_title}")
                        return ref_content, topic_title, link
                        
        except Exception as e: 
            print(f"⚠️ 네이버 API/크롤링 에러: {e}")
            
    return "오늘의 주요 브리핑 내용입니다.", f"[{category.upper()}] 주요 브리핑", ""

# ==========================================
# 3. AI 이미지 생성 및 글 작성
# ==========================================
def create_photo_prompt(category, topic, ref_content):
    system_msg = f"당신은 보도사진 편집장입니다. 주제 '{topic}'와 관련된 영문 이미지 프롬프트를 작성하세요. 3D CG 절대 금지. 무조건 고화질 실사(Photorealistic)."
    res = gpt_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": system_msg}], temperature=0.8)
    return res.choices[0].message.content.strip()

def generate_and_split_images_xai(prompt):
    final_prompt = f"A photo collage of 4 panels in 2x2 grid. {prompt} Photorealistic, natural scenes, no text."
    try:
        response = xai_client.images.generate(model="grok-imagine-image", prompt=final_prompt, extra_body={"aspect_ratio": "1:1", "resolution": "2k"}, n=1)
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
    blockquote_style = 'style="border-left: 4px solid #cc0000; padding: 10px 15px; margin: 25px 0; background-color: #fff5f5; color: #333; font-weight: bold; border-radius: 0 8px 8px 0;"'
    
    # ⭐️ GPT에게 수치와 팩트를 넣어 깊이 있는 '알맹이'를 쓰도록 강력하게 지시합니다!
    system_prompt = f"""
    당신은 '{category}' 분야의 수석 에디터이자 심층 분석 블로거입니다. 스마트폰 가독성을 극대화하여 1:1 대화체로 작성하세요.
    
    [핵심 지시사항 - 알맹이 채우기]
    1. 제공된 [내용]의 팩트, 수치, 구체적인 사실을 절대 누락하지 마세요. 
    2. 단순 요약이 아니라, 독자가 얻어갈 수 있는 '인사이트'나 '깊이 있는 해설'을 덧붙여 풍성하게(최소 1000자 이상) 작성하세요.
    3. 글의 제일 첫 줄에는 반드시 <h2>여기에 시선을 끄는 제목</h2> 형태로 제목을 작성하세요.
    4. 문단이 끝날 때마다 반드시 <br><br> 태그를 넣어 줄바꿈을 넉넉하게 하세요.
    5. 본문 중간중간에 [IMAGE_1], [IMAGE_2], [IMAGE_3], [IMAGE_4] 라는 텍스트를 정확하게 흩뿌려서 배치하세요.
    6. 중요한 핵심 문장이나 인용구는 <blockquote {blockquote_style}> 여기에 </blockquote> 로 감싸주세요.
    """
    
    res = gpt_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"주제: {topic}\n\n분석할 알맹이 내용:\n{ref_content}"}], temperature=0.85)
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    title = f"[{category.upper()}] 심층 브리핑"
    
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()
        
    if base64_images:
        for i, b64 in enumerate(base64_images):
            img_tag = f'<div style="text-align:center; margin: 40px 0;"><img src="{b64}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);"></div>'
            
            if f"[IMAGE_{i+1}]" in html_content:
                html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
            else:
                html_content += f"<br>{img_tag}"
                
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
        html_output += f'<br><br><hr><div style="text-align:center;"><p>🔗 <a href="{ref_url}" target="_blank">관련 상세 기사 보러가기</a></p></div>'
        
    try:
        post_url = post_to_blogger(blog_id, title, html_output)
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚡ [{category.upper()}] 심층 포스팅 완료!\n📝 {title}\n👉 {post_url}"})
    except Exception as e:
        print(f"Error: {e}")