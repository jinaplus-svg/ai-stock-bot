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

BLOG_REGISTRY = {
    "it": os.environ.get("IT_BLOG_ID"),
    "food": os.environ.get("FOOD_BLOG_ID"),
    "news": os.environ.get("NEWS_BLOG_ID"),
    "stock": os.environ.get("STOCK_BLOG_ID"),
    "youtube": os.environ.get("YOUTUBE_BLOG_ID")
}

gpt_client = OpenAI(api_key=OPENAI_API_KEY)
# 이미지용 xAI는 전용 로직을 위해 requests를 직접 사용합니다.
SCOPES = ['https://www.googleapis.com/auth/blogger']

# ==========================================
# 2. xAI 이미지 6분할 생성 (제공해주신 성공 코드 기반)
# ==========================================
def generate_and_split_images_xai(topic):
    print(f"🎨 [{topic}] 주제로 xAI 6분할 이미지 생성을 시작합니다...")
    if not XAI_API_KEY:
        print("⚠️ XAI API 키가 없습니다.")
        return []

    # 6분할을 위한 프롬프트와 xAI 전용 파라미터
    prompt = f"A high-quality 3:2 aspect ratio grid image divided into 6 clean scenes about '{topic}'. Modern photography style, no text, distinct sections."
    
    try:
        headers = {
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json"
        }
        # 성공했던 코드의 페이로드 구조 적용
        payload = {
            "model": "grok-imagine-image",
            "prompt": prompt,
            "aspect_ratio": "3:2",
            "resolution": "2k", # 분할 후 화질을 위해 2k 사용
            "n": 1
        }

        res = requests.post("https://api.x.ai/v1/images/generations", headers=headers, json=payload, timeout=120)
        
        if res.status_code != 200:
            print(f"❌ xAI 응답 에러: {res.text}")
            return []

        image_url = res.json()['data'][0]['url']
        img_data = requests.get(image_url).content
        img = Image.open(BytesIO(img_data))
        
        # 6분할 슬라이싱 로직 (제공해주신 코드 최적화 적용)
        width, height = img.size
        step_w, step_h = width // 3, height // 2
        margin = 20 # 테두리 제거 마진
        
        base64_images = []
        for row in range(2):
            for col in range(3):
                left = (col * step_w) + margin
                top = (row * step_h) + margin
                right = (col * step_w) + step_w - margin
                bottom = (row * step_h) + step_h - margin
                
                cropped = img.crop((left, top, right, bottom))
                
                # 가로폭 600px 최적화
                cropped = cropped.resize((600, int(600 * (cropped.height / cropped.width))), Image.Resampling.LANCZOS)
                if cropped.mode in ('RGBA', 'P'): cropped = cropped.convert('RGB')
                
                buffered = BytesIO()
                cropped.save(buffered, format="JPEG", quality=85)
                img_str = base64.b64encode(buffered.getvalue()).decode()
                base64_images.append(f"data:image/jpeg;base64,{img_str}")
        
        print("✂️ 6분할 이미지 처리 완료!")
        return base64_images

    except Exception as e:
        print(f"❌ 이미지 생성 중 오류: {e}")
        return []

# ==========================================
# 3. GPT-5.4-mini 블로그 원고 작성 (후킹 강조)
# ==========================================
def write_blog_post(category, topic, base64_images):
    print(f"✍️ [{category}] 후킹한 원고 작성 중 (gpt-5.4-mini)...")
    
    system_prompt = f"""
    당신은 '{category}' 분야의 최고 인기 인플루언서입니다.
    '{topic}'에 대해 독자들이 첫 문장부터 빠져들 수 있는 흥미진진한 블로그 포스팅을 작성하세요.
    
    [미션]
    1. 지루한 설명조가 아니라, 궁금증을 유발하는 강력한 헤드라인과 도입부를 사용하세요.
    2. HTML 태그(<h2>, <p>, <ul>, <strong>)만 사용하세요. (마크다운 ```html 금지)
    3. <br><br>를 사용하여 모바일에서 보기 편하게 문단 간격을 넓게 유지하세요.
    4. 친근한 말투와 이모지를 풍부하게 사용하여 활기찬 느낌을 전달하세요.
    5. 6개의 이미지가 들어갈 위치에 [IMAGE_1]~[IMAGE_6]을 순서대로 넣으세요.
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.8
    )
    
    html_content = res.choices[0].message.content.strip()
    if html_content.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1

### 🛠️ 수정 사항 요약
1.  **xAI 에러 해결**: `size` 대신 `aspect_ratio`와 `resolution`을 사용하는 xAI 전용 방식으로 수정했습니다.
2.  **이미지 퀄리티 UP**: 분할 후에도 선명하도록 **2k 해상도**로 생성하고, 테두리 흰 선을 방지하기 위해 마진을 적용해 정교하게 잘라냅니다.
3.  **모델 최적화**: 모든 텍스트 생성은 최신 가성비 모델인 **`gpt-5.4-mini`**를 사용합니다.
4.  **후킹 지시 강화**: 프롬프트를 수정하여 단순히 정보를 나열하지 않고 사람들이 클릭하고 싶게 만드는 말투를 사용하도록 했습니다.

이제 이 코드를 저장하고 다시 실행해 보세요! 이번엔 텔레그램 알림과 함께 이미지가 쏙 들어간 고퀄리티 포스팅이 올라올 겁니다. 🚀
