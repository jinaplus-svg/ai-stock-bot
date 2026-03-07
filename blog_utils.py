import os
import requests
import re
from openai import OpenAI

# API 키 및 클라이언트 초기화
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

COUPANG_AD_HTML = """
<div style="text-align: center; margin: 40px 0; padding: 25px; border: 1px dashed #0073e9; border-radius: 10px; background-color: #f0f8ff;">
    <p style="margin-bottom: 20px; font-weight: bold; color: #333; font-size: 18px;">🎁 T대디가 엄선한 오늘의 추천 특가! 🎁</p>
    <a href="https://link.coupang.com/a/dYVf3W" target="_blank" style="display: inline-block; padding: 18px 35px; background-color: #0073e9; color: #ffffff !important; text-decoration: none; font-weight: bold; border-radius: 5px; font-size: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: background-color 0.3s;">
        👉 추천 상품 상세 정보 확인하기
    </a>
    <p style="margin-top: 15px; font-size: 14px; color: #666;">(한정 수량이니 서두르세요! 🏃‍♂️)</p>
</div>
"""

DISCLAIMER_HTML = """
<p style="font-size:12px; color:#888; text-align:center; margin-top:50px; padding-top:20px; border-top:1px solid #eee;">
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

def get_real_web_image(keyword):
    """Tavily API를 이용해 실제 웹(Google 등)에서 검색된 관련 이미지 URL을 가져옵니다."""
    if not TAVILY_API_KEY: return ""
    
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": keyword, # AI가 생성한 구체적 묘사
        "search_depth": "basic",
        "include_images": True # 📸 이미지 검색 활성화
    }
    
    try:
        response = requests.post(url, json=payload).json()
        images = response.get('images', [])
        # Tavily는 구글/유튜브/지도의 실제 이미지 URL을 반환합니다.
        if images:
            return images[0] # 검색 결과 중 첫 번째 이미지를 사용
    except Exception as e:
        print(f"❌ 실제 이미지 검색 실패: {e}")
    return ""

def generate_blog_post(system_role, subject, search_context):
    """지정된 페르소나와 구조에 맞춰 심층적인 블로그 HTML 코드를 생성하고, 실제 이미지를 통합합니다."""
    
    # 🌟 프롬프트 전면 개정: 글자 수 증량 및 심층 분석 요구
    prompt = f"""
    당신은 해당 분야의 글로벌 '최고 전문가'이자 대중과 소통하는 스타 블로거 **'지니'**입니다. 
    제공받은 최신 정보를 바탕으로, 마치 직접 경험하고 깊이 연구한 것처럼 **매우 깊이 있고 방대한 내용**의 블로그 포스팅을 HTML 형식으로 작성해주세요. 독자들과 소통하는 친근한 말투(해요체)를 사용하고 이모지를 풍부하게 써주세요.

    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}
    [당신의 페르소나]: {system_role}

    [필수 작성 구조 및 규칙 - 글자 수 대폭 늘리기]
    1.  **제목:** 응답의 맨 첫 줄은 무조건 `<h1>✨ 제목</h1>` 형식이어야 합니다. SEO를 고려하면서도 클릭을 유도하는 매력적이고 구체적인 제목을 지으세요. (종목명, 장소명 필수 포함)
    2.  **프롤로그:** 해당 주제에 대한 독자의 호기심을 자극하고, 당신의 깊은 관심과 경험담을 섞어 길게 작성하세요. (최소 400자)
    3.  **심층 분석 본문 (최소 4개 섹션):** 주입식 요약은 절대 금지! 정보를 다각도로 분석하여 매우 상세하게 서술하세요. (각 섹션당 최소 500자)
        * **데이터 해석:** 단순히 '수치가 올랐다'가 아니라, **'왜 올랐는지', '그 수치가 시장에 주는 의미'**를 전문가의 시각에서 심층 분석하세요.
        * **과거 사례 및 배경:** 이와 유사했던 과거 역사적 사건이나 기업의 배경 스토리를 설명하여 정보의 깊이를 더하세요.
        * **향후 전망 및 영향:** 이 정보가 앞으로 어떻게 전개될지, 독자의 일상이나 포트폴리오에 어떤 영향을 미칠지 구체적으로 전망하세요.
        * **반론 및 리스크:** (주식/뉴스) 이 정보와 다른 시각이나 잠재적인 리스크는 무엇인지 균형 잡힌 시각을 제공하세요.
    4.  **이미지 플레이스홀더:** 본문 곳곳에 사진이 들어갈 자리를 `(사진 N: 사진에 대한 구체적이고 생생한 묘사)` 형식으로 최소 4개 이상 넣어주세요. (예: `(사진 1: 구글 지도 로드뷰에서 보이는 다이너 목감점의 따뜻한 입구 전경)`)
    5.  **정보 요약 & 꿀팁 섹션:** 글 하단에 반드시 `<h3>📍 지니의 전문가급 꿀팁 & 정보 요약</h3>` 섹션을 만드세요.
        * `<ul>` Tag를 사용하여 주소(`🗺️`), 영업시간(`⏰`) 등의 실제 정보를 정리하세요. (주식의 경우 관련 지표 요약)
        * `<h4>💡 지니의 꿀팁!</h4>`을 만들어 방문 전/투자 전 꼭 알아야 할 숨겨진 팁을 적어주세요.
    6.  **에필로그 & 마무리:** 포스팅을 정리하고 독자와 소통하는 질문으로 끝을 맺으세요.
    7.  **광고 삽입:** 본문의 흐름이 자연스럽게 바뀌는 중간 지점에 정확히 `[COUPANG_AD]` 라는 텍스트를 한 번만 삽입하세요.
    8.  **마무리 해시태그:** 맨 마지막 줄에는 관련 해시태그 15개를 띄어쓰기로 구분하여 작성하세요.
    9.  HTML 태그 외의 마크다운 기호(```html 등)는 절대 출력하지 마세요.
    """

    print("🧠 OpenAI로 심층 블로그 포스팅 생성 중... (시간이 소요될 수 있습니다)")
    response = client.chat.completions.create(
        model="gpt-4", # 🌟 글의 품질과 깊이를 위해 GPT-4 사용 (기존 4o-mini는 짧게 쓰는 경향이 있음)
        messages=[{"role": "user", "content": prompt}],
        temperature=0.75 # 전문가의 균형 잡힌 시각을 위해 temperature 조정
    )
    
    response_text = response.choices[0].message.content.strip()
    
    # 1. 제목 추출 및 본문 정리
    title = "오늘의 인사이트"
    final_html = response_text
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = final_html.replace(f"<h1>{title}</h1>", "")
    
    # 2. 🎲 실제 이미지 검색 및 통합 로직 (핵심 업그레이드)
    # 정규표현식을 사용하여 이미지 플레이스홀더를 모두 찾습니다.
    # (사진 N: 사진에 대한 구체적이고 생생한 묘사)
    image_placeholders = re.findall(r'\(사진 \d+:[^)]+\)', final_html)
    
    # 🎲 각 플레이스홀더에 대해 Tavily 이미지 검색을 호출하고, 실제 이미지 태그로 치환합니다.
    for i, placeholder in enumerate(image_placeholders):
        # 플레이스홀더에서 사진 설명을 추출합니다.
        description = placeholder.split(':', 1)[1].strip(')')
        
        # 실제 웹 이미지 검색 모델을 호출합니다.
        print(f"📸 사진 {i+1} 검색 중... (구체적 묘사: {description[:30]}...)")
        image_url = get_real_web_image(description)
        
        # 이미지 태그를 생성합니다.
        if image_url:
            image_tag = f'<div style="text-align:center;"><img src="{image_url}" alt="{description}" style="max-width:100%; border-radius:12px; margin-bottom:25px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);"><p style="font-size:12px; color:#888; margin-top:-20px; margin-bottom:25px;">▲ {description} (실제 웹 검색 이미지)</p></div>'
            # 🎲 본문에서 플레이스홀더를 실제 이미지 태그로 치환합니다.
            final_html = final_html.replace(placeholder, image_tag)
        else:
            # 이미지 검색 실패 시 플레이스홀더를 삭제합니다.
            final_html = final_html.replace(placeholder, "")
            print(f"❌ 사진 {i+1} 검색 실패")

    # 3. 쿠팡 광고 및 마무리 문구 조합
    # 본문 중간의 [COUPANG_AD]를 진짜 HTML 버튼으로 치환
    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    # 전체 구조 조합
    final_content = final_content + COUPANG_AD_HTML + DISCLAIMER_HTML
    
    return title, final_content
