import os
import requests
import re
from openai import OpenAI

# API 키 및 클라이언트 초기화
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# 🌟 쿠팡 광고 HTML (대표님 맥북 배너)
COUPANG_AD_HTML = """
<div style="text-align: center; margin: 40px 0;">
    <a href="https://link.coupang.com/a/d0lKD1" target="_blank" referrerpolicy="unsafe-url"><img src="https://image3.coupangcdn.com/image/affiliate/banner/191a9ef0ae936109f897e1b063491dd3@2x.jpg" alt="Apple 2026 맥북 네오 A18 Pro칩, 실버, A18 Pro 6코어, 5코어, 8GB, 256GB, 한글" width="120" height="240"></a>
</div>
"""

DISCLAIMER_HTML = """
<p style="font-size:12px; color:#888; text-align:center; margin-top:50px; padding-top:20px; border-top:1px solid #eee;">
"이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
</p>
"""

def search_latest_info(query):
    url = "https://api.tavily.com/search"
    payload = {"api_key": TAVILY_API_KEY, "query": query, "search_depth": "advanced", "include_answer": True}
    try:
        response = requests.post(url, json=payload).json()
        return response.get('answer', str(response.get('results', '검색 결과를 요약할 수 없습니다.')))
    except Exception as e:
        print(f"❌ Tavily 검색 실패: {e}")
        return "최신 정보를 불러오는 데 실패했습니다."

def get_real_web_image(keyword):
    if not TAVILY_API_KEY: return ""
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": keyword, 
        "search_depth": "basic",
        "include_images": True 
    }
    try:
        response = requests.post(url, json=payload).json()
        images = response.get('images', [])
        if images:
            return images[0] 
    except Exception as e:
        print(f"❌ 실제 이미지 검색 실패: {e}")
    return ""

def generate_blog_post(system_role, subject, search_context):
    """2단계로 나누어 AI에게 명령을 내려 글자 수를 강제로 늘립니다."""
    
    # 공통 시스템 프롬프트
    system_prompt = f"당신은 해당 분야의 글로벌 '최고 전문가'이자 스타 블로거 **'지니'**입니다. 페르소나: {system_role}\n모든 응답은 HTML 태그로만 작성하고, ```html 같은 마크다운 기호는 절대 쓰지 마세요. 독자와 소통하는 친근한 해요체와 이모지를 사용하세요."

    messages = [{"role": "system", "content": system_prompt}]
    
    # 🌟 1차 명령: 1부 작성 (제목, 프롤로그, 분석 전반부)
    prompt_part1 = f"""
    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}

    위 정보를 바탕으로 심층 블로그 포스팅의 **'1부'**를 아주 길게 작성해주세요.
    1. 맨 첫 줄은 무조건 `<h1>✨ 제목</h1>` (종목명/장소명 필수 포함)
    2. 프롤로그: 독자 호기심 자극 및 경험담 (최소 500자)
    3. 본문 전반부: 데이터 심층 해석 및 과거 배경 설명 (최소 1000자 이상, 주입식 요약 금지)
    4. 중간중간에 `(사진 1: 구체적이고 생생한 묘사)`, `(사진 2: 구체적 묘사)` 플레이스홀더 2개 필수 삽입.
    """
    messages.append({"role": "user", "content": prompt_part1})
    
    print("🧠 1차 생성 중: 제목 및 본문 전반부 작성 (gpt-4o-mini)...")
    res1 = client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.75)
    part1_html = res1.choices[0].message.content.strip()
    
    # 🌟 2차 명령: 2부 작성 (이전 대화 내용을 기억한 상태로 후반부 이어서 작성)
    messages.append({"role": "assistant", "content": part1_html})
    prompt_part2 = """
    아주 훌륭합니다! 이제 앞선 내용과 자연스럽게 이어지는 **'2부'**를 마저 아주 길게 작성해주세요. (제목 <h1>은 다시 쓰지 마세요)
    1. 본문 후반부: 향후 전망, 독자에게 미칠 영향, 반론 및 리스크 (최소 1000자 이상)
    2. 중간에 `(사진 3: 구체적 묘사)`, `(사진 4: 구체적 묘사)` 플레이스홀더 2개 필수 삽입.
    3. 흐름이 바뀌는 곳에 `[COUPANG_AD]` 라는 텍스트 정확히 1회 삽입.
    4. 하단에 `<h3>📍 지니의 전문가급 꿀팁 & 정보 요약</h3>` 생성 (<ul> 태그로 주소, 시간, 지표 등 상세 정리 및 <h4>💡 지니의 꿀팁!</h4> 포함)
    5. 에필로그 및 마무리 인사
    6. 맨 마지막 줄에 관련 해시태그 15개를 띄어쓰기로 작성.
    """
    messages.append({"role": "user", "content": prompt_part2})

    print("🧠 2차 생성 중: 본문 후반부 및 마무리 작성 (gpt-4o-mini)...")
    res2 = client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.75)
    part2_html = res2.choices[0].message.content.strip()

    # 🌟 1부와 2부 텍스트 완벽 합체!
    final_html = part1_html + "\n\n" + part2_html
    
    # 제목 추출 로직
    title = "오늘의 인사이트"
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = final_html.replace(f"<h1>{title}</h1>", "")
    
    # 실제 이미지 검색 및 통합 로직
    image_placeholders = re.findall(r'\(사진 \d+:[^)]+\)', final_html)
    for i, placeholder in enumerate(image_placeholders):
        description = placeholder.split(':', 1)[1].strip(')')
        print(f"📸 사진 {i+1} 검색 중... (구체적 묘사: {description[:30]}...)")
        image_url = get_real_web_image(description)
        
        if image_url:
            image_tag = f'<div style="text-align:center;"><img src="{image_url}" alt="{description}" style="max-width:100%; border-radius:12px; margin-bottom:25px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);"><p style="font-size:12px; color:#888; margin-top:-20px; margin-bottom:25px;">▲ {description}</p></div>'
            final_html = final_html.replace(placeholder, image_tag)
        else:
            final_html = final_html.replace(placeholder, "")
            print(f"❌ 사진 {i+1} 검색 실패")

    # 쿠팡 배너 합체
    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    final_content = final_content + COUPANG_AD_HTML + DISCLAIMER_HTML
    
    return title, final_content
