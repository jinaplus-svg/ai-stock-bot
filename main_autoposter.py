import os
import json
import argparse
import base64
import requests
import xml.etree.ElementTree as ET
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
# 2. 강력한 크롤링 & 구글 글로벌 뉴스 엔진
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
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title = (soup.find('meta', property='og:title') or soup.find('meta', name='title') or soup.title).get('content', soup.title.text if soup.title else "참조 기사")
        
        # 쓸데없는 태그 제거
        for script in soup(["script", "style", "nav", "footer", "header", "aside", "form"]): 
            script.decompose()
            
        # 모든 p 태그를 긁어서 실제 '알맹이 문장'만 조립 (봇 차단 회피)
        paragraphs = soup.find_all('p')
        text_content = ""
        if paragraphs:
            valid_p = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30]
            text_content = '\n'.join(valid_p)
            
        if len(text_content) < 200:
            text_content = soup.get_text(separator='\n', strip=True)
            
        return text_content[:4000], title, url
    except Exception as e:
        print(f"⚠️ 크롤링 에러: {e}")
        return "", "", url

def generate_auto_topic_google_news(category):
    print(f"🤖 [{category.upper()}] 구글 글로벌 뉴스(RSS) 엔진으로 최신 기사 탐색 중...")
    
    # 구글 뉴스 검색어 세팅 (최근 1일 이내 데이터만)
    search_queries = {
        "news": "사회 OR 정치 OR 속보 when:1d", 
        "it": "IT OR 테크 OR 애플 OR 삼성 OR AI when:1d", 
        "stock": "증시 OR 주가 OR 실적발표 OR 특징주 when:1d", 
        "food": "맛집 OR 식품 OR 외식 트렌드 when:1d", 
        "travel": "여행 OR 항공 OR 관광 when:1d"
    }
    query = search_queries.get(category, "핫이슈 when:1d")
    
    # 네이버 대신 구글 뉴스 RSS 활용 (차단 위험 낮고, 양질의 글로벌/국내 뉴스 확보)
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        response = requests.get(rss_url, timeout=10)
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        for item in items[:5]: # 상위 5개 최신 기사 확인
            topic_title = item.find('title').text
            link = item.find('link').text
            
            # 구글 뉴스 리다이렉트 링크에서 원본 기사 추출
            ref_content, _, final_url = fetch_reference_content(link)
            
            # 본문이 400자 이상 확보된 진짜 '알맹이 있는 기사'만 채택!
            if len(ref_content) > 400:
                print(f"✅ 구글 뉴스 팩트 확보 완료: {topic_title}")
                return f"[구글 뉴스 최신 팩트]:\n{ref_content}", topic_title, final_url
                
    except Exception as e:
        print(f"⚠️ 구글 뉴스 RSS 에러: {e}")
            
    return "[팩트]: 최근 유의미한 뉴스를 찾지 못했습니다.", f"[{category.upper()}] 주요 브리핑", ""

# ==========================================
# 3. AI 이미지 생성 및 글 작성
# ==========================================
def create_photo_prompt(category, topic, ref_content):
    system_msg = f"""
    당신은 퓰리처상을 받은 보도사진 편집장입니다. 
    다음 최신 기사 내용을 철저히 분석하여, 이 뉴스/이슈의 핵심 장면을 가장 직관적이고 상징적으로 보여주는 4분할 컷(4-panel photo collage)용 영문 프롬프트를 작성하세요.
    - 기업명, 신기술, 경제 상황(상승/하락)의 뉘앙스를 시각적으로 정확히 묘사할 것. (자연 풍경 절대 금지)
    - 3D CG, 일러스트레이션 절대 금지. 무조건 8k 해상도의 극사실주의 실사(Photorealistic)로 묘사할 것.
    - 텍스트나 글자는 사진에 포함되지 않게 할 것.
    """
    res = gpt_client.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"주제: {topic}\n\n기사 팩트:\n{ref_content[:1500]}"}], 
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
    blockquote_style = 'style="border-left: 4px solid #0056b3; padding: 15px 20px; margin: 30px 0; background-color: #f4f8fc; color: #111; font-weight: 800; font-size: 1.1em; border-radius: 0 8px 8px 0;"'
    table_style = 'style="width: 100%; border-collapse: collapse; margin: 30px 0; font-size: 0.95em; font-family: sans-serif; box-shadow: 0 0 20px rgba(0, 0, 0, 0.05); border-radius: 8px; overflow: hidden;"'
    th_style = 'style="background-color: #1a202c; color: #ffffff; text-align: center; padding: 12px 15px; font-weight: bold;"'
    td_style = 'style="padding: 12px 15px; border-bottom: 1px solid #edf2f7; text-align: center; color: #2d3748;"'
    
    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")
    
    # ⭐️ "월가 애널리스트" 빙의! 극강의 엣지를 위한 프롬프트 개조
    system_prompt = f"""
    당신은 실리콘밸리 탑티어 애널리스트이자, 대중들에게 팩트 폭격을 날리는 100만 구독자 칼럼니스트입니다.
    언론사의 기계적인 요약은 쓰레기통에 버리세요. 독자가 진짜 원하는 건 "그래서 이게 무슨 꿍꿍이인데?", "결국 누가 돈을 벌고 누가 망하는데?" 같은 날카롭고 뼈때리는 '인사이트'입니다.
    
    🚨 [절대 규칙]
    1. 마크다운 별표(**) 기호는 절대 사용 금지! 강조할 때는 무조건 HTML <strong>텍스트</strong> 태그만 쓰세요.
    2. 'A사', 'B기업' 같은 촌스러운 익명 처리 절대 금지. 삼성전자, 애플, 테슬라 등 100% 실제 기업명과 실명을 그대로 쓰세요.
    3. 어조는 전문가다운 확신에 찬 1:1 대화체(해요체/합쇼체 혼용)입니다.
    
    [칼럼 작성 구조 - 이대로 작성하세요]
    - 첫 줄: <h2>시선을 확 끄는 도발적이고 직관적인 제목</h2>
    - [도입부]: "오늘({today_str}) 이런 뉴스가 터졌습니다."라며 원문의 팩트와 수치를 던지며 시선 집중.
    - [숨겨진 진실/분석]: 언론에서 말하지 않는 이면의 진실, 이 사태가 벌어진 진짜 이유를 날카롭게 파헤치기.
    - [팩트 체크 표]: 원문에 있는 중요한 수치, 관련 기업, 등락률 등을 HTML <table> 태그로 가독성 있게 정리.
       <table {table_style}>
         <thead><tr><th {th_style}>항목1</th><th {th_style}>항목2</th></tr></thead>
         <tbody><tr><td {td_style}>데이터</td><td {td_style}>수치</td></tr></tbody>
       </table>
    - [결론/예측]: "결론적으로 우리는 이렇게 대비해야 합니다"라는 본인만의 확고한 전망. 가장 핵심 문장 하나를 <blockquote {blockquote_style}> 여기에 </blockquote> 로 감싸기.
    
    * 문단 사이에는 무조건 <br><br>를 넣어 여백을 넉넉하게 줍니다.
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-4o", # ⭐️ 추론 능력이 더 뛰어난 모델로 글의 퀄리티를 한 단계 올림
        messages=[
            {"role": "system", "content": system_prompt}, 
            {"role": "user", "content": f"주제: {topic}\n\n[오늘자 글로벌 최신 기사 팩트 원문]:\n{ref_content}"}
        ], 
        temperature=0.85
    )
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    title = f"[{category.upper()}] 심층 분석 칼럼"
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()
        
    # 파이썬 강제 사진 분산 배치 로직 (절대 밑에 뭉치지 않음)
    if base64_images:
        img_tags = [f'<div style="text-align:center; margin: 40px 0;"><img src="{b64}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 8px 16px rgba(0,0,0,0.1);"></div>' for b64 in base64_images]
        paragraphs = html_content.split('<br><br>')
        
        if len(paragraphs) >= len(img_tags):
            step = max(1, len(paragraphs) // len(img_tags))
            new_html = ""
            img_idx = 0
            for i, p in enumerate(paragraphs):
                new_html += p + "<br><br>"
                if i > 0 and i % step == 0 and img_idx < len(img_tags):
                    new_html += img_tags[img_idx] + "<br><br>"
                    img_idx += 1
            while img_idx < len(img_tags):
                new_html += img_tags[img_idx] + "<br><br>"
                img_idx += 1
            html_content = new_html
        else:
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
        # 네이버 대신 구글 뉴스 엔진 호출!
        ref_content, topic, ref_url = generate_auto_topic_google_news(category)
    
    photo_prompt = create_photo_prompt(category, topic, ref_content)
    images = generate_and_split_images_xai(photo_prompt)
    title, html_output = write_blog_post(category, images, ref_content, topic)
    
    if ref_url:
        html_output += f'<br><br><hr><div style="text-align:center; margin-top: 30px;"><p style="font-size: 1.1em; font-weight: bold;">🔗 <a href="{ref_url}" target="_blank" style="color: #0056b3; text-decoration: none;">관련 글로벌/국내 기사 원문 보기</a></p></div>'
        
    try:
        post_url = post_to_blogger(blog_id, title, html_output)
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚡ [{category.upper()}] 심층 분석 칼럼 발행 완료!\n📝 {title}\n👉 {post_url}"})
    except Exception as e:
        print(f"Error: {e}")
