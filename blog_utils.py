import os
import requests
import random
import re  # 👈 문자열 치환(정규식)을 위해 새롭게 추가됨
from openai import OpenAI

# API 키 및 클라이언트 초기화
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

COUPANG_AD_HTML = """
<div style="text-align: center; margin: 50px 0; padding: 25px; border: 2px dashed #0073e9; border-radius: 12px; background-color: #f8fbff;">
    <p style="margin-bottom: 15px; font-weight: bold; color: #1a1a1a; font-size: 17px;">🎁 T대디가 엄선한 오늘의 추천 특가! 🎁</p>
    <a href="https://link.coupang.com/a/dYVf3W" target="_blank" style="display: inline-block; padding: 16px 32px; background-color: #0073e9; color: #ffffff !important; text-decoration: none; font-weight: bold; border-radius: 8px; font-size: 18px; box-shadow: 0 4px 10px rgba(0,115,233,0.3); transition: all 0.3s;">
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
    url = f"https://api.pexels.com/v1/search?query={keyword}&per_page=15&locale=en-US"
    
    try:
        res = requests.get(url, headers=headers).json()
        photos = res.get('photos', [])
        if photos:
            random_photo = random.choice(photos)
            return random_photo['src']['large']
    except Exception as e:
        print(f"❌ Pexels 이미지 검색 실패: {e}")
    return ""

def generate_blog_post(system_role, subject, search_context):
    """지정된 페르소나와 구조에 맞춰 힙한 블로그 HTML 코드를 생성합니다."""
    
    prompt = f"""
    당신은 인스타그램과 블로그에서 엄청난 인기를 끄는 스타 블로거 **'지니'**입니다. 
    방금 제공받은 정보를 바탕으로 본인이 직접 경험한 것처럼 생생하고 힙한 감성의 블로그 포스팅을 HTML 형식으로 작성해주세요. 독자들과 수다를 떠는 듯한 친근한 말투(해요체)와 이모지를 풍부하게 사용하세요.

    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}
    [당신의 페르소나]: {system_role}

    [필수 작성 구조 및 규칙]
    1. 제목: 맨 첫 줄은 무조건 `<h1>✨ 제목</h1>` 형식으로 매력적인 제목을 지으세요.
    2. 넓은 띄어쓰기(가독성): 모바일 독자를 위해 문단 사이 간격이 아주 넓어야 합니다. 새로운 문단이나 주제가 시작될 때는 반드시 `<p style="margin-bottom: 40px; line-height: 1.8; font-size: 16px;">` 태그를 사용하여 여백을 충분히 주세요.
    3. 다중 이미지 자동 삽입 (가장 중요): 글을 쓰다가 시각적 자료가 필요한 곳(최소 3곳 이상)에 절대 '(사진 1: 설명)' 같은 한글을 쓰지 마세요. 
       대신 해당 상황에 맞는 영어 검색어를 넣어 `[IMAGE: 영어 검색어]` 형식으로 코드만 삽입하세요.
       예시: [IMAGE: delicious pasta plating], [IMAGE: cozy cafe interior], [IMAGE: modern city street]
       이 코드는 나중에 시스템이 실제 고화질 사진으로 자동 변환합니다.
    4. 정보 요약 섹션: 글 하단에 `<h3>📍 정보 요약 & 꿀팁</h3>` 을 만들고 주소, 영업시간, 지니의 꿀팁 등을 작성하세요.
    5. 광고 삽입: 본문 중간에 흐름이 바뀌는 곳에 딱 한 번 `[COUPANG_AD]` 텍스트를 넣으세요.
    6. 해시태그: 맨 아래에 관련 해시태그 10개를 띄어쓰기로 구분하여 작성하세요.
    7. HTML 태그 외의 마크다운 기호(```html 등)는 절대 출력하지 마세요.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.75
    )
    
    final_html = response.choices[0].message.content.strip()
    
    # 1. 제목 추출
    title = "오늘의 인사이트"
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = final_html.replace(f"<h1>{title}</h1>", "")

    # 2. [IMAGE: 검색어] 코드를 찾아 실제 Pexels 이미지 HTML로 변환하는 함수
    def replace_with_image(match):
        keyword = match.group(1).strip()
        img_url = get_thumbnail_image(keyword)
        if img_url:
            # 여백을 넉넉히 준 이미지 컨테이너 반환
            return f'<div style="text-align:center; margin: 50px 0;"><img src="{img_url}" alt="{keyword}" style="max-width:100%; border-radius:12px; box-shadow: 0 6px 12px rgba(0,0,0,0.15);"></div>'
        return "" # 이미지를 못 찾으면 해당 텍스트 삭제

    # 정규식(Regex)을 사용하여 [IMAGE: ...] 패턴을 모두 찾아 치환 실행
    final_html = re.sub(r'\[IMAGE:\s*(.*?)\]', replace_with_image, final_html)
    
    # 3. 쿠팡 광고 및 마무리 문구 조합
    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    final_content = final_content + DISCLAIMER_HTML
    
    return title, final_content
