import os
import requests
import re
import random
from openai import OpenAI

# API 키 및 클라이언트 초기화
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# 4대 이미지/검색 API 키
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
PIXABAY_API_KEY = os.environ.get("PIXABAY_API_KEY")
UNSPLASH_API_KEY = os.environ.get("UNSPLASH_API_KEY")

# 🌟 새로운 쿠팡 링크 & 클릭을 유도하는 고급 CSS 버튼 ('T대디' 문구 제거)
COUPANG_AD_HTML = """
<div style="text-align: center; margin: 60px 0; padding: 35px 20px; border: 2px solid #0073e9; border-radius: 12px; background-color: #f8fbff; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
    <p style="margin-bottom: 20px; font-size: 18px; font-weight: 800; color: #111; word-break: keep-all;">🎁 특별히 엄선한 오늘의 추천 특가! 🎁</p>
    <a href="https://link.coupang.com/a/d12zsf" target="_top" style="display: inline-block; padding: 16px 35px; background-color: #0073e9; color: #ffffff !important; text-decoration: none; font-weight: bold; border-radius: 8px; font-size: 18px; box-shadow: 0 4px 6px rgba(0, 115, 233, 0.3);">
        👉 추천 상품 상세 정보 확인하기
    </a>
    <p style="margin-top: 15px; font-size: 13px; color: #666; word-break: keep-all;">(한정 수량이니 서두르세요! 🏃‍♂️)</p>
</div>
"""

DISCLAIMER_HTML = """
<p style="font-size:12px; color:#888; text-align:center; margin-top:60px; padding-top:20px; border-top:1px solid #eee;">
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

def get_best_image(description):
    """4개의 플랫폼(Unsplash, Pixabay, Pexels, Tavily) 중 랜덤하게 이미지를 가져옵니다."""
    try:
        kw_res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Translate this photo description into a short English search keyword (max 3 words) for stock photos. Description: {description}. Just output the keywords without any quotes or explanations."}]
        )
        eng_keyword = kw_res.choices[0].message.content.strip()
    except:
        eng_keyword = "beautiful landscape"

    sources = []
    if UNSPLASH_API_KEY: sources.append('unsplash')
    if PIXABAY_API_KEY: sources.append('pixabay')
    if PEXELS_API_KEY: sources.append('pexels')
    if TAVILY_API_KEY: sources.append('tavily')
    
    random.shuffle(sources)

    for source in sources:
        url = ""
        try:
            if source == 'unsplash':
                res = requests.get(f"https://api.unsplash.com/search/photos?query={eng_keyword}&per_page=5", headers={"Authorization": f"Client-ID {UNSPLASH_API_KEY}"}).json()
                if res.get('results'): url = random.choice(res['results'])['urls']['regular']
            elif source == 'pixabay':
                res = requests.get(f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={eng_keyword}&image_type=photo&per_page=5").json()
                if res.get('hits'): url = random.choice(res['hits'])['largeImageURL']
            elif source == 'pexels':
                res = requests.get(f"https://api.pexels.com/v1/search?query={eng_keyword}&per_page=5", headers={"Authorization": PEXELS_API_KEY}).json()
                if res.get('photos'): url = random.choice(res['photos'])['src']['large']
            elif source == 'tavily':
                res = requests.post("https://api.tavily.com/search", json={"api_key": TAVILY_API_KEY, "query": description, "search_depth": "basic", "include_images": True}).json()
                if res.get('images'): url = res['images'][0]
        except Exception as e:
            print(f"⚠️ [{source}] 이미지 검색 오류: {e}")

        if url:
            source_name = "Unsplash" if source == 'unsplash' else "Pixabay" if source == 'pixabay' else "Pexels" if source == 'pexels' else "Web Search"
            return url, source_name

    return "", "none"

def generate_blog_post(system_role, subject, search_context):
    """2단계 분할 작성 + 매거진 스타일 폰트/이미지 강제 적용"""
    
    system_prompt = f"당신은 글로벌 '최고 전문가'이자 스타 블로거 **'지니'**입니다. 페르소나: {system_role}\n독자와 수다 떠는 듯한 친근한 해요체와 이모지를 풍부하게 사용하세요. 모든 응답은 HTML 태그로만 작성하고, ```html 같은 마크다운 기호는 절대 쓰지 마세요."

    messages = [{"role": "system", "content": system_prompt}]
    
    # 🌟 1차 명령 
    prompt_part1 = f"""
    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}

    위 정보를 바탕으로 심층 블로그 포스팅의 **'1부'**를 아주 길게 작성해주세요.

    🔥 [가독성 및 디자인 필수 규칙] 🔥
    1. **단락 제목 태그:** 단락의 소제목은 반드시 순수하게 `<h2>` 또는 `<h3>` 태그만 사용하세요. (속성 추가 금지)
    2. **짧은 호흡:** 한 문단(`<p>`)은 무조건 2~3문장 이내로 짧게 쓰세요.
    3. **여백:** 문단과 문단 사이에는 반드시 `<br><br>`을 넣어주세요.

    [1부 필수 작성 구조]
    1. 맨 첫 줄은 무조건 `<h1>✨ 제목</h1>` 
    2. 프롤로그: 독자 호기심 자극 및 경험담 (최소 500자)
    3. 심층 본문 A: 전문가 시각 분석 (최소 500자)
    4. 글 흐름에 맞춰 `(사진 1: 구체적 묘사)`, `(사진 2: 구체적 묘사)`, `(사진 3: 구체적 묘사)` 3개 삽입.
    """
    messages.append({"role": "user", "content": prompt_part1})
    
    print("🧠 1차 생성 중: 서론 및 본문 A 작성 (gpt-4o-mini)...")
    res1 = client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.75)
    part1_html = res1.choices[0].message.content.strip()
    
    # 🌟 2차 명령 
    messages.append({"role": "assistant", "content": part1_html})
    prompt_part2 = """
    아주 훌륭합니다! 앞선 내용과 자연스럽게 이어지는 **'2부'**를 마저 아주 길게 작성해주세요. (제목 <h1>은 금지)

    🔥 앞서 지시한 **[가독성 및 디자인 필수 규칙]**(<h2>사용, 짧은 문단, <br><br> 여백)을 엄격하게 지키세요!

    [2부 필수 작성 구조]
    1. 심층 본문 B: 과거 사례, 구체적인 전망 (최소 1000자 이상)
    2. 중간중간 `(사진 4: 구체적 묘사)`, `(사진 5: 구체적 묘사)`, `(사진 6: 구체적 묘사)` 3개 삽입.
    3. 흐름이 바뀌는 곳에 `[COUPANG_AD]` 정확히 1회 삽입.
    4. 하단에 `<h3>📍 정보 요약 및 지니의 꿀팁</h3>` 섹션 생성. (<ul> 태그 활용)
    5. 에필로그 및 마무리 인사
    6. 맨 마지막 줄에 관련 해시태그 15개를 띄어쓰기로 작성.
    """
    messages.append({"role": "user", "content": prompt_part2})

    print("🧠 2차 생성 중: 본문 B 및 마무리 작성 (gpt-4o-mini)...")
    res2 = client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.75)
    part2_html = res2.choices[0].message.content.strip()

    # 🌟 1, 2부 텍스트 합체
    final_html = part1_html + "\n<br><br>\n" + part2_html
    
    # 🌟 디자인 강제 적용 (스크린샷 느낌 완벽 구현)
    final_html = final_html.replace("<h2>", "<h2 style='font-size: 24px; font-weight: 800; color: #111; margin-top: 50px; margin-bottom: 20px; line-height: 1.4; word-break: keep-all;'>")
    final_html = final_html.replace("<h3>", "<h3 style='font-size: 20px; font-weight: 700; color: #333; margin-top: 40px; margin-bottom: 15px;'>")
    final_html = final_html.replace("<p>", "<p style='font-size: 16px; line-height: 1.8; color: #444; margin-bottom: 15px; word-break: keep-all;'>")

    # 제목 분리
    title = "오늘의 인사이트"
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = re.sub(r'<h1.*?>.*?</h1>', '', final_html)
    
    # 🎲 다중 플랫폼 이미지 통합 및 캡션 디자인
    image_placeholders = re.findall(r'\(사진 \d+:[^)]+\)', final_html)
    for i, placeholder in enumerate(image_placeholders):
        description = placeholder.split(':', 1)[1].strip(')')
        print(f"📸 사진 {i+1}/{len(image_placeholders)} 검색 중... ({description[:20]}...)")
        
        image_url, source_name = get_best_image(description)
        
        if image_url:
            image_tag = f"""
            <div style="margin: 40px 0;">
                <img src="{image_url}" alt="{description}" style="max-width:100%; height:auto; display:block; border-radius: 8px;">
                <p style="font-size:13px; color:#888888; font-style:italic; margin-top:12px; margin-bottom:30px; line-height:1.5;">{description}</p>
            </div>
            """
            final_html = final_html.replace(placeholder, image_tag)
        else:
            final_html = final_html.replace(placeholder, "")

    # 쿠팡 배너 합체
    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    final_content = final_content + COUPANG_AD_HTML + DISCLAIMER_HTML
    
    return title, final_content
