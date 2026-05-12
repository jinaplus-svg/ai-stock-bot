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
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

BLOG_REGISTRY = {
    "it": os.environ.get("IT_BLOG_ID"),
    "food": os.environ.get("FOOD_BLOG_ID"),
    "news": os.environ.get("NEWS_BLOG_ID"),
    "stock": os.environ.get("STOCK_BLOG_ID"),
    "travel": os.environ.get("TRAVEL_BLOG_ID")
}

gpt_client = OpenAI(api_key=OPENAI_API_KEY)
xai_client = OpenAI(api_key=XAI_API_KEY, base_url="[https://api.x.ai/v1](https://api.x.ai/v1)")
SCOPES = ['[https://www.googleapis.com/auth/blogger](https://www.googleapis.com/auth/blogger)']

# ==========================================
# 2. 강력한 Tavily AI 검색 엔진 (뉴스 탐색 최적화)
# ==========================================
def fetch_reference_content(url):
    if not url: return "", "", ""
    if "youtube.com" in url or "youtu.be" in url:
        try:
            video_id = url.split("/")[-1].split("?")[0] if "youtu.be" in url else re.search(r"v=([a-zA-Z0-9_-]+)", url).group(1)
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
            transcript_text = " ".join([item['text'] for item in transcript_list])
            return f"[유튜브 스크립트]:\n{transcript_text[:4000]}", "유튜브 분석", url
        except:
            return "자막 추출 실패", "유튜브", url
            
    if TAVILY_API_KEY:
        try:
            payload = {"api_key": TAVILY_API_KEY, "query": url, "search_depth": "advanced", "include_raw_content": True}
            res = requests.post("[https://api.tavily.com/search](https://api.tavily.com/search)", json=payload, timeout=20)
            if res.status_code == 200:
                data = res.json()
                if data.get("results"):
                    content = data["results"][0].get("raw_content") or data["results"][0].get("content")
                    return content[:4000], data["results"][0].get("title", "참고 기사"), url
        except Exception as e:
            print(f"URL 추출 에러: {e}")
    return "", "", url

def generate_auto_topic_tavily(category):
    print(f"🤖 [{category.upper()}] Tavily AI 검색 엔진으로 봇 차단 없이 최신 기사 원문 추출 중...")
    
    if not TAVILY_API_KEY:
        print("⚠️ TAVILY_API_KEY가 설정되지 않았습니다.")
        return "", "", ""

    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")

    # ⭐️ 주말/휴일 등 뉴스가 없는 날을 대비해 검색어를 더 스마트하게 구성
    search_queries = {
        "news": f"{today_str} 한국 주요 정치 사회 핫이슈 뉴스", 
        "it": f"{today_str} IT 테크 AI 신제품 혁신 기술 뉴스", 
        "stock": f"{today_str} 주식 증시 경제 특징주 기업 실적 뉴스", 
        "food": f"최신 한국 외식 식품 프랜차이즈 트렌드", 
        "travel": f"최신 국내외 여행 관광 항공 핫플 트렌드"
    }
    query = search_queries.get(category, f"{today_str} 주요 핫이슈")
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced", 
        "include_raw_content": True, 
        "max_results": 5, 
        "topic": "news", 
        "days": 3 # ⭐️ 1일로 하면 주말에 뉴스가 없을 수 있으니 3일 내 특급 기사로 보장!
    }
    
    try:
        response = requests.post("[https://api.tavily.com/search](https://api.tavily.com/search)", json=payload, headers=headers, timeout=20)
        
        if response.status_code == 200:
            data = response.json()
            for result in data.get('results', []):
                title = result.get('title', '제목 없음')
                url = result.get('url', '')
                raw_content = result.get('raw_content', '')
                content = result.get('content', '')
                
                final_content = raw_content if len(raw_content) > 300 else content
                
                # ⭐️ 본문이 500자 이상 확보된 확실한 기사만 선택!
                if len(final_content) > 500:
                    print(f"✅ Tavily 최신 팩트 확보 완료: {title}")
                    return f"[Tavily AI 추출 최신 기사 원문]:\n{final_content[:4000]}", title, url
                    
            print("⚠️ 조건에 맞는 충분히 긴 기사를 찾지 못했습니다.")
        else:
            print(f"⚠️ Tavily API 호출 실패: {response.status_code}")
            
    except Exception as e:
        print(f"⚠️ Tavily 검색 중 에러: {e}")
            
    return "", "", ""

# ==========================================
# 3. AI 이미지 생성 및 글 작성
# ==========================================
def create_photo_prompt(category, topic, ref_content):
    system_msg = f"""
    당신은 퓰리처상을 받은 보도사진 편집장입니다. 
    다음 최신 기사 내용을 철저히 분석하여, 이 뉴스/이슈의 핵심 장면을 가장 직관적이고 상징적으로 보여주는 4분할 컷(4-panel photo collage)용 영문 프롬프트를 작성하세요.
    - 기업명, 신기술, 경제 상황(상승/하락)의 뉘앙스를 시각적으로 정확히 묘사할 것. (자연 풍경 절대 금지)
    - 3D CG, 일러스트레이션 금지. 8k 해상도의 극사실주의 실사(Photorealistic)로 묘사할 것.
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
    blockquote_style = 'style="border-left: 5px solid #d32f2f; padding: 18px 25px; margin: 35px 0; background-color: #fff9f9; color: #111; font-weight: 800; font-size: 1.15em; border-radius: 0 10px 10px 0; line-height: 1.6;"'
    table_style = 'style="width: 100%; border-collapse: collapse; margin: 35px 0; font-size: 0.95em; font-family: sans-serif; box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05); border-radius: 8px; overflow: hidden;"'
    th_style = 'style="background-color: #1a202c; color: #ffffff; text-align: center; padding: 14px 15px; font-weight: bold;"'
    td_style = 'style="padding: 14px 15px; border-bottom: 1px solid #edf2f7; text-align: center; color: #2d3748; font-weight: 500;"'
    
    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")
    
    # ⭐️ 초일류 유튜버/블로거 빙의 강력 프롬프트
    system_prompt = f"""
    당신은 한국 최고의 탑티어 비즈니스/IT 트렌드 블로거이자 100만 유튜버 수준의 스토리텔러입니다. (예: 슈카월드, 삼프로TV 스타일)
    절대 기계적인 기사 요약이나 딱딱한 뉴스처럼 쓰지 마세요. 독자가 옆에서 흥미진진한 썰을 듣는 것처럼 '재미있고 엣지있게' 풀어내야 합니다.
    
    🚨 [초강력 금지 규칙 - 반드시 지킬 것!]
    1. "markdown", "```html", "```" 같은 코드 블록 기호나 마크다운 문법(**, # 등)은 절대 출력하지 마세요! 오직 순수 HTML 태그와 텍스트로만 대답하세요.
    2. 'A사', 'B사' 같은 익명 처리 절대 금지! 100% 실제 기업명, 인물명, 금액, 퍼센트 수치를 당당하게 그대로 쓰세요.
    3. 글이 짧으면 안 됩니다. 최소 2000자 이상, 7~8개의 문단으로 아주 풍성하고 깊이 있게 썰을 푸세요.
    
    [완벽한 칼럼 포스팅 구조]
    - 첫 줄: <h2>시선을 훅 끄는 도발적이고 재미있는 제목</h2>
    - [도입부 - 어그로 끌기]: "여러분, 혹시 오늘 이 난리 난 소식 들으셨나요?" 처럼 독자의 호기심을 극도로 자극하며 시작. 사건의 발단을 재미있게 설명.
    - [본론 1 - 팩트 폭격]: 뉴스 원문에 있는 구체적 수치, 통계, 발언을 나열하며 사건의 스케일을 짚어줍니다.
    - [본론 2 - 이면의 진실]: 언론에서 대충 넘어가는 진짜 속내, "도대체 왜 이런 일이 벌어졌을까?"에 대한 날카로운 뇌피셜과 분석.
    - [시각적 자료 - 표]: 원문의 핵심 수치, 비교 데이터, 관련주 등을 반드시 1개 이상의 HTML <table> 태그로 깔끔하게 정리. (스타일 가이드 적용)
       <table {table_style}>
         <thead><tr><th {th_style}>항목1</th><th {th_style}>항목2</th></tr></thead>
         <tbody><tr><td {td_style}>실제 데이터</td><td {td_style}>실제 수치</td></tr></tbody>
       </table>
    - [결론 - 그래서 우리는?]: "결론적으로 우리는 이렇게 대비해야 합니다"라는 뼈때리는 통찰과 조언.
    - 마지막 줄: 글을 관통하는 가장 엣지있는 한 줄 요약을 <blockquote {blockquote_style}> 여기에 </blockquote> 로 감싸서 강렬하게 마무리.
    
    [HTML 가독성 및 이미지 배치 규칙]
    - 문단과 문단 사이는 반드시 <br><br> 태그를 넣어 여백을 시원하게 주세요.
    - 중요한 단어나 숫자는 <strong style="color:#d32f2f;">텍스트</strong> 로 붉은색 강조를 주세요.
    - [IMAGE_1], [IMAGE_2], [IMAGE_3], [IMAGE_4] 텍스트를 글의 흐름(서론, 본론, 결론)에 맞춰 골고루 흩뿌리세요. 한 곳에 몰려있으면 절대 안 됩니다.
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-4o", 
        messages=[
            {"role": "system", "content": system_prompt}, 
            {"role": "user", "content": f"주제: {topic}\n\n[오늘자({today_str}) 최신 특급 기사 팩트 원문]:\n{ref_content}"}
        ], 
        temperature=0.85
    )
    
    # ⭐️ 지긋지긋한 마크다운 찌꺼기 완벽 청소 로직
    html_content = res.choices[0].message.content.strip()
    
    # ```html, ```markdown, ``` 등의 코드블럭 마커 완전 제거
    html_content = re.sub(r'```[a-zA-Z]*\n?', '', html_content)
    html_content = html_content.replace('```', '')
    
    # 텍스트 앞에 간혹 붙는 markdown 글자 제거
    if html_content.lower().startswith('markdown'):
        html_content = html_content[8:].strip()
    if html_content.lower().startswith('html'):
        html_content = html_content[4:].strip()
        
    # ** 굵은 글씨 마크다운 찌꺼기 제거 (안전장치)
    html_content = html_content.replace('**', '')

    # 제목 추출 및 정리
    title = f"[{category.upper()}] 스페셜 브리핑"
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip()
        title = title.replace('*', '').replace('#', '') 
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()
        
    # 파이썬 강제 사진 분산 배치 (글이 길어져서 훨씬 자연스럽게 박힙니다)
    if base64_images:
        img_tags = [f'<div style="text-align:center; margin: 45px 0;"><img src="{b64}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 10px 20px rgba(0,0,0,0.12);"></div>' for b64 in base64_images]
        
        # 만약 GPT가 [IMAGE_X] 태그를 충실히 넣었다면 치환
        for i, tag in enumerate(img_tags):
            marker = f"[IMAGE_{i+1}]"
            if marker in html_content:
                html_content = html_content.replace(marker, tag)
            else:
                # 안 넣었으면 파이썬이 강제로 징검다리 배치
                paragraphs = html_content.split('<br><br>')
                if len(paragraphs) > 2:
                    insert_idx = (len(paragraphs) // len(img_tags)) * i
                    if insert_idx < len(paragraphs):
                        paragraphs[insert_idx] = tag + "<br><br>" + paragraphs[insert_idx]
                        html_content = '<br><br>'.join(paragraphs)
                    else:
                        html_content += f"<br><br>{tag}"
                else:
                    html_content += f"<br><br>{tag}"

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
        # Tavily 엔진 호출
        ref_content, topic, ref_url = generate_auto_topic_tavily(category)
    
    # ⭐️ 에러 방지: 크롤링 실패로 내용이 아예 없으면 포스팅 자체를 깔끔하게 취소합니다.
    if not ref_content:
        print("❌ 유효한 기사 팩트를 찾지 못해 포스팅을 중단합니다.")
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚠️ [{category.upper()}] 적합한 뉴스를 찾지 못해 포스팅을 건너뛰었습니다."})
        exit(0)
        
    photo_prompt = create_photo_prompt(category, topic, ref_content)
    images = generate_and_split_images_xai(photo_prompt)
    title, html_output = write_blog_post(category, images, ref_content, topic)
    
    if ref_url:
        html_output += f'<br><br><hr><div style="text-align:center; margin-top: 40px;"><p style="font-size: 1.15em; font-weight: bold;">🔗 <a href="{ref_url}" target="_blank" style="color: #d32f2f; text-decoration: none;">오늘의 최신 기사 원문 출처 보기</a></p></div>'
        
    try:
        post_url = post_to_blogger(blog_id, title, html_output)
        if TELEGRAM_TOKEN and CHAT_ID:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚡ [{category.upper()}] 심층 분석 칼럼 발행 완료!\n📝 {title}\n👉 {post_url}"})
    except Exception as e:
        print(f"Error: {e}")
