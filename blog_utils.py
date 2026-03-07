import os
import requests
import random
import re
from openai import OpenAI

# API 키 세팅
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

COUPANG_AD_HTML = """
<div style="text-align: center; margin: 50px 0; padding: 25px; border: 2px dashed #0073e9; border-radius: 12px; background-color: #f8fbff;">
    <p style="margin-bottom: 15px; font-weight: bold; color: #1a1a1a; font-size: 17px;">🎁 T대디가 엄선한 오늘의 추천 특가! 🎁</p>
    <a href="[https://link.coupang.com/a/dYVf3W](https://link.coupang.com/a/dYVf3W)" target="_blank" style="display: inline-block; padding: 16px 32px; background-color: #0073e9; color: #ffffff !important; text-decoration: none; font-weight: bold; border-radius: 8px; font-size: 18px; box-shadow: 0 4px 10px rgba(0,115,233,0.3); transition: all 0.3s;">
        👉 추천 상품 상세 정보 확인하기
    </a>
    <p style="margin-top: 12px; font-size: 13px; color: #777;">(한정 수량이니 서두르세요! 🏃‍♂️)</p>
</div>
"""

DISCLAIMER_HTML = """
<p style="font-size:12px; color:#999; text-align:center; margin-top:50px; padding-top:20px; border-top:1px solid #eaeaea;">
"이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
</p>
"""

def search_latest_info(query):
    """Tavily API를 이용해 최신 정보와 **실제 관련 웹 이미지**를 동시에 검색합니다."""
    url = "[https://api.tavily.com/search](https://api.tavily.com/search)"
    payload = {
        "api_key": TAVILY_API_KEY, 
        "query": query, 
        "search_depth": "advanced", 
        "include_answer": True,
        "include_images": True  # 👈 핵심! 검색된 기사/장소/유튜브의 실제 이미지를 가져옵니다.
    }
    try:
        response = requests.post(url, json=payload).json()
        context = response.get('answer', str(response.get('results', '검색 결과를 요약할 수 없습니다.')))
        real_images = response.get('images', []) # 👈 실제 이미지 URL 리스트
        return context, real_images
    except Exception as e:
        print(f"❌ Tavily 검색 실패: {e}")
        return "최신 정보를 불러오는 데 실패했습니다.", []

def get_thumbnail_image(keyword):
    """실제 이미지가 부족할 경우를 대비한 Pexels 예비용(Fallback) 함수"""
    if not PEXELS_API_KEY: return ""
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"[https://api.pexels.com/v1/search?query=](https://api.pexels.com/v1/search?query=){keyword}&per_page=15&locale=en-US"
    try:
        res = requests.get(url, headers=headers).json()
        photos = res.get('photos', [])
        if photos: return random.choice(photos)['src']['large']
    except: pass
    return ""

def generate_blog_post(system_role, subject, search_context, real_images):
    """지정된 페르소나와 구조에 맞춰 힙한 블로그 HTML 코드를 생성합니다."""
    prompt = f"""
    당신은 스타 블로거 **'지니'**입니다. 제공받은 정보를 바탕으로 본인이 직접 경험한 것처럼 생생하고 힙한 감성의 블로그 포스팅을 HTML 형식으로 작성해주세요. 독자들과 수다를 떠는 듯한 친근한 말투(해요체)와 이모지를 풍부하게 사용하세요.

    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}
    [당신의 페르소나]: {system_role}

    [필수 작성 구조 및 규칙]
    1. 제목: 맨 첫 줄은 무조건 `<h1>✨ 제목</h1>` 형식으로 작성하세요.
    2. 넓은 띄어쓰기(가독성): 스마트폰 가독성을 위해 새로운 문단이나 주제가 시작될 때는 반드시 `<p style="margin-bottom: 40px; line-height: 1.8; font-size: 16px;">` 태그를 사용하여 여백을 아주 넉넉히 주세요.
    3. 실제 사진 삽입 (중요!): 글을 쓰다가 시각적 자료(기사 사진, 식당 사진 등)가 들어갈 만한 적절한 위치에 정확히 `[IMAGE_PLACEHOLDER]` 라고만 텍스트를 삽입하세요. (최소 3개 이상 분산 배치)
    4. 정보 요약 섹션: 글 하단에 `<h3>📍 정보 요약 & 꿀팁</h3>` 을 만들고 필요한 정보를 정리하세요.
    5. 광고 삽입: 본문 중간에 딱 한 번 `[COUPANG_AD]` 텍스트를 넣으세요.
    6. 해시태그: 맨 아래에 해시태그 10개를 작성하세요.
    7. 절대 마크다운(```html 등)을 앞뒤에 붙이지 마세요. 순수 HTML 태그만 출력하세요.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.75
    )
    
    final_html = response.choices[0].message.content.strip()
    
    # 🧹 1. 골칫거리였던 ```html 및 ``` 마크다운 태그 강제 삭제
    final_html = final_html.replace("```html", "").replace("```", "").strip()
    
    # 2. 제목 추출
    title = "오늘의 인사이트"
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = final_html.replace(f"<h1>{title}</h1>", "")

    # 🖼️ 3. [IMAGE_PLACEHOLDER]를 실제 웹 이미지로 치환
    def replace_placeholder(match):
        img_url = ""
        # 1순위: Tavily가 찾아온 실제 기사/장소/유튜브 사진 사용
        if real_images:
            img_url = real_images.pop(0) 
        # 2순위: 실제 사진이 모자라면 Pexels에서 예비 사진 충당
        else:
            img_url = get_thumbnail_image("trend " + subject[:10])
            
        if img_url:
            return f'<div style="text-align:center; margin: 50px 0;"><img src="{img_url}" alt="포스팅 관련 실제 이미지" style="max-width:100%; border-radius:12px; box-shadow: 0 6px 12px rgba(0,0,0,0.15);"></div>'
        return ""

    final_html = re.sub(r'\[IMAGE_PLACEHOLDER\]', replace_placeholder, final_html)
    
    # 4. 쿠팡 광고 및 마무리 문구 조합
    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    final_content = final_content + DISCLAIMER_HTML
    
    return title, final_content
