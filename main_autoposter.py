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
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# 블로그 카테고리별 ID 매핑
BLOG_REGISTRY = {
    "it": os.environ.get("IT_BLOG_ID"),
    "food": os.environ.get("FOOD_BLOG_ID"),
    "news": os.environ.get("NEWS_BLOG_ID"),
    "stock": os.environ.get("STOCK_BLOG_ID"),
    "youtube": os.environ.get("YOUTUBE_BLOG_ID")
}

gpt_client = OpenAI(api_key=OPENAI_API_KEY)
# xAI 클라이언트 설정 (OpenAI 호환 방식)
xai_client = OpenAI(
    api_key=XAI_API_KEY,
    base_url="https://api.x.ai/v1"
)

SCOPES = ['https://www.googleapis.com/auth/blogger']

# ==========================================
# 2. xAI 이미지 생성 및 6분할 슬라이싱 로직
# ==========================================
def generate_and_split_images_xai(topic):
    """xAI API로 3:2 비율의 이미지를 생성하고 6개로 정교하게 분할합니다."""
    print(f"🎨 [{topic}] 주제로 xAI 이미지 생성을 시작합니다 (grok-imagine-image)...")
    
    if not XAI_API_KEY:
        print("❌ XAI API 키가 설정되지 않았습니다.")
        return []

    # xAI 전용 모델 파라미터 적용 (3:2 비율, 2k 해상도)
    prompt = f"A professional 3:2 aspect ratio grid image collage divided into 6 clean scenes about '{topic}'. Modern and realistic photography style, no text, minimal borders."
    
    try:
        # xAI의 Grok 이미지 생성 모델 호출
        response = xai_client.images.generate(
            model="grok-imagine-image",
            prompt=prompt,
            extra_body={
                "aspect_ratio": "3:2",
                "resolution": "2k"
            },
            n=1
        )
        
        img_url = response.data[0].url
        img_data = requests.get(img_url).content
        img = Image.open(BytesIO(img_data))
        
        # 이미지 분할 로직 (3열 2행)
        width, height = img.size
        step_w = width // 3
        step_h = height // 2
        margin = 25 # 테두리 제거를 위한 마진 설정
        
        base64_images = []
        for row in range(2):
            for col in range(3):
                left = (col * step_w) + margin
                top = (row * step_h) + margin
                right = (col * step_w) + step_w - margin
                bottom = (row * step_h) + step_h - margin
                
                cropped = img.crop((left, top, right, bottom))
                
                # 가로폭 600px로 최적화 리사이즈
                target_width = 600
                target_height = int(target_width * (cropped.height / cropped.width))
                cropped = cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
                
                if cropped.mode in ('RGBA', 'P'):
                    cropped = cropped.convert('RGB')
                
                buffered = BytesIO()
                cropped.save(buffered, format="JPEG", quality=85)
                img_str = base64.b64encode(buffered.getvalue()).decode()
                base64_images.append(f"data:image/jpeg;base64,{img_str}")
                
        print(f"✂️ 이미지 6분할 완료 ({len(base64_images)}장)")
        return base64_images

    except Exception as e:
        print(f"❌ xAI 이미지 처리 중 오류 발생: {e}")
        return []

# ==========================================
# 3. GPT-5.4-mini 블로그 원고 작성 (후킹 강조)
# ==========================================
def write_blog_post(category, topic, base64_images):
    """GPT-5.4-mini를 사용하여 매력적인 블로그 글을 작성합니다."""
    print(f"✍️ [{category}] 원고 작성 중 (gpt-5.4-mini)...")
    
    system_prompt = f"""
    당신은 '{category}' 분야의 최고 스타 블로거입니다.
    '{topic}'에 대해 독자들이 첫 문장부터 빠져들 수 있는 흥미진진한 블로그 포스팅을 작성하세요.
    
    [작성 규칙]
    1. 지루한 설명은 빼고, 사람들의 호기심을 자극하는 강렬한 제목(<h2>)과 핵심 위주로 작성하세요.
    2. 무조건 순수 HTML 태그(<h2>, <p>, <ul>, <li>, <strong>)만 사용하세요. (마크다운 기호 금지)
    3. 가독성을 위해 <br><br>를 사용하여 문단 간격을 넉넉히 벌려주세요.
    4. 친근한 말투(해요체)와 트렌디한 이모지를 풍부하게 활용하세요.
    5. 생성된 6개의 이미지가 들어갈 위치에 [IMAGE_1]부터 [IMAGE_6]까지 순서대로 배치하세요.
    """
    
    try:
        res = gpt_client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"주제: {topic}"}],
            temperature=0.8
        )
        
        html_content = res.choices[0].message.content.strip()
        
        # 마크다운 블록 기호 제거
        if html_content.startswith("```html"):
            html_content = html_content[7:]
        if html_content.endswith("```"):
            html_content = html_content[:-3]
            
        # 제목 추출
        try:
            title = html_content.split('<h2>')[1].split('</h2>')[0].strip()
        except:
            title = f"[{category.upper()}] {topic}의 모든 것!"

        # 이미지 플레이스홀더를 실제 Base64 데이터로 치환
        if base64_images:
            for i, b64 in enumerate(base64_images):
                placeholder = f"[IMAGE_{i+1}]"
                img_tag = f'<div style="text-align:center; margin:35px 0;"><img src="{b64}" style="max-width:100%; border-radius:12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);"></div>'
                html_content = html_content.replace(placeholder, img_tag)
        
        # 미사용 플레이스홀더 청소
        for i in range(1, 7):
            html_content = html_content.replace(f"[IMAGE_{i}]", "")
            
        return title, html_content
    except Exception as e:
        print(f"❌ 원고 작성 실패: {e}")
        return f"[{category}] {topic}", f"<p>{topic}에 대한 글 작성을 실패했습니다.</p>"

# ==========================================
# 4. 구글 블로거 업로드 및 텔레그램 전송
# ==========================================
def post_to_blogger(blog_id, title, content):
    """구글 블로그에 포스팅을 업로드합니다."""
    print("☁️ 구글 블로그 업로드 시도 중...")
    try:
        token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        
        service = build('blogger', 'v3', credentials=creds)
        body = {"kind": "blogger#post", "title": title, "content": content}
        
        request = service.posts().insert(blogId=blog_id, body=body, isDraft=False)
        response = request.execute()
        post_url = response.get('url')
        print(f"✅ 발행 성공: {post_url}")
        return post_url
    except Exception as e:
        print(f"❌ 블로그 업로드 실패: {e}")
        return None

def send_telegram(category, title, url):
    """텔레그램 알림을 발송합니다."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("⚠️ 텔레그램 설정이 부족하여 알림을 생략합니다.")
        return
    
    msg = f"🎉 [{category.upper()}] 새 포스팅 업로드 완료!\n\n📝 제목: {title}\n👉 바로가기: {url}"
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
        print("✈️ 텔레그램 알림 전송 완료!")
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")

# ==========================================
# 5. 메인 실행부
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", type=str, required=True, help="it, food, news, stock, youtube")
    parser.add_argument("--topic", type=str, required=True, help="포스팅 주제")
    args = parser.parse_args()
    
    blog_id = BLOG_REGISTRY.get(args.category)
    if not blog_id:
        print(f"❌ '{args.category}' 블로그 ID를 찾을 수 없습니다.")
        exit(1)
        
    # 1. xAI 이미지 생성 및 6분할 처리
    images = generate_and_split_images_xai(args.topic)
    
    # 2. GPT-5.4-mini 원고 작성
    title, html_body = write_blog_post(args.category, args.topic, images)
    
    # 3. 발행 및 텔레그램 알림
    final_url = post_to_blogger(blog_id, title, html_body)
    if final_url:
        send_telegram(args.category, title, final_url)
