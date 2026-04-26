import os
import json
import argparse
import base64
import requests
from io import BytesIO
from PIL import Image
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from bs4 import BeautifulSoup # 외부 링크 본문 추출을 위해 추가

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
# 2. 외부 링크 내용 가져오기 (Scraping 강화)
# ==========================================
def fetch_reference_content(url):
    if not url: return "", "주제 없음"
    print(f"🔗 외부 링크({url}) 본문 분석 중...")
    try:
        # 네이버 블로그 등 우회를 위한 헤더 설정
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8' # 한글 깨짐 방지
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 제목 추출 시도
        title_tag = soup.find('title')
        page_title = title_tag.text.strip() if title_tag else "참조 링크"
        
        # 본문 텍스트 추출 (스크립트, 스타일 태그 제외)
        for script in soup(["script", "style"]):
            script.decompose()
        
        text = soup.get_text(separator=' ', strip=True)
        # 너무 길면 짤리므로 핵심 3000자만 추출
        clean_text = text[:3000]
        
        print(f"✅ 원문 분석 완료 (약 {len(clean_text)}자 추출)")
        return clean_text, page_title
    except Exception as e:
        print(f"⚠️ 링크 분석 실패: {e}")
        return "", "주제 없음"

# ==========================================
# 3. xAI 이미지 생성 및 6분할 (분위기 순화)
# ==========================================
def generate_and_split_images_xai(topic):
    print(f"🎨 [{topic}] 주제로 감성적인 6컷 분할 이미지 생성 중...")
    # 프롬프트를 '영화 포스터'에서 '감성적이고 트렌디한 잡지' 스타일로 변경
    prompt = f"A beautiful and trendy 3:2 grid collage with 6 distinct scenes about '{topic}'. Modern magazine photography style, bright and inviting lighting, no text."
    
    try:
        response = xai_client.images.generate(
            model="grok-imagine-image",
            prompt=prompt,
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
# 4. GPT-5.4-mini 원고 작성 (큐레이터/리뷰어 모드)
# ==========================================
def write_blog_post(category, base64_images, ref_content="", ref_title="", ref_url=""):
    print(f"✍️ [{category}] '통찰력 있는 큐레이터 모드'로 원고 작성 중...")
    
    topic_context = f"다음은 참고할 원본 글의 내용입니다 (제목: {ref_title}):\n{ref_content}" if ref_content else "주어진 내용이 없습니다. 알아서 트렌디한 주제를 선정하세요."

    system_prompt = f"""
    당신은 '{category}' 분야의 트렌드를 짚어주고, 뻔한 정보를 가치 있게 재해석하는 인기 리뷰어(큐레이터)입니다.
    
    [필수 원칙]
    1. 무조건 제공된 [원본 글의 내용]을 핵심으로 삼아 글을 작성하세요. 원문과 무관한 소설은 절대 쓰지 마세요.
    2. 무지성 비난이나 독설은 금지합니다. 대신, 원문 내용에 대해 "이래서 사람들이 열광하는구나" 또는 "이런 부분은 좀 아쉽지만 그래도 갈 만한 이유" 등 날카롭지만 공감 가는 **'통찰력 있는 분석'**을 더하세요.
    3. 제목(<h2>): 사람들이 클릭하고 싶게 만드는 센스 있는 제목으로 작성하세요. (예: "OOO, 제가 직접 확인해본 솔직한 느낌은?", "요즘 난리난 OOO, 진짜 갈만한 곳일까?")
    4. 본문: HTML 태그만 사용하고, 문단 간격을 <br><br>로 넓게 주세요.
    5. 결론: 글 마지막에 원본 출처를 언급하세요. "자세한 원문 후기는 아래 링크에서 확인해 보세요."
    6. [IMAGE_1]~[IMAGE_6] 태그를 문맥에 맞게 글 중간중간에 배치하세요.
    
    [원본 글의 내용]
    {topic_context}
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.7 # 너무 튀지 않고 원문을 반영하도록 온도 낮춤
    )
    
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    try: title = html_content.split('<h2>')[1].split('</h2>')[0].strip()
    except: title = f"[{category.upper()}] 당신이 놓치고 있던 리뷰"

    # 이미지 플레이스홀더 치환
    if base64_images:
        for i, b64 in enumerate(base64_images):
            img_tag = f'<div style="text-align:center; margin:35px 0;"><img src="{b64}" style="max-width:100%; border-radius:12px; box-shadow: 0 4px 10px rgba(0,0,0,0.1);"></div>'
            html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
    
    for i in range(1, 7): html_content = html_content.replace(f"[IMAGE_{i}]", "")
    
    # 원문 링크 추가
    if ref_url:
        link_html = f'<br><br><hr><p style="text-align:center; color:#555;">🔗 <a href="{ref_url}" target="_blank" style="color:#0066cc; text-decoration:none;"><strong>원본 후기 자세히 보기 (클릭)</strong></a></p>'
        html_content += link_html

    return title, html_content

# ==========================================
# 5. 메인 실행 및 업로드
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
    parser.add_argument("--topic", required=True) # 수동 실행을 위해 남겨둠
    parser.add_argument("--reference_url", default="") 
    args = parser.parse_args()
    
    blog_id = BLOG_REGISTRY.get(args.category)
    if not blog_id: exit(1)
        
    # 외부 링크 내용 우선 분석
    ref_content, ref_title = fetch_reference_content(args.reference_url) if args.reference_url else ("", "")
    
    # 이미지 생성을 위한 키워드 설정 (링크가 있으면 링크 제목으로, 없으면 수동 토픽으로)
    image_topic = ref_title if ref_title != "주제 없음" else args.topic
    
    images = generate_and_split_images_xai(image_topic)
    title, html = write_blog_post(args.category, images, ref_content, ref_title, args.reference_url)
    
    try:
        post_url = post_to_blogger(blog_id, title, html)
        print(f"✅ 발행 성공 URL: {post_url}")
        
        # 텔레그램 알림 디버깅 강화
        if TELEGRAM_TOKEN and CHAT_ID:
            print("✈️ 텔레그램 알림 전송 시도...")
            msg = f"🎉 [{args.category.upper()}] 스마트 리뷰 포스팅 완료!\n\n📝 {title}\n👉 {post_url}"
            tel_res = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
            if tel_res.status_code == 200:
                print("✅ 텔레그램 전송 완료!")
            else:
                print(f"❌ 텔레그램 전송 에러: {tel_res.text}")
        else:
            print("⚠️ TELEGRAM_TOKEN 또는 CHAT_ID가 설정되지 않았습니다.")
            
    except Exception as e:
        print(f"❌ 구글 블로그 업로드 오류: {e}")
