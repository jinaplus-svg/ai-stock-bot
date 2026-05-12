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
from youtube_transcript_api import YouTubeTranscriptApi

# ==========================================
# 1. 설정 및 API 키 로드
# ==========================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
XAI_API_KEY = os.environ.get("XAI")
GOOGLE_OAUTH_TOKEN_STR = os.environ.get("GOOGLE_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# ⭐️ Tavily API 키 로드 (시크릿에 있는 키 사용)
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

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
# 2. 강력한 Tavily AI 검색 엔진
# ==========================================
def fetch_reference_content(url):
    # 유튜브 링크 처리 유지
    if not url: return "", "", ""
    if "youtube.com" in url or "youtu.be" in url:
        try:
            video_id = url.split("/")[-1].split("?")[0] if "youtu.be" in url else re.search(r"v=([a-zA-Z0-9_-]+)", url).group(1)
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
            transcript_text = " ".join([item['text'] for item in transcript_list])
            return f"[유튜브 스크립트]:\n{transcript_text[:4000]}", "유튜브 분석", url
        except:
            return "자막 추출 실패", "유튜브", url
            
    # 일반 URL이 직접 들어오면 Tavily로 해당 URL의 본문을 긁어옴
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

def generate_auto_topic_tavily(category):
    print(f"🤖 [{category.upper()}] Tavily AI 검색 엔진으로 봇 차단 없이 기사 원문 추출 중...")
    
    if not TAVILY_API_KEY:
        print("⚠️ TAVILY_API_KEY가 설정되지 않았습니다.")
        return "API 키 누락", "키 설정 확인", ""

    # Tavily 전용 검색 쿼리 (정확도 극대화)
    search_queries = {
        "news": "오늘 한국 주요 속보 정치 사회 뉴스", 
        "it": "오늘 IT 테크 기술 신제품 트렌드 뉴스", 
        "stock": "오늘 주식 증시 특징주 경제 시황 뉴스", 
        "food": "오늘 최신 외식 식품 맛집 트렌드", 
        "travel": "최신 국내외 여행 관광 트렌드 뉴스"
    }
    query = search_queries.get(category, "오늘 핫이슈 뉴스")
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced", # 심층 검색
        "include_raw_content": True, # HTML 태그 없는 깨끗한 본문 전체 추출
        "max_results": 3,
        "topic": "news" # 뉴스 카테고리 고정
    }
    
    try:
        response = requests.post("https://api.tavily.com/search", json=payload, headers=headers, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            for result in data.get('results', []):
                title = result.get('title', '제목 없음')
                url = result.get('url', '')
                # raw_content(전체 본문)가 있으면 우선 사용, 없으면 content(요약) 사용
                raw_content = result.get('raw_content', '')
                content = result.get('content', '')
                
                final_content = raw_content if len(raw_content) > 300 else content
                
                # 확실한 알맹이가 있는 기사만 통과!
                if len(final_content) > 400:
                    print(f"✅ Tavily 팩트 확보 완료: {title}")
                    return f"[Tavily AI 추출 기사 원문]:\n{final_content[:4000]}", title, url
                    
            print("⚠️ 검색은 성공했으나, 본문이 긴 기사가 없습니다.")
        else:
            print(f"⚠️ Tavily API 호출 실패: {response.status_code}")
            
    except Exception as e:
        print(f"⚠️ Tavily 검색 중 에러: {e}")
            
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
        model="gpt-4o", 
        messages=[
            {"role": "system", "content": system_prompt}, 
            {"role": "user", "content": f"주제: {topic}\n\n[오늘자 최신 기사 팩트 원문]:\n{ref_content}"}
        ], 
        temperature=0.85
    )
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    title = f"[{category.upper()}] 심층 분석 칼럼"
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()
        
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
        # ⭐️ 크롤링 차단 없는 완벽한 Tavily 엔진 호출!
        ref_content, topic, ref_url = generate_auto_topic_tavily(category)
    
    photo_prompt = create_photo_prompt(category, topic, ref_content)
    images = generate_and_split_images_xai(photo_prompt)
    title, html_output = write_blog_post(category, images, ref_content, topic)
    
    if ref_url:
        html_output += f'<br><br><hr><div style="text-align:center; margin-top: 30px;"><p style="font-size: 1.1em; font-weight: bold;">🔗 <a href="{ref_url}" target="_blank" style="color: #0056b3; text-decoration: none;">기사 원문 보기</a></p></div>'
        
    try:
        post_url = post_to_blogger(blog_id, title, html_output)
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚡ [{category.upper()}] 심층 분석 칼럼 발행 완료!\n📝 {title}\n👉 {post_url}"})
    except Exception as e:
        print(f"Error: {e}")
