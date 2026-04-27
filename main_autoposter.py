import os
import json
import argparse
import base64
import requests
import datetime
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

# ==========================================
# 2. 외부 링크 스크래핑 (뉴스, 유튜브 메타데이터 포함)
# ==========================================
def fetch_reference_content(url):
    if not url: return "", "주제 없음"
    print(f"🔗 외부 링크({url}) 본문/메타데이터 분석 중...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 1. 제목 추출 (og:title 우선)
        title_tag = soup.find('meta', property='og:title')
        page_title = title_tag['content'] if title_tag else (soup.title.text if soup.title else "참조 링크")
        
        # 2. 요약 메타데이터 추출 (유튜브 등 본문이 없는 경우 대비)
        desc_tag = soup.find('meta', property='og:description') or soup.find('meta', name='description')
        meta_desc = desc_tag['content'] if desc_tag else ""
        
        # 3. 본문 텍스트 추출
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()
        text = soup.get_text(separator=' ', strip=True)
        
        # 본문과 메타설명을 합쳐서 핵심만 전달 (약 3000자 제한)
        combined_content = f"[요약/설명]: {meta_desc}\n\n[본문 내용]: {text[:2500]}"
        print(f"✅ 추출 성공! 제목: {page_title[:30]}...")
        return combined_content, page_title
    except Exception as e:
        print(f"⚠️ 링크 분석 실패: {e}")
        return "", "주제 없음"

# ==========================================
# 3. [Step 1] 은유적(Metaphor) 이미지 프롬프트 설계
# ==========================================
def create_metaphorical_prompt(topic, ref_content):
    print("🧠 GPT가 안전하고 은유적인 이미지 프롬프트를 구상 중입니다...")
    system_msg = """
    당신은 추상적이고 은유적인 표현에 능한 아트 디렉터입니다.
    주어진 기사/사건의 핵심 주제를 분석하여, 1차원적인 묘사를 배제하고 '상징적인 사물이나 풍경'으로 은유(Metaphor)하는 영문 프롬프트를 작성하세요.
    
    [절대 금지 사항]
    - 피(blood), 총/칼/무기(gun, weapon), 살인, 폭력, 범죄자 등의 직접적이고 자극적인 묘사는 API 차단을 유발하므로 절대 금지합니다.
    - 텍스트나 글자를 이미지에 넣지 마세요.
    
    [작성 가이드]
    - 예시 (범죄/암살 기사): "A broken scale of justice entangled in thorny vines, cold cinematic lighting, dark and mysterious atmosphere."
    - 예시 (주식 폭락 기사): "A massive ship navigating through a turbulent stormy sea, dark clouds, dramatic lighting."
    - 결과물은 오직 영문 1~2문장만 출력하세요. 다른 설명은 붙이지 마세요.
    """
    
    try:
        res = gpt_client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {"role": "system", "content": system_msg}, 
                {"role": "user", "content": f"주제: {topic}\n내용: {ref_content[:1000]}"}
            ],
            temperature=0.8
        )
        metaphor_prompt = res.choices[0].message.content.strip()
        print(f"💡 생성된 메타포 프롬프트: {metaphor_prompt}")
        return metaphor_prompt
    except Exception as e:
        print(f"⚠️ 프롬프트 생성 오류, 기본값 사용: {e}")
        return "abstract cinematic mood, soft lighting, highly detailed."

# ==========================================
# 4. [Step 2] xAI 이미지 생성 (6분할 적용)
# ==========================================
def generate_and_split_images_xai(metaphor_prompt):
    print("🎨 메타포를 기반으로 6컷 분할 이미지 생성 중...")
    
    # 그리드 6분할 강제 지시문 + 생성된 메타포 결합
    final_prompt = f"A professional 3:2 aspect ratio grid image collage divided into 6 clean scenes. {metaphor_prompt} Modern magazine photography style, no text, minimal borders."
    
    try:
        response = xai_client.images.generate(
            model="grok-imagine-image",
            prompt=final_prompt,
            extra_body={"aspect_ratio": "3:2", "resolution": "2k"},
            n=1
        )
        img_url = response.data[0].url
        img_data = requests.get(img_url).content
        img = Image.open(BytesIO(img_data))
        
        width, height = img.size
        step_w, step_h = width // 3, height // 2
        margin = 25
        
        base64_images = []
        for row in range(2):
            for col in range(3):
                left, top = (col * step_w) + margin, (row * step_h) + margin
                right, bottom = (col * step_w) + step_w - margin, (row * step_h) + step_h - margin
                
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
# 5. [Step 3] 비판적/통찰력 있는 블로그 원고 작성
# ==========================================
def write_blog_post(category, base64_images, ref_content="", ref_title="", ref_url=""):
    print(f"✍️ [{category}] '10년 차 비평가 모드'로 원고 작성 중...")
    
    topic_context = f"기사/영상 제목: {ref_title}\n{ref_content}" if ref_content else "주제 없음"

    system_prompt = f"""
    당신은 10년 차 사회/이슈 비평 블로거이자 날카로운 인사이트로 유명한 칼럼니스트입니다.
    주어진 기사/영상의 내용을 바탕으로 독자의 시선을 사로잡고 생각을 뒤흔드는 글을 작성하세요.
    
    [핵심 작성 원칙]
    1. 구성 비율: 주어진 사건의 팩트 요약은 글의 30%만 할애하세요. 나머지 70%는 이 사건이 사회에 미치는 파장, 숨겨진 모순점, 독자가 알아야 할 이면의 진실 등 '비판적 통찰'로 채우세요.
    2. 페르소나 (말투): "이 남성은 ~라고 주장했습니다" 같은 건조한 기계적 요약투는 절대 금지합니다. 독자에게 직접 질문을 던지거나, 핵심을 찌르는 단호하고 몰입감 있는 문체를 사용하세요. (예: "과연 이게 우연일까요?", "우리가 진짜 분노해야 할 지점은 따로 있습니다.")
    3. HTML 서식: 본문은 순수 HTML 태그(<h2>, <p>, <strong>, <ul> 등)만 사용하세요. 모바일 가독성을 위해 문단 사이는 <br><br>를 넣어 넓게 띄우세요.
    4. 제목(<h2>): 평범한 요약이 아닌, 호기심을 극대화하는 후킹한 제목으로 시작하세요.
    5. 이미지 배치: 문맥 흐름에 맞게 [IMAGE_1] 부터 [IMAGE_6] 까지의 태그를 분산 배치하세요. 각 이미지 태그 아래에는 <p> 태그로 짤막하고 의미심장한 이미지 캡션을 달아주세요.
    
    [참고 데이터]
    {topic_context}
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.85 # 창의성과 날카로움을 위해 온도 상향
    )
    
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    try: title = html_content.split('<h2>')[1].split('</h2>')[0].strip()
    except: title = f"[{category.upper()}] 당신이 몰랐던 충격적인 진실"

    # 이미지 플레이스홀더 치환 (의미심장한 캡션 스타일 유지)
    if base64_images:
        for i, b64 in enumerate(base64_images):
            img_tag = f'<div style="text-align:center; margin:40px 0;"><img src="{b64}" style="max-width:100%; border-radius:10px; box-shadow: 0 5px 15px rgba(0,0,0,0.15);"></div>'
            html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
    
    for i in range(1, 7): html_content = html_content.replace(f"[IMAGE_{i}]", "")
    
    # 네이버 블로그 등 외부 링크 오류 방지 (rel="noopener noreferrer")
    if ref_url:
        clean_url = ref_url.strip()
        link_html = f'<br><br><hr><div style="text-align:center; padding: 20px; background-color: #f8f9fa; border-radius: 8px;"><p style="margin: 0; font-size: 1.1em;">더 자세한 원문과 팩트가 궁금하다면?</p><p style="margin: 10px 0 0 0;">🔗 <a href="{clean_url}" target="_blank" rel="noopener noreferrer" style="color:#0056b3; text-decoration:none; font-weight: bold;">[사건 원문 기사/영상 확인하기]</a></p></div>'
        html_content += link_html

    return title, html_content

# ==========================================
# 6. 자동 시간대별 카테고리 배분 로직
# ==========================================
def get_auto_category():
    now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    hour = now_kst.hour
    mapping = {(7, 12, 17): "news", (8, 13, 18): "it", (9, 14, 19): "stock", (10, 15, 20): "youtube", (11, 16, 21): "food"}
    for hours, cat in mapping.items():
        if hour in hours: return cat
    return "news"

# ==========================================
# 7. 메인 실행 및 블로그 업로드
# ==========================================
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
    parser.add_argument("--topic", default="오늘의 주요 이슈")
    parser.add_argument("--reference_url", default="") 
    args = parser.parse_args()
    
    category = get_auto_category() if args.category == "auto" else args.category
    
    blog_id = BLOG_REGISTRY.get(category)
    if not blog_id: exit(1)
        
    # 1. 링크 긁어오기
    ref_content, ref_title = fetch_reference_content(args.reference_url) if args.reference_url else ("", "")
    
    # 2. 이미지용 은유적 프롬프트 생성
    topic_for_image = ref_title if ref_title != "주제 없음" else args.topic
    metaphor_prompt = create_metaphorical_prompt(topic_for_image, ref_content)
    
    # 3. 이미지 생성 및 분할
    images = generate_and_split_images_xai(metaphor_prompt)
    
    # 4. 통찰력 있는 글쓰기
    title, html = write_blog_post(category, images, ref_content, ref_title, args.reference_url)
    
    # 5. 블로그 업로드 및 알림
    try:
        post_url = post_to_blogger(blog_id, title, html)
        print(f"✅ 발행 성공 URL: {post_url}")
        
        if TELEGRAM_TOKEN and CHAT_ID:
            msg = f"🔥 [{category.upper()}] 비판적 인사이트 포스팅 완료!\n\n📝 {title}\n👉 {post_url}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
            
    except Exception as e:
        print(f"❌ 구글 블로그 업로드 오류: {e}")
