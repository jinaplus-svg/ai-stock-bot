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

# API 키 설정
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

def fetch_reference_content(url):
    if not url: return ""
    print(f"🔗 외부 링크({url}) 분석 중...")
    try:
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        return res.text[:5000] 
    except Exception as e:
        print(f"⚠️ 링크 분석 실패: {e}")
        return ""

def generate_and_split_images_xai(topic):
    print(f"🎨 [{topic}] 주제로 xAI 이미지 생성 시작...")
    prompt = f"A dramatic and high-contrast 3:2 grid collage with 6 cinematic scenes about '{topic}'. Intense lighting, hyper-realistic, no text."
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
                # 이전 코드의 오타 수정 (base64_encode = 부분 제거)
                b64_str = base64.b64encode(buffered.getvalue()).decode()
                base64_images.append(f"data:image/jpeg;base64,{b64_str}")
        
        print(f"✅ 이미지 {len(base64_images)}장 생성 완료!")
        return base64_images
    except Exception as e:
        print(f"❌ 이미지 생성 실패: {e}")
        return []

def write_blog_post(category, topic, base64_images, ref_content=""):
    print(f"✍️ [{category}] 독설가 모드로 원고 작성 중...")
    ref_msg = f"참고자료: {ref_content[:1500]}" if ref_content else ""
    
    system_prompt = f"""
    당신은 '{category}' 분야의 최고 독설가 블로거입니다. 
    '{topic}'에 대해 사람들이 충격받을 만큼 날카로운 글을 HTML로 작성하세요.
    글 중간에 [IMAGE_1] ~ [IMAGE_6]을 반드시 포함하세요.
    {ref_msg}
    """
    
    try:
        res = gpt_client.chat.completions.create(
            model="gpt-5.4-mini", # 사용자 지정 모델명 유지
            messages=[{"role": "system", "content": system_prompt}],
            temperature=0.8
        )
        content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
        
        try: title = content.split('<h2>')[1].split('</h2>')[0].strip()
        except: title = f"[{category.upper()}] {topic}의 충격적인 진실"

        if base64_images:
            for i, b64 in enumerate(base64_images):
                img_tag = f'<div style="text-align:center; margin:30px 0;"><img src="{b64}" style="max-width:100%; border-radius:12px;"><p style="color:#888; font-size:0.9em;">▲ {topic}의 한 장면</p></div>'
                content = content.replace(f"[IMAGE_{i+1}]", img_tag)
        
        for i in range(1, 7): content = content.replace(f"[IMAGE_{i}]", "")
        print("✅ 원고 작성 완료!")
        return title, content
    except Exception as e:
        print(f"❌ 원고 작성 중 에러: {e}")
        return None, None

def post_to_blogger(blog_id, title, content):
    print("☁️ 구글 블로그 업로드 중...")
    try:
        token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
        if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
        service = build('blogger', 'v3', credentials=creds)
        request = service.posts().insert(blogId=blog_id, body={"title": title, "content": content}, isDraft=False)
        response = request.execute()
        return response.get('url')
    except Exception as e:
        print(f"❌ 블로그 업로드 에러: {e}")
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--reference_url", default="")
    args = parser.parse_args()
    
    blog_id = BLOG_REGISTRY.get(args.category)
    if not blog_id:
        print(f"❌ {args.category} 카테고리에 해당하는 BLOG_ID가 없습니다.")
        exit(1)
        
    ref_data = fetch_reference_content(args.reference_url)
    images = generate_and_split_images_xai(args.topic)
    title, html = write_blog_post(args.category, args.topic, images, ref_data)
    
    if title and html:
        post_url = post_to_blogger(blog_id, title, html)
        if post_url:
            print(f"🚀 발행 성공! 주소: {post_url}")
            if TELEGRAM_TOKEN:
                msg = f"⚡ [{args.category.upper()}] 독설 포스팅 완료!\n\n📝 {title}\n👉 {post_url}"
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
                print("✈️ 텔레그램 알림 전송 완료!")
        else:
            print("❌ 블로그 발행에 실패했습니다.")
    else:
        print("❌ 원고를 생성하지 못했습니다.")
