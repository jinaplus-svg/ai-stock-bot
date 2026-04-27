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
# 2. 외부 링크 스크래핑
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
# 3. [Step 1] 카테고리별 맞춤형 은유 이미지 프롬프트
# ==========================================
def create_metaphorical_prompt(category, topic, ref_content):
    print(f"🧠 [{category.upper()}] 성격에 맞는 감각적인 이미지 프롬프트 구상 중...")
    
    system_msg = f"""
    당신은 블로그 카테고리에 맞춰 이미지를 기획하는 아트 디렉터입니다.
    주어진 주제를 1차원적으로 묘사하지 말고, 카테고리 '{category}'의 특성에 맞는 '감각적이고 상징적인 무드보드' 형식의 영문 이미지 프롬프트를 1~2문장으로 작성하세요.

    [절대 금지 사항]
    - 피, 무기, 폭력 등 자극적 묘사 금지. 문자(Text) 포함 금지. 사람 얼굴 직접 묘사 금지.

    [카테고리별 필수 무드]
    - news: 체스판, 빛과 그림자, 서류철 등 무겁고 시네마틱한 메타포.
    - it: 홀로그램, 데이터 라인, 미니멀한 룸, 사이버네틱 텍스처 등 세련된 미래주의.
    - food: 아늑한 웜톤 조명, 미슐랭 레스토랑의 테이블 세팅, 따뜻하고 먹음직스러운 색채.
    - stock: 상승하는 빛의 궤적, 거대한 물결, 추상적인 톱니바퀴 등 역동적 흐름.
    - youtube: 팝아트 컬러, 스포트라이트, 화려하고 트렌디한 공간.
    """
    
    try:
        res = gpt_client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": f"주제: {topic}\n내용: {ref_content[:1000]}"}],
            temperature=0.8
        )
        return res.choices[0].message.content.strip()
    except:
        return "abstract cinematic mood, highly detailed, soft lighting."

# ==========================================
# 4. [Step 2] xAI 이미지 생성 및 1:1 정사각형 스마트 크롭
# ==========================================
def generate_and_split_images_xai(metaphor_prompt):
    print("🎨 6컷 분할 이미지 생성 및 스마트 크롭 중...")
    final_prompt = f"A moodboard collage composed of 6 distinct square panels. {metaphor_prompt} High-end editorial photography style, no text."
    
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
        cell_w, cell_h = width // 3, height // 2
        
        base64_images = []
        for row in range(2):
            for col in range(3):
                # 1. 6등분 구역 계산
                left, top = col * cell_w, row * cell_h
                right, bottom = left + cell_w, top + cell_h
                cell_img = img.crop((left, top, right, bottom))
                
                # 2. 마진 적용 (테두리 자르기)
                margin = 20
                cell_img = cell_img.crop((margin, margin, cell_img.width - margin, cell_img.height - margin))
                
                # 3. 1:1 정사각형 중앙 크롭 (찌그러짐 방지)
                min_dim = min(cell_img.width, cell_img.height)
                c_left = (cell_img.width - min_dim) // 2
                c_top = (cell_img.height - min_dim) // 2
                square_img = cell_img.crop((c_left, c_top, c_left + min_dim, c_top + min_dim))
                
                # 4. 최종 600x600 사이즈로 리사이즈
                final_img = square_img.resize((600, 600), Image.Resampling.LANCZOS)
                
                buffered = BytesIO()
                if final_img.mode in ('RGBA', 'P'): final_img = final_img.convert('RGB')
                final_img.save(buffered, format="JPEG", quality=85)
                base64_images.append(f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode()}")
                
        return base64_images
    except Exception as e:
        print(f"❌ 이미지 생성 실패: {e}")
        return []

# ==========================================
# 5. [Step 3] 풍부하고 깊이 있는 원고 작성
# ==========================================
def write_blog_post(category, base64_images, ref_content="", ref_title="", ref_url=""):
    print(f"✍️ 풍부한 내용의 블로그 원고 작성 중...")
    topic_context = f"기사 제목: {ref_title}\n{ref_content}" if ref_content else "주제 없음"

    system_prompt = f"""
    당신은 '{category}' 분야의 통찰력 있는 10년 차 리뷰어입니다. 
    글을 너무 짧게 자르지 말고, 독자가 몰입할 수 있도록 1500자 내외의 충분한 분량으로 작성하세요.
    
    [작성 규칙]
    1. 글 최상단에는 무조건 <h2> 태그로 후킹하는 전체 제목을 딱 1번만 쓰세요.
    2. 본문은 3~4개의 소주제로 나누고, 각 소주제 시작마다 <h3> 태그를 활용해 가독성을 높이세요.
    3. 한 줄 쓰고 끊지 마세요. 한 문단(소주제)에 최소 3~5문장 이상 깊이 있는 비평과 통찰을 담으세요. 문단 간격은 <br><br>로 띄웁니다.
    4. 이미지 배치: [IMAGE_1] 부터 [IMAGE_6] 까지의 태그를 문장 중간에 뜬금없이 넣지 말고, '소주제(문단)가 하나 끝날 때마다' 1~2개씩 자연스럽게 배치하세요.
    5. 기계적 요약투가 아닌, 독자에게 말을 거는 듯한 친근하면서도 날카로운 문체를 사용하세요.
    
    [참고 데이터]
    {topic_context}
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.8
    )
    
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    # 📌 제목 중복 노출 방지 로직 (완벽 처리)
    title = f"[{category.upper()}] 오늘의 핵심 인사이트"
    h2_match = re.search(r'<h2>(.*?)</h2>', html_content)
    if h2_match:
        title = h2_match.group(1).strip()
        html_content = re.sub(r'<h2>.*?</h2>', '', html_content, count=1).strip() # 본문에서 h2 태그 삭제

    # 이미지 플레이스홀더 치환 (정사각형 비율에 어울리는 CSS 적용)
    if base64_images:
        for i, b64 in enumerate(base64_images):
            # 모바일에서 예쁘게 보이도록 가로폭 조절 및 그림자 효과 부여
            img_tag = f'<div style="text-align:center; margin: 40px 0;"><img src="{b64}" style="max-width: 90%; border-radius: 12px; box-shadow: 0 5px 15px rgba(0,0,0,0.1);"></div>'
            html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
    
    for i in range(1, 7): html_content = html_content.replace(f"[IMAGE_{i}]", "")
    
    if ref_url:
        clean_url = ref_url.strip()
        link_html = f'<br><br><hr><div style="text-align:center; padding: 25px; background-color: #f8f9fa; border-radius: 12px; margin-top: 40px;"><p style="margin: 0; font-size: 1.1em; color:#333; font-weight: bold;">더 자세한 원문이 궁금하다면?</p><p style="margin: 10px 0 0 0;">🔗 <a href="{clean_url}" target="_blank" rel="noopener noreferrer" style="color:#0056b3; text-decoration:none;">사건 원문 기사 바로가기</a></p></div>'
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
    
    topic_for_image = ref_title if ref_title != "주제 없음" else args.topic
    metaphor_prompt = create_metaphorical_prompt(category, topic_for_image, ref_content)
    
    images = generate_and_split_images_xai(metaphor_prompt)
    title, html = write_blog_post(category, images, ref_content, ref_title, args.reference_url)
    
    try:
        post_url = post_to_blogger(blog_id, title, html)
        print(f"✅ 발행 성공 URL: {post_url}")
        
        if TELEGRAM_TOKEN and CHAT_ID:
            msg = f"⚡ [{category.upper()}] 프리미엄 인사이트 포스팅 완료!\n\n📝 {title}\n👉 {post_url}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ 구글 블로그 업로드 오류: {e}")
