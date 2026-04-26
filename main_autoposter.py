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
# 2. 외부 링크 내용 가져오기 (Scraping)
# ==========================================
def fetch_reference_content(url):
    if not url: return ""
    print(f"🔗 외부 링크({url}) 분석 중...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        return res.text[:5000] 
    except Exception as e:
        print(f"⚠️ 링크 분석 실패: {e}")
        return ""

# ==========================================
# 3. xAI 이미지 생성 및 6분할 (엣지 있게)
# ==========================================
def generate_and_split_images_xai(topic):
    print(f"🎨 [{topic}] 주제로 충격적인 6컷 분할 이미지 생성 중...")
    prompt = f"A dramatic and high-contrast 3:2 grid collage with 6 cinematic scenes about '{topic}'. Intense lighting, hyper-realistic, no text. Make it look like a blockbuster movie poster."
    
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
# 4. GPT-5.4-mini 원고 작성 (독설가 모드)
# ==========================================
def write_blog_post(category, topic, base64_images, ref_content=""):
    print(f"✍️ [{category}] '독설가 모드'로 원고 작성 중...")
    
    ref_instruction = f"다음 외부 자료를 참고하여 더 날카롭게 재해석하세요: {ref_content[:2000]}" if ref_content else ""

    system_prompt = f"""
    당신은 '{category}' 분야의 100만 유튜버이자, 팩트 폭격으로 유명한 인플루언서입니다.
    오늘의 주제 '{topic}'에 대해 사람들이 뒤통수를 한 대 맞은 것 같은 '독설과 통찰'이 담긴 글을 쓰세요.
    
    [필수 원칙]
    1. 제목(<h2>): '당신이 ~하면 망하는 이유', '전문가들은 절대 말 안 하는 ~' 식으로 도발적으로 작성.
    2. 도입부: "아직도 ~하시나요? 참 안타깝습니다." 같은 식으로 독자의 불안이나 궁금증을 자극하며 시작.
    3. 본문: 무조건 HTML 태그만 사용. 문단마다 <br><br>를 넣어 모바일 가독성 극대화.
    4. 이미지 캡션: [IMAGE_N] 태그 바로 밑에 '▲ 이 장면이 무엇을 의미하는지 궁금하신가요?' 같은 식의 날카로운 한 줄 캡션을 넣을 것.
    5. 결론: "결국 행동하는 사람만이 살아남습니다." 같은 강력한 행동 유도(CTA)로 마무리.
    {ref_instruction}
    """
    
    res = gpt_client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "system", "content": system_prompt}],
        temperature=0.85
    )
    
    html_content = res.choices[0].message.content.strip().replace("```html", "").replace("```", "")
    
    try: title = html_content.split('<h2>')[1].split('</h2>')[0].strip()
    except: title = f"[{category.upper()}] 지금 당장 알아야 할 {topic}"

    if base64_images:
        for i, b64 in enumerate(base64_images):
            img_tag = f'<div style="text-align:center; margin:35px 0;"><img src="{b64}" style="max-width:100%; border-radius:12px; box-shadow: 0 4px 10px rgba(0,0,0,0.1);"><p style="font-size:0.85em; color:#888; margin-top:5px;">▲ 이 포스팅의 핵심적인 한 장면</p></div>'
            html_content = html_content.replace(f"[IMAGE_{i+1}]", img_tag)
    
    for i in range(1, 7): html_content = html_content.replace(f"[IMAGE_{i}]", "")
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
    parser.add_argument("--topic", required=True)
    parser.add_argument("--reference_url", default="") 
    args = parser.parse_args()
    
    blog_id = BLOG_REGISTRY.get(args.category)
    if not blog_id: exit(1)
        
    ref_data = fetch_reference_content(args.reference_url) if args.reference_url else ""
    images = generate_and_split_images_xai(args.topic)
    title, html = write_blog_post(args.category, args.topic, images, ref_data)
    
    try:
        post_url = post_to_blogger(blog_id, title, html)
        if TELEGRAM_TOKEN:
            msg = f"⚡ [{args.category.upper()}] 독설 포스팅 완료!\n\n📝 {title}\n👉 {post_url}"
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print(f"❌ 오류: {e}")
