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

# ==========================================
# 1. 설정 및 API 키 로드 (GitHub Secrets)
# ==========================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
XAI_API_KEY = os.environ.get("XAI")
GOOGLE_OAUTH_TOKEN_STR = os.environ.get("GOOGLE_TOKEN")

# 텔레그램 알림 설정
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
# 2. 텔레그램 전송 로직
# ==========================================
def send_telegram_message(category, title, url):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ 텔레그램 토큰 또는 CHAT_ID가 없어 알림을 생략합니다.")
        return

    message = f"🎉 [{category.upper()}] 새 포스팅 업로드 완료!\n\n📝 제목: {title}\n👉 확인하기: {url}"
    req_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    try:
        requests.post(req_url, data={"chat_id": CHAT_ID, "text": message})
        print("✈️ 텔레그램 알림 전송 완료!")
    except Exception as e:
        print(f"❌ 텔레그램 알림 전송 실패: {e}")

# ==========================================
# 3. xAI 이미지 6분할 생성 로직
# ==========================================
def generate_and_split_images_xai(topic):
    print(f"🎨 [{topic}] 주제로 xAI에 6컷 분할 이미지 생성을 요청합니다...")
    img_prompt = f"A 2x3 grid collage of 6 different scenes related to '{topic}'. The image must be evenly divided into 6 rectangles (3 columns, 2 rows). No borders, no text, highly realistic and clean modern photography style."
    
    try:
        response = xai_client.images.generate(prompt=img_prompt, size="1024x1024", n=1)
        img_url = response.data[0].url
        
        print("✂️ 이미지를 다운로드하고 6장으로 분할합니다...")
        img_response = requests.get(img_url)
        img = Image.open(BytesIO(img_response.content))
        
        width, height = img.size
        col_w = width // 3
        row_h = height // 2
        
        base64_images = []
        for row in range(2):
            for col in range(3):
                left, upper = col * col_w, row * row_h
                right, lower = left + col_w, upper + row_h
                
                cropped = img.crop((left, upper, right, lower))
                cropped = cropped.resize((600, int(600 * (row_h/col_w))), Image.Resampling.LANCZOS)
                buffered = BytesIO()
                cropped.save(buffered, format="JPEG", quality=85)
                
                img_str = base64.b64encode(buffered.getvalue()).decode()
                base64_images.append(f"data:image/jpeg;base64,{img_str}")
                
        return base64_images
    except Exception as e:
        print(f"❌ xAI 이미지 생성/분할 실패: {e}")
        return []

# ==========================================
# 4. GPT 블로그 작성 로직 (gpt-5.4-mini)
# ==========================================
def write_blog_post(category, topic, base64_images):
    print(f"✍️ [{category}] 블로그 원고 작성 중 (gpt-5.4-mini)...")
    system_prompt = f"""
    당신은 '{category}' 분야의 최고 인기 블로거입니다.
    '{topic}'에 대해 사람들이 클릭하지 않고는 못 배길 만큼 '후킹(hooking)하고 의미 있는' 블로그 포스팅을 작성하세요.
    
    [작성 규칙]
    1. 지루한 서론은 빼고 독자의 시선을 확 사로잡는 핵심 위주로 작성하세요.
    2. 무조건 HTML 태그(<h2>, <p>, <ul>, <strong> 등)만 사용하세요. (마크다운 ```html 절대 금지)
    3. 모바일 가독성을 위해 한 문단이 3문장을 넘지 않게 하고, <br><br>로 문단을 자주 띄워주세요.
    4. 친근하고 톡톡 튀는 말투를 사용하며 이모지를 적절히 섞어주세요.
    5. 글의 흐름에 맞춰 6개의 이미지가 자연스럽게 배치되도록 삽입 코드를 넣으세요.
       - 삽입 코드: [IMAGE_1], [IMAGE_2], [IMAGE_3], [IMAGE_4], [IMAGE_5], [IMAGE_6]
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.75
    )
    
    html_content = res.choices[0].message.content.strip()
    
    if html_content.startswith("```html"): 
        html_content = html_content[7:]
    if html_content.endswith("```"): 
        html_content = html_content[:-3]
    
    try:
        title = html_content.split('<h2>')[1].split('</h2>')[0].strip()
    except:
        title = f"[{category.upper()}] {topic} 핵심 요약"

    if base64_images and len(base64_images) >= 6:
        for i in range(6):
            img_tag = f'<div style="text-align:center; margin:30px 0;"><img src="{base64_images[i]}" style="max-width:100%; border-radius:10px; box-shadow: 0 4px 8px rgba(0,0,0,0.05);"></div>'
            html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
    
    for i in range(1, 7):
        html_content = html_content.replace(f"[IMAGE_{i}]", "")
        
    return title, html_content

# ==========================================
# 5. 구글 블로거 업로드
# ==========================================
def post_to_blogger(blog_id, title, content):
    print("☁️ 구글 블로그에 업로드 중...")
    token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        
    service = build('blogger', 'v3', credentials=creds)
    body = {"title": title, "content": content}
    
    try:
        request = service.posts().insert(blogId=blog_id, body=body, isDraft=False)
        response = request.execute()
        post_url = response.get('url')
        print(f"🎉 포스팅 성공! 링크: {post_url}")
        return post_url
    except Exception as e:
        print(f"❌ 포스팅 실패: {e}")
        return None

# ==========================================
# 6. 메인 실행부 (여기가 지워졌었습니다!)
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", type=str, required=True)
    parser.add_argument("--topic", type=str, required=True)
    args = parser.parse_args()
    
    target_blog_id = BLOG_REGISTRY.get(args.category)
    if not target_blog_id:
        print(f"❌ 카테고리 '{args.category}'의 블로그 ID가 없습니다.")
        exit(1)
        
    images = generate_and_split_images_xai(args.topic)
    title, final_html = write_blog_post(args.category, args.topic, images)
    
    # 블로그 포스팅 후 성공 시 텔레그램 알림 발송
    uploaded_url = post_to_blogger(target_blog_id, title, final_html)
    if uploaded_url:
        send_telegram_message(args.category, title, uploaded_url)
