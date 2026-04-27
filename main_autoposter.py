import os
import json
import argparse
import base64
import requests
import datetime
import re
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
    print(f"🔗 외부 링크({url}) 분석 중...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        title_tag = soup.find('meta', property='og:title')
        page_title = title_tag['content'] if title_tag else (soup.title.text if soup.title else "참조 링크")
        
        desc_tag = soup.find('meta', property='og:description') or soup.find('meta', name='description')
        meta_desc = desc_tag['content'] if desc_tag else ""
        
        for script in soup(["script", "style", "nav", "footer"]):
            script.decompose()
        text = soup.get_text(separator=' ', strip=True)
        
        combined_content = f"[요약]: {meta_desc}\n\n[본문]: {text[:2500]}"
        return combined_content, page_title
    except Exception as e:
        print(f"⚠️ 링크 분석 실패: {e}")
        return "", "주제 없음"

# ==========================================
# 3. [Step 1] 카테고리 맞춤형 은유적 이미지 프롬프트
# ==========================================
def create_metaphorical_prompt(category, topic, ref_content):
    print(f"🧠 [{category.upper()}] 성격에 맞는 안전하고 감각적인 이미지 프롬프트 구상 중...")
    
    system_msg = f"""
    당신은 트렌디하고 감각적인 아트 디렉터입니다.
    주어진 기사/사건의 주제와 블로그 카테고리 '{category}'의 특성에 맞춰, 1차원적 묘사를 피하고 '감각적인 상징이나 풍경'으로 은유(Metaphor)하는 영문 이미지 프롬프트를 1~2문장으로 작성하세요.

    [절대 금지 사항]
    - 피, 무기, 살인, 범죄자 등 직접적이고 자극적인 묘사 절대 금지.
    - 텍스트나 글자 포함 금지.

    [카테고리별 무드 가이드]
    - news(이슈/사회): 부서진 시계, 얽힌 가시덤불, 흑백의 체스판 등 무겁고 시네마틱한 은유.
    - it(기술/과학): 빛나는 홀로그램 텍스처, 미니멀하고 깨끗한 룸, 네온 빛의 회로도 등 세련되고 미래지향적인 분위기.
    - food(맛집/요리): 신선함이 돋보이는 아늑한 웜톤 조명, 미슐랭 스타일의 감각적인 테이블 세팅, 먹음직스러운 색감.
    - stock(경제/주식): 위로 뻗어나가는 황금빛 궤적, 톱니바퀴, 거대한 파도 등 역동적이고 추상적인 흐름.
    - youtube(자유/엔터): 팝아트 느낌, 화려한 색채, 무대 조명 등 트렌디하고 톡톡 튀는 분위기.
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
        print(f"💡 생성된 프롬프트: {metaphor_prompt}")
        return metaphor_prompt
    except Exception as e:
        return "abstract cinematic mood, soft lighting, highly detailed."

# ==========================================
# 4. [Step 2] xAI 이미지 생성
# ==========================================
def generate_and_split_images_xai(metaphor_prompt):
    print("🎨 6컷 분할 이미지 생성 중...")
    final_prompt = f"A professional 3:2 aspect ratio grid image collage divided into 6 clean scenes. {metaphor_prompt} Modern aesthetic photography style, no text, minimal borders."
    
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
# 5. [Step 3] 초압축 + 통찰력 블로그 원고 작성
# ==========================================
def write_blog_post(category, base64_images, ref_content="", ref_title="", ref_url=""):
    print(f"✍️ 짧고 타격감 있는 원고 작성 중...")
    topic_context = f"기사 제목: {ref_title}\n{ref_content}" if ref_content else "주제 없음"

    system_prompt = f"""
    당신은 10년 차 비평가입니다. 기존보다 분량을 절반 이하로 팍 줄여서(공백 포함 최대 800자 이내), 아주 짧고 임팩트 있게 핵심만 찌르는 글을 작성하세요.
    
    [작성 규칙]
    1. 글 최상단에는 무조건 <h2> 태그로 후킹하는 제목을 딱 1번만 쓰세요.
    2. 구구절절한 설명은 다 빼고, 가장 충격적이거나 중요한 팩트 1줄 + 독자의 뒤통수를 치는 비판적 통찰 위주로 짧게 치고 빠지세요.
    3. 문단은 <br><br>로 넉넉히 띄워 모바일 가독성을 극대화하세요.
    4. [IMAGE_1] 부터 [IMAGE_6] 태그를 문맥에 맞게 분산 배치하고, 짧은 캡션을 다세요.
    
    [참고 데이터]
    {topic_context}
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.8
    )
    
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    # 📌 [수정] 정규식으로 제목을 추출한 뒤 본문에서 <h2> 태그 부분을 완전히 삭제합니다.
    title = f"[{category.upper()}] 오늘의 핵심 인사이트"
    h2_match = re.search(r'<h2>(.*?)</h2>', html_content)
    if h2_match:
        title = h2_match.group(1).strip()
        # 본문에서 해당 h2 태그 전체를 공백으로 치환 (중복 노출 방지)
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip()

    # 이미지 플레이스홀더 치환
    if base64_images:
        for i, b64 in enumerate(base64_images):
            img_tag = f'<div style="text-align:center; margin:35px 0;"><img src="{b64}" style="max-width:100%; border-radius:10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);"></div>'
            html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
    
    for i in range(1, 7): html_content = html_content.replace(f"[IMAGE_{i}]", "")
    
    # 원문 링크 삽입 (네이버 오류 방지 rel 태그 포함)
    if ref_url:
        clean_url = ref_url.strip()
        link_html = f'<br><br><hr><div style="text-align:center; padding: 20px; background-color: #f8f9fa; border-radius: 8px;"><p style="margin: 0; font-size: 1.0em; color:#333;">더 자세한 원문이 궁금하다면?</p><p style="margin: 10px 0 0 0;">🔗 <a href="{clean_url}" target="_blank" rel="noopener noreferrer" style="color:#0056b3; text-decoration:none; font-weight: bold;">[사건 원문 기사 확인하기]</a></p></div>'
        html_content += link_html

    return title, html_content

# ==========================================
# 6. 메인 실행부
# ==========================================
def get_auto_category():
    now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    hour = now_kst.hour
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
        
    ref_content, ref_title = fetch_reference_content(args.reference_url) if args.reference_url else ("", "")
    
    # 📌 이미지 프롬프트 생성 시 category 정보를 넘겨주어 무드를 맞춤 설정합니다.
    topic_for_image = ref_title if ref_title != "주제 없음" else args.topic
    metaphor_prompt = create_metaphorical_prompt(category, topic_for_image, ref_content)
    
    images = generate_and_split_images_xai(metaphor_prompt)
    title, html = write_blog_post(category, images, ref_content, ref_title, args.reference_url)
    
    try:
        post_url = post_to_blogger(blog_id, title, html)
        print(f"✅ 발행 성공 URL: {post_url}")
        
        if TELEGRAM_TOKEN and CHAT_ID:
            msg = f"⚡ [{category.upper()}] 숏폼 인사이트 포스팅 완료!\n\n📝 {title}\n👉 {post_url}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ 구글 블로그 업로드 오류: {e}")
