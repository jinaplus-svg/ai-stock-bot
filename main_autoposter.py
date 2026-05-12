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
from bs4 import BeautifulSoup

# ==========================================
# 1. 설정 및 API 키 로드
# ==========================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
XAI_API_KEY = os.environ.get("XAI")
GOOGLE_OAUTH_TOKEN_STR = os.environ.get("GOOGLE_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# 쌍끌이 엔진(Tavily + Naver) 키
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
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
# 2. 이중 방어 쌍끌이 뉴스 검색 엔진
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
            res = requests.post("https://api.tavily.com/search", json=payload, timeout=20)
            if res.status_code == 200:
                data = res.json()
                if data.get("results"):
                    content = data["results"][0].get("raw_content") or data["results"][0].get("content")
                    return content[:4000], data["results"][0].get("title", "참고 기사"), url
        except Exception as e:
            print(f"URL 추출 에러: {e}")
    return "", "", url

def generate_auto_topic(category):
    print(f"🤖 [{category.upper()}] 최신 기사 팩트 수집 중...")
    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")

    # 1차 시도: Tavily AI 검색
    if TAVILY_API_KEY:
        try:
            search_queries = {
                "news": "한국 주요 정치 사회 속보 핫이슈", 
                "it": "IT 테크 인공지능 스마트폰 신제품 혁신 기술", 
                "stock": "주식 증시 특징주 경제 시황", 
                "food": "한국 외식 식품 트렌드 인기 맛집", 
                "travel": "국내외 여행 항공 관광 핫플 트렌드"
            }
            query = search_queries.get(category, "주요 핫이슈")
            payload = {
                "api_key": TAVILY_API_KEY, 
                "query": f"{today_str} {query}", 
                "search_depth": "advanced", 
                "include_raw_content": True, 
                "max_results": 3,
                "days": 3 # 주말 고려 3일치 검색
            }
            res = requests.post("https://api.tavily.com/search", json=payload, timeout=15)
            if res.status_code == 200:
                for result in res.json().get('results', []):
                    title = result.get('title', '제목 없음')
                    content = result.get('raw_content') or result.get('content', '')
                    if len(content) > 200:
                        print(f"✅ [Tavily] 팩트 확보: {title}")
                        return f"[최신 기사 원문]:\n{content[:4000]}", title, result.get('url', '')
        except Exception as e:
            print(f"⚠️ Tavily 검색 에러: {e}")

    # 2차 시도: Tavily 실패 시 네이버 API 백업 출동
    if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
        print("⚠️ Tavily 검색 실패. 네이버 API(백업)로 최신 뉴스를 검색합니다.")
        try:
            queries = {"news": "사회 속보", "it": "IT 신기술", "stock": "증시 특징주", "food": "맛집 핫플", "travel": "여행 가볼만한곳"}
            headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
            params = {"query": queries.get(category, "핫이슈"), "display": 3, "sort": "date"}
            res = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params=params, timeout=10)
            if res.status_code == 200:
                for item in res.json().get('items', []):
                    title = html.unescape(re.sub(r'<[^>]+>', '', item['title']))
                    desc = html.unescape(re.sub(r'<[^>]+>', '', item['description']))
                    link = item.get('originallink') or item['link']
                    if len(desc) > 30:
                        print(f"✅ [Naver] 백업 팩트 확보: {title}")
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
    기사 내용을 분석하여 이슈의 핵심 장면을 보여주는 4분할 컷(4-panel photo collage)용 영문 프롬프트를 작성하세요.
    - 3D CG, 일러스트레이션 금지. 8k 극사실주의 실사(Photorealistic)로 묘사할 것.
    - 텍스트나 글자는 포함하지 말 것. 의미없는 풍경 금지.
    """
    res = gpt_client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"주제: {topic}\n내용: {ref_content[:1500]}"}], temperature=0.7)
    return res.choices[0].message.content.strip()

def generate_and_split_images_xai(prompt):
    final_prompt = f"A seamless photo collage of 4 panels in a 2x2 grid. {prompt} Photorealistic, cinematic lighting, no text, no borders."
    try:
        response = xai_client.images.generate(model="grok-imagine-image", prompt=final_prompt, extra_body={"aspect_ratio": "1:1", "resolution": "2k"}, n=1)
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
    td_style = 'style="padding: 14px 15px; border-bottom: 1px solid #edf2f7; text-align: center; color: #2d3748; font-weight: 500;"'
    
    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y년 %m월 %d일")
    
    system_prompt = f"""
    당신은 한국 최고의 탑티어 비즈니스/IT 트렌드 블로거이자 100만 유튜버 수준의 썰을 푸는 스토리텔러입니다. (예: 슈카월드 스타일)
    기계적인 기사 요약은 절대 금지합니다. 독자가 옆에서 듣는 것처럼 흥미진진하고 엣지있게 파헤쳐주세요.
    
    🚨 [초강력 금지 규칙 - 위반 시 무조건 감점]
    1. 마크다운 기호(```, markdown, html, **, #)는 절대로 출력하지 마세요! 오직 순수 HTML 태그와 텍스트만 사용.
    2. "[도입부]", "[본론]", "[결론]", "도입부:" 같이 목차를 나타내는 괄호나 단어는 절대로 본문에 쓰지 마세요! 대화하듯 자연스럽게 이어가세요.
    3. 'A사', 'B사' 같은 익명 처리 절대 금지! 100% 실제 기업명, 수치를 당당하게 명시.
    4. 글은 최소 2000자 이상, 7개 이상의 문단으로 아주 길고 상세하게 썰을 푸세요.
    
    [완벽한 칼럼 포스팅 구조]
    - 첫 줄: <h2>시선을 훅 끄는 도발적이고 재미있는 제목</h2>
    - "여러분, 혹시 오늘 이 소식 들으셨나요?" 처럼 어그로를 끌며 사건의 발단을 자연스럽게 시작.
    - 뉴스 원문에 있는 구체적 수치, 통계를 나열하며 언론에서 대충 넘어가는 진짜 속내, 날카로운 분석 진행.
    - 원문의 핵심 수치나 정보를 반드시 1개 이상의 HTML <table> 태그로 정리.
       <table {table_style}>
         <thead><tr><th {th_style}>항목1</th><th {th_style}>항목2</th></tr></thead>
         <tbody><tr><td {td_style}>데이터</td><td {td_style}>수치</td></tr></tbody>
       </table>
    - 뼈때리는 통찰과 조언으로 마무리.
    - 가장 마지막 줄: 엣지있는 한 줄 요약을 <blockquote {blockquote_style}> 여기에 </blockquote> 로 감싸기.
    
    [가독성 규칙]
    - 문단 사이는 반드시 <br><br> 태그를 넣어 여백을 주세요.
    - 강조할 단어는 <strong style="color:#d32f2f;">텍스트</strong> 로 붉은색 강조.
    - [IMAGE_1], [IMAGE_2], [IMAGE_3], [IMAGE_4] 텍스트를 글의 흐름에 맞춰 골고루 흩뿌리세요.
    """
    
    res = gpt_client.chat.completions.create(model="gpt-4o", messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"주제: {topic}\n\n[오늘자({today_str}) 최신 특급 기사 팩트 원문]:\n{ref_content}"}], temperature=0.85)
    
    html_content = res.choices[0].message.content.strip()
    
    # ⭐️ 1. 마크다운 기호 완벽 청소
    html_content = re.sub(r'^```[a-zA-Z]*\n', '', html_content)
    html_content = re.sub(r'```$', '', html_content).strip()
    html_content = html_content.replace('```', '')
    if html_content.lower().startswith('markdown'): html_content = html_content[8:].strip()
    if html_content.lower().startswith('html'): html_content = html_content[4:].strip()
    html_content = html_content.replace('**', '')
    
    # ⭐️ 2. 꼴보기 싫은 [도입부], [본론] 등 시스템 괄호 강제 삭제
    html_content = re.sub(r'\[(도입부|본론|결론|본론\s?\d|팩트 체크 표|숨겨진 진실|분석)\]:?', '', html_content)

    title = f"[{category.upper()}] 스페셜 브리핑"
    if h2_match := re.search(r'<h2>(.*?)</h2>', html_content):
        title = h2_match.group(1).strip().replace('#', '')
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()
        
    # ⭐️ 3. 이미지 자연스러운 강제 분산 배치
    if base64_images:
        img_tags = [f'<div style="text-align:center; margin: 45px 0;"><img src="{b64}" style="max-width: 100%; border-radius: 12px; box-shadow: 0 10px 20px rgba(0,0,0,0.12);"></div>' for b64 in base64_images]
        
        for i, tag in enumerate(img_tags):
            marker = f"[IMAGE_{i+1}]"
            if marker in html_content:
                html_content = html_content.replace(marker, tag)
            else:
                paragraphs = html_content.split('<br><br>')
                if len(paragraphs) > 2:
                    insert_idx = max(1, (len(paragraphs) // len(img_tags)) * i)
                    if insert_idx < len(paragraphs):
                        paragraphs[insert_idx] = tag + "<br><br>" + paragraphs[insert_idx]
                        html_content = '<br><br>'.join(paragraphs)
                    else:
                        html_content += f"<br><br>{tag}"
                else:
                    html_content += f"<br><br>{tag}"

    # 처리 안된 마커 최종 삭제
    for i in range(1, 5): html_content = html_content.replace(f"[IMAGE_{i}]", "")
    
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
    
    if not ref_content:
        print("❌ 유효한 기사 팩트를 찾지 못해 포스팅을 중단합니다.")
        if TELEGRAM_TOKEN and CHAT_ID: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": f"⚠️ [{category.upper()}] 검색 엔진을 총동원했으나 적합한 뉴스를 찾지 못했습니다."})
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
