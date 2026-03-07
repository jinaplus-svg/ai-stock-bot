# blog_utils.py (최종 업그레이드 버전)

import os
import requests
import random  # 🎲 랜덤 추출을 위해 추가
from openai import OpenAI

# API 키 및 클라이언트 초기화
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

COUPANG_AD_HTML = """
<div style="text-align: center; margin: 30px 0; padding: 20px; border: 1px dashed #0073e9; border-radius: 10px; background-color: #f0f8ff;">
    <p style="margin-bottom: 15px; font-weight: bold; color: #333; font-size: 16px;">🎁 T대디가 엄선한 오늘의 추천 특가! 🎁</p>
    <a href="https://link.coupang.com/a/dYVf3W" target="_blank" style="display: inline-block; padding: 15px 30px; background-color: #0073e9; color: #ffffff !important; text-decoration: none; font-weight: bold; border-radius: 5px; font-size: 18px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: background-color 0.3s;">
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
    """Tavily API를 이용해 최신 정보를 검색합니다."""
    url = "https://api.tavily.com/search"
    payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "advanced", "include_answer": True}
    try:
        response = requests.post(url, json=payload).json()
        return response.get('answer', str(response.get('results', '검색 결과를 요약할 수 없습니다.')))
    except Exception as e:
        print(f"❌ Tavily 검색 실패: {e}")
        return "최신 정보를 불러오는 데 실패했습니다."

def get_thumbnail_image(keyword):
    """Pexels API를 이용해 검색 결과 중 랜덤으로 사진을 가져옵니다."""
    if not PEXELS_API_KEY: return ""
    
    headers = {"Authorization": PEXELS_API_KEY}
    # 🎲 다양성을 위해 per_page를 20으로 늘립니다.
    url = f"https://api.pexels.com/v1/search?query={keyword}&per_page=20&locale=en-US"
    
    try:
        res = requests.get(url, headers=headers).json()
        photos = res.get('photos', [])
        if photos:
            # 🎲 검색된 20개의 사진 중 하나를 랜덤으로 선택합니다. (중복 방지 핵심)
            random_photo = random.choice(photos)
            return random_photo['src']['large']
    except Exception as e:
        print(f"❌ Pexels 이미지 검색 실패: {e}")
    return ""

def generate_blog_post(system_role, subject, search_context):
    """지정된 페르소나와 구조에 맞춰 힙한 블로그 HTML 코드를 생성합니다."""
    
    # 🌟 프롬프트 대폭 강화: 제공해주신 예시 스타일 반영
    prompt = f"""
    당신은 인스타그램과 블로그에서 엄청난 인기를 끄는 스타 블로거 **'지니'**입니다. 
    방금 제공받은 최신 정보를 바탕으로, 마치 본인이 직접 경험한 것처럼 생생하고 힙한 감성의 블로그 포스팅을 HTML 형식으로 작성해주세요. 독자들과 수다를 떠는 듯한 친근한 말투(해요체)를 사용하고 이모지를 풍부하게 써주세요.

    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}
    [당신의 페르소나]: {system_role}

    [필수 작성 구조 및 규칙]
    1.  **제목:** 응답의 맨 첫 줄은 무조건 `<h1>✨ 제목</h1>` 형식이어야 합니다. SEO를 고려하면서도 클릭을 유도하는 매력적인 제목을 지으세요.
    2.  **본문:** 주입식 정보 전달은 절대 금지! 본인의 감정(와!, 미쳤다!, 존맛탱 등)을 섞어 재미있게 묘사하세요. 소제목(`<h2>✨ 주제</h2>`)을 활용해 가독성을 높이세요.
    3.  **이미지 플레이스홀더:** 본문 곳곳에 사진이 들어갈 자리를 `(사진 N: 사진에 대한 생생한 묘사)` 형식으로 최소 3개 이상 넣어주세요. (예: `(사진 1: 'DINER' 네온사인이 반겨주는 입구와 따뜻한 실내 분위기)`)
    4.  **정보 요약 섹션:** 글 하단에 반드시 `<h3>📍 정보 요약 & 꿀팁</h3>` 섹션을 만드세요.
        * `<ul>` 태그를 사용하여 주소(`🗺️`), 영업시간(`⏰`) 등을 정리하세요.
        * `<h4>💡 지니의 꿀팁!</h4>`을 만들어 방문 전 꼭 알아야 할 팁을 적어주세요.
    5.  **광고 삽입:** 본문의 흐름이 자연스럽게 바뀌는 중간 지점에 정확히 `[COUPANG_AD]` 라는 텍스트를 한 번만 삽입하세요.
    6.  **마무리 & 해시태그:** 친근한 인사로 글을 맺고, 맨 마지막 줄에는 관련 해시태그 10개를 띄어쓰기로 구분하여 작성하세요.
    7.  **Pexels 키워드:** **가장 중요합니다.** HTML 작성이 끝나고 맨 아래에 `[PEXELS_KEYWORDS]: 영어 키워드` 형식으로, 이 글 전체 내용과 분위기에 딱 맞는 Pexels 검색용 영어 키워드 3~5개를 쉼표로 구분하여 작성하세요. (예: `[PEXELS_KEYWORDS]: lake view restaurant, cozy interior, gourmet food plating`)
    8.  HTML 태그 외의 마크다운 기호(```html 등)는 절대 출력하지 마세요.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    
    response_text = response.choices[0].message.content.strip()
    
    # 1. 🎲 Pexels 동적 키워드 추출 및 사진 가져오기
    title = "오늘의 인사이트"
    final_html = response_text
    dynamic_image_url = ""

    if "[PEXELS_KEYWORDS]:" in response_text:
        try:
            temp_parts = response_text.split("[PEXELS_KEYWORDS]:")
            final_html = temp_parts[0].strip() # 키워드 부분 제외한 HTML
            pexels_keywords = temp_parts[1].strip()
            # AI가 생성한 키워드로 Pexels 검색 (다양성 확보)
            dynamic_image_url = get_thumbnail_image(pexels_keywords)
        except: pass

    # 만약 키워드 추출 실패 시 주제 기반 고정 키워드로 백업
    if not dynamic_image_url:
        dynamic_image_url = get_thumbnail_image(subject[:15])

    # 2. 제목 추출 및 본문 정리
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = final_html.replace(f"<h1>{title}</h1>", "")
    
    # 3. 최상단 썸네일 이미지 HTML 생성
    image_html = f'<div style="text-align:center;"><img src="{dynamic_image_url}" alt="{title}" style="max-width:100%; border-radius:12px; margin-bottom:25px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);"></div>' if dynamic_image_url else ""
    
    # 4. 쿠팡 광고 및 마무리 문구 조합
    # 본문 중간의 [COUPANG_AD]를 진짜 HTML 버튼으로 치환
    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    # 전체 구조 조합: 썸네일 + 본문 + 하단 대형 배너(이전 버전 유지) + 공지
    final_content = image_html + final_content + COUPANG_AD_HTML + DISCLAIMER_HTML
    
    return title, final_content
