import os
import requests
from openai import OpenAI

# API 키 및 클라이언트 초기화
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# 🌟 획기적으로 개선된 쿠팡 광고 HTML (디자인 박스 + 클릭 유도 버튼 형태)
COUPANG_AD_HTML = """
<div style="text-align: center; margin: 30px 0; padding: 20px; border: 1px dashed #0073e9; border-radius: 10px; background-color: #f0f8ff;">
    <p style="margin-bottom: 15px; font-weight: bold; color: #333; font-size: 16px;">🎁 T대디가 엄선한 오늘의 추천 특가! 🎁</p>
    <a href="https://link.coupang.com/a/d0lKD1" target="_blank" rel="noopener noreferrer" style="display: inline-block; padding: 15px 30px; background-color: #0073e9; color: #ffffff !important; text-decoration: none; font-weight: bold; border-radius: 5px; font-size: 18px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: background-color 0.3s;">
        👉 추천 상품 보러가기
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
    """(임시) 썸네일 이미지를 가져오는 함수입니다. 현재는 고정 이미지를 사용합니다."""
    # 향후 Pexels나 Tavily Image API로 교체 가능
    return "https://images.pexels.com/photos/3183197/pexels-photo-3183197.jpeg?auto=compress&cs=tinysrgb&w=1260&h=750&dpr=2"

def generate_blog_post(system_role, subject, search_context):
    """지정된 페르소나에 맞춰 블로그 HTML 코드를 생성하고 광고를 통합합니다."""
    
    prompt = f"""
    당신은 글로벌 '최고 전문가'이자 대중과 소통하는 스타 블로거 **'지니'**입니다. 
    방금 제공받은 최신 정보를 바탕으로, 마치 본인이 직접 경험한 것처럼 생생하고 힙한 감성의 블로그 포스팅을 HTML 형식으로 작성해주세요. 독자들과 수다를 떠는 듯한 친근한 말투(해요체)를 사용하고 이모지를 풍부하게 써주세요.

    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}
    [당신의 페르소나]: {system_role}

    [필수 작성 구조 및 규칙]
    1.  **제목:** 응답의 맨 첫 줄은 무조건 `<h1>✨ 제목</h1>` 형식이어야 합니다. SEO를 고려하면서도 클릭을 유도하는 매력적인 제목을 지으세요.
    2.  **본문:** 주입식 정보 전달은 절대 금지! 본인의 감정(와!, 미쳤다!, 존맛탱 등)을 섞어 재미있게 묘사하세요. 소제목(`<h2>✨ 주제</h2>`)을 활용해 가독성을 높이세요.
    3.  **광고 삽입:** 본문의 흐름이 자연스럽게 바뀌는 중간 지점에 정확히 `[COUPANG_AD]` 라는 텍스트를 한 번만 삽입하세요.
    4.  **마무리:** 독자들의 호응을 유도하며 글을 맺으세요.
    5.  **해시태그:** 맨 마지막 줄에는 관련 해시태그 10개를 띄어쓰기로 구분하여 작성하세요.
    6.  HTML 태그 외의 마크다운 기호(```html 등)는 절대 출력하지 마세요.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    
    response_text = response.choices[0].message.content.strip()
    
    # 1. 제목 추출 및 본문 정리
    title = "오늘의 인사이트"
    final_html = response_text
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = final_html.replace(f"<h1>{title}</h1>", "")
    
    # 2. 썸네일 이미지 및 광고/공지 HTML 조합
    # 본문 중간의 [COUPANG_AD]를 진짜 HTML 버튼으로 치환
    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    # 전체 구조 조합
    final_content = final_content + COUPANG_AD_HTML + DISCLAIMER_HTML
    
    return title, final_content
