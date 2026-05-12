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
# 2. 크롤링 및 유튜브 자막 추출 (강력한 알맹이 추출!)
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
        # ⭐️ 네이버 등 포털 사이트의 봇 차단을 뚫기 위한 강력한 사람 위장 헤더
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
        
        # ⭐️ 네이버 뉴스 및 주요 언론사 본문을 정확히 타겟팅하여 긁어옵니다.
        article_body = (soup.find('article', id='dic_area') or 
                        soup.find('div', id='dic_area') or 
                        soup.find('div', id='articeBody') or 
                        soup.find('div', id='newsct_article') or 
                        soup.find('div', class_='news_contents') or 
                        soup.find('article'))
        
        if article_body:
            # 불필요한 태그 제거 (광고, 기자 정보 등)
            for el in article_body.find_all(['script', 'style', 'em', 'span']):
                if el.name == 'span' and 'end_photo_org' in el.get('class', []): continue
                el.decompose()
            text_content = article_body.get_text(separator='\n', strip=True)
        else:
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]): script.decompose()
            text_content = soup.get_text(separator='\n', strip=True)
            
        # 넉넉하게 4000자까지 긁어와서 GPT에게 팩트를 가득 먹여줍니다.
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
            params = {"query": query, "display": 3, "sort": "sim"}
            response = requests.get(api_url, headers=headers, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                for item in data.get('items', []):
                    link = item.get('originallink') or item['link']
                    topic_title = html.unescape(re.sub(r'<[^>]+>', '', item['title']))
                    
                    ref_content, _, _ = fetch_reference_content(link)
                    
                    # 텍스트가 짧으면 거르고 알맹이가 꽉 찬 기사만 선별!
                    if len(ref_content) > 300:
                        print(f"✅ 팩트 알맹이 확보 완료: {topic_title}")
                        return ref_content, topic_title, link
                        
        except Exception as e: 
            print(f"⚠️ 네이버 API/크롤링 에러: {e}")
            
    return "오늘의 주요 브리핑 내용입니다.", f"[{category.upper()}] 주요 브리핑", ""

# ==========================================
# 3. AI 이미지 생성 및 글 작성
# ==========================================
def create_photo_prompt(category, topic, ref_content):
    # ⭐️ 다시 4분할(2x2)에 맞춰 프롬프트를 수정했습니다.
    system_msg = f"""
    당신은 퓰리처상을 받은 보도사진 편집장입니다. 
    다음 기사 내용을 분석하여, 이 이슈를 가장 직관적으로 보여주는 4분할 컷(4-panel photo collage)용 영문 프롬프트를 작성하세요.
    - 기사 본문에 등장하는 핵심 키워드(특정 인물, 장소, 기술, 분위기, 상징물 등)를 반드시 시각적으로 묘사할 것.
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
    # ⭐️ 3x2(6장)에서 다시 2x2(4장) 비율(1:1)로 원상복구했습니다. 이미지가 잘리지 않습니다!
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
        
        # 2칸(열), 2칸(행)으로 나눕니다.
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
    
    # ⭐️ 엣지 있는 텍스트 로직은 유지하되 사진만 4장 삽입으로 변경했습니다.
    system_prompt = f"""
    당신은 '{category}' 분야의 최고 전문가이자, 거침없고 날카로운 통찰력을 가진 1티어 인플루언서입니다.
    기계적인 기사 요약은 절대 금지합니다. 독자들이 읽고 무릎을 탁 칠 만한 '엣지 있는 시각'과 '비판적/심층적 분석'을 제공해야 합니다.
    스마트폰 가독성을 극대화하여 1:1 대화체(해요체/합쇼체 혼용)로 작성하세요.
    
    [핵심 지시사항 - 엣지 있는 알맹이 채우기]
    1. [팩트 폭격]: 제공된 기사 원문에서 구체적인 '수치', '통계', '고유명사', '발언'을 절대 누락하지 말고 본문 곳곳에 강력한 근거로 배치하세요.
    2. [날카로운 인사이트]: 이 사건/이슈의 이면에는 어떤 진실이 있는지, 앞으로 우리에게 어떤 영향을 미칠지 본인만의 도발적이고 예리한 의견을 반드시 포함하세요.
    3. [가독성 및 포맷]:
       - 글의 제일 첫 줄에는 반드시 <h2>시선을 확 끄는 도발적인 제목</h2> 형태로 작성하세요.
       - 문단이 끝날 때마다 반드시 <br><br> 태그를 넣어 여백을 넉넉하게 주세요.
       - 중요한 팩트나 강조할 문장은 <strong> 텍스트 </strong> 태그를 사용해 시각적으로 돋보이게 하세요.
    4. ⭐️ 본문 내용 흐름에 맞춰 중간중간에 [IMAGE_1], [IMAGE_2], [IMAGE_3], [IMAGE_4] 라는 텍스트를 문맥에 맞게 골고루 흩뿌려서 배치하세요.
    5. 글의 마무리나 가장 뼈때리는 핵심 요약 한 줄은 <blockquote {blockquote_style}> 여기에 </blockquote> 로 감싸서 강렬하게 마무리하세요.
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[
            {"role": "system", "content": system_prompt}, 
            {"role": "user", "content": f"주제: {topic}\n\n[분석할 기사 원문 팩트]:\n{ref_content}"}
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
