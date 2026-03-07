import os
import requests
import re
import random
from openai import OpenAI

# API 키 및 클라이언트 초기화
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

COUPANG_AD_HTML = """
<div style="text-align: center; margin: 30px 0; padding: 20px; border: 1px dashed #0073e9; border-radius: 10px; background-color: #f0f8ff;">
    <p style="margin-bottom: 15px; font-weight: bold; color: #333; font-size: 16px;">🎁 T대디가 엄선한 오늘의 추천 특가! 🎁</p>
    <a href="https://link.coupang.com/a/dYVf3W" target="_blank" style="display: inline-block; padding: 15px 30px; background-color: #0073e9; color: #ffffff !important; text-decoration: none; font-weight: bold; border-radius: 5px; font-size: 18px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
        👉 추천 상품 상세 정보 확인하기
    </a>
    <p style="margin-top: 10px; font-size: 12px; color: #666;">(한정 수량이니 서두르세요! 🏃‍♂️)</p>
</div>
"""

DISCLAIMER_HTML = """
<p style="font-size:12px; color:#888; text-align:center; margin-top:40px; padding-top:20px; border-top:1px solid #eee;">
"이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
</p>
"""

def search_latest_info(query):
    url = "https://api.tavily.com/search"
    payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "advanced", "include_answer": True}
    try:
        response = requests.post(url, json=payload).json()
        return response.get('answer', str(response.get('results', '검색 결과를 요약할 수 없습니다.')))
    except:
        return "최신 정보를 불러오는 데 실패했습니다."

def get_thumbnail_image(keyword):
    """Pexels API를 이용해 검색 결과 15개 중 랜덤으로 1장의 사진을 가져옵니다."""
    if not PEXELS_API_KEY: return ""
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/v1/search?query={keyword}&per_page=15&locale=en-US"
    try:
        res = requests.get(url, headers=headers).json()
        photos = res.get('photos', [])
        if photos:
            return random.choice(photos)['src']['large']
    except Exception as e:
        print(f"❌ Pexels 이미지 검색 실패: {e}")
    return ""

def generate_blog_post(system_role, subject, search_context):
    prompt = f"""
    당신은 인스타그램과 블로그에서 엄청난 인기를 끄는 스타 블로거 **'지니'**입니다. 
    방금 제공받은 최신 정보를 바탕으로 생생하고 힙한 감성의 블로그 포스팅을 HTML로 작성해주세요. 친근한 말투(해요체)와 이모지를 풍부하게 써주세요.

    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}
    [당신의 페르소나]: {system_role}

    [필수 작성 구조]
    1. **제목:** 첫 줄은 무조건 `<h1>✨ 제목</h1>` 형식.
    2. **본문:** 감정 표현을 섞어 재미있게 묘사하고, `<h2>` 소제목 활용.
    3. **이미지 자리:** 본문 내용과 매칭되는 사진이 들어갈 자리를 `(사진 N: 사진에 대한 아주 짧고 명확한 한글 묘사)` 형식으로 최소 3개 이상 넣으세요.
    4. **정보 요약:** 하단에 `<h3>📍 정보 요약 & 꿀팁</h3>` 섹션.
    5. **광고:** 본문 중간에 `[COUPANG_AD]` 텍스트 1회 삽입.
    6. **마무리:** 해시태그 10개로 마무리. HTML 마크다운(```html)은 절대 출력 금지.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.75
    )
    
    final_html = response.choices[0].message.content.strip()
    
    title = "오늘의 인사이트"
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = final_html.replace(f"<h1>{title}</h1>", "")
    
    # 본문 안의 (사진 N: 묘사) 부분을 찾아 실제 Pexels 이미지로 치환
    image_placeholders = re.findall(r'\(사진 \d+:[^)]+\)', final_html)
    
    for i, placeholder in enumerate(image_placeholders):
        description = placeholder.split(':', 1)[1].strip(')')
        
        # 한글 묘사를 짧은 영어 검색어로 번역 (Pexels용)
        kw_res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Translate this photo description into a short English search keyword (max 3 words) for stock photos. Description: {description}. Just output the keywords."}]
        )
        english_keyword = kw_res.choices[0].message.content.strip()
        
        print(f"📸 사진 {i+1} 검색 중... (키워드: {english_keyword})")
        image_url = get_thumbnail_image(english_keyword)
        
        if image_url:
            # 사진 아래에 작은 글씨로 사진 묘사 캡션 추가
            image_tag = f'<div style="text-align:center;"><img src="{image_url}" alt="{description}" style="max-width:100%; border-radius:12px; margin-bottom:10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);"><p style="font-size:12px; color:#888; margin-bottom:25px;">▲ {description}</p></div>'
            final_html = final_html.replace(placeholder, image_tag)
        else:
            final_html = final_html.replace(placeholder, "")

    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    final_content = final_content + COUPANG_AD_HTML + DISCLAIMER_HTML
    
    return title, final_content
