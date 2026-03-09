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

# 🌟 쿠팡 광고 HTML (대표님 전용 맥북 배너)
COUPANG_AD_HTML = """
<div style="text-align: center; margin: 50px 0;">
    <a href="https://link.coupang.com/a/d0lKD1" target="_blank" referrerpolicy="unsafe-url"><img src="https://image3.coupangcdn.com/image/affiliate/banner/191a9ef0ae936109f897e1b063491dd3@2x.jpg" alt="Apple 2026 맥북 네오 A18 Pro칩, 실버, A18 Pro 6코어, 5코어, 8GB, 256GB, 한글" width="120" height="240"></a>
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
    
    # 1. AI를 이용해 한글 묘사를 짧은 영어 검색어로 번역 (해외 플랫폼 검색 정확도 향상)
    try:
        kw_res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Translate this photo description into a short English search keyword (max 3 words) for stock photos. Description: {description}. Just output the keywords without any quotes or explanations."}]
        )
        eng_keyword = kw_res.choices[0].message.content.strip()
    except:
        eng_keyword = "beautiful landscape" # 오류 시 기본값

    # 2. 사용 가능한 API 플랫폼 리스트 구성
    sources = []
    if UNSPLASH_API_KEY: sources.append('unsplash')
    if PIXABAY_API_KEY: sources.append('pixabay')
    if PEXELS_API_KEY: sources.append('pexels')
    if TAVILY_API_KEY: sources.append('tavily')
    
    random.shuffle(sources) # 플랫폼 순서를 무작위로 섞음 (다양성 확보)

    # 3. 순차적으로 호출 시도 (하나라도 성공하면 즉시 반환)
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
                # Tavily는 웹 검색이므로 원래의 구체적인 한글 묘사를 그대로 사용
                res = requests.post("https://api.tavily.com/search", json={"api_key": TAVILY_API_KEY, "query": description, "search_depth": "basic", "include_images": True}).json()
                if res.get('images'): url = res['images'][0]
        except Exception as e:
            print(f"⚠️ [{source}] 이미지 검색 오류: {e}")

        if url:
            source_name = "Unsplash" if source == 'unsplash' else "Pixabay" if source == 'pixabay' else "Pexels" if source == 'pexels' else "Web Search"
            return url, source_name

    return "", "none"

def generate_blog_post(system_role, subject, search_context):
    """2단계 분할 작성 + 극강의 가독성 + 6개 이상의 이미지를 포함하는 최종 포스팅 생성 엔진"""
    
    system_prompt = f"당신은 글로벌 '최고 전문가'이자 스타 블로거 **'지니'**입니다. 페르소나: {system_role}\n독자와 수다 떠는 듯한 친근한 해요체와 이모지를 풍부하게 사용하세요. 모든 응답은 HTML 태그로만 작성하고, ```html 같은 마크다운 기호는 절대 쓰지 마세요."

    messages = [{"role": "system", "content": system_prompt}]
    
    # 🌟 1차 명령 (Part 1: 서론 및 심층 분석 전반부)
    prompt_part1 = f"""
    [최신 정보 데이터]: {search_context}
    [포스팅 주제]: {subject}

    위 정보를 바탕으로 심층 블로그 포스팅의 **'1부'**를 아주 길게 작성해주세요.

    🔥 [가독성 극대화 필수 규칙] 🔥
    1. **짧은 호흡:** 한 문단(`<p>`)은 무조건 2~3문장 이내로 짧게 치고 빠지세요!
    2. **숨통 트이는 여백:** 문단과 문단 사이, 소제목 위아래에는 반드시 `<br><br>` 태그를 넣어 시원시원한 여백을 만드세요.
    3. **가독성 포인트:** 중요한 문장은 `<strong>` 태그로 굵게 표시하고, `<h2>`, `<h3>` 소제목을 적극 활용하세요.

    [1부 필수 작성 구조]
    1. 맨 첫 줄은 무조건 `<h1>✨ 제목</h1>` (종목명/장소명 필수 포함)
    2. 프롤로그: 독자 호기심 자극 및 경험담 (최소 500자)
    3. 심층 본문 A: 전문가의 시각에서 심층 분석 (최소 500자)
    4. 중간중간 글의 흐름에 맞게 `(사진 1: 구체적 묘사)`, `(사진 2: 구체적 묘사)`, `(사진 3: 구체적 묘사)` 플레이스홀더를 정확히 3개 띄엄띄엄 삽입하세요.
    """
    messages.append({"role": "user", "content": prompt_part1})
    
    print("🧠 1차 생성 중: 서론 및 본문 A 작성 (gpt-4o-mini)...")
    res1 = client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.75)
    part1_html = res1.choices[0].message.content.strip()
    
    # 🌟 2차 명령 (Part 2: 본문 후반부 및 마무리)
    messages.append({"role": "assistant", "content": part1_html})
    prompt_part2 = """
    아주 훌륭합니다! 이제 앞선 내용과 자연스럽게 이어지는 **'2부'**를 마저 아주 길게 작성해주세요. (제목 <h1>은 다시 쓰지 마세요)

    🔥 앞서 지시한 **[가독성 극대화 필수 규칙]**(짧은 문단, <br><br> 여백, <strong> 강조)을 똑같이 엄격하게 지키세요!

    [2부 필수 작성 구조]
    1. 심층 본문 B: 과거 사례, 구체적인 전망, 리스크 분석 (최소 1000자 이상)
    2. 중간중간 글의 흐름에 맞게 `(사진 4: 구체적 묘사)`, `(사진 5: 구체적 묘사)`, `(사진 6: 구체적 묘사)` 플레이스홀더를 정확히 3개 띄엄띄엄 삽입하세요. (총 6개의 사진이 됩니다)
    3. 흐름이 바뀌는 곳에 `[COUPANG_AD]` 라는 텍스트를 정확히 1회 삽입.
    4. 하단에 `<h3>📍 지니의 전문가급 꿀팁 & 정보 요약</h3>` 섹션 생성.
        * `<ul>` 태그로 주소, 시간, 지표 등 상세 정보 요약
        * `<h4>💡 지니의 꿀팁!</h4>` 포함
    5. 에필로그 및 마무리 인사
    6. 맨 마지막 줄에 관련 해시태그 15개를 띄어쓰기로 작성.
    """
    messages.append({"role": "user", "content": prompt_part2})

    print("🧠 2차 생성 중: 본문 B 및 마무리 작성 (gpt-4o-mini)...")
    res2 = client.chat.completions.create(model="gpt-4o-mini", messages=messages, temperature=0.75)
    part2_html = res2.choices[0].message.content.strip()

    # 🌟 1부와 2부 텍스트 합체
    final_html = part1_html + "\n<br><br>\n" + part2_html
    
    # 제목 분리
    title = "오늘의 인사이트"
    if "<h1>" in final_html and "</h1>" in final_html:
        title = final_html.split("<h1>")[1].split("</h1>")[0]
        final_html = final_html.replace(f"<h1>{title}</h1>", "")
    
    # 🎲 다중 플랫폼 연동 이미지 검색 및 치환
    image_placeholders = re.findall(r'\(사진 \d+:[^)]+\)', final_html)
    for i, placeholder in enumerate(image_placeholders):
        description = placeholder.split(':', 1)[1].strip(')')
        print(f"📸 사진 {i+1}/{len(image_placeholders)} 검색 중... ({description[:20]}...)")
        
        # 4대 플랫폼 통합 검색 함수 호출
        image_url, source_name = get_best_image(description)
        
        if image_url:
            # 사진과 출처, 캡션을 깔끔하게 디자인하여 삽입
            image_tag = f"""
            <div style="text-align:center; margin: 30px 0;">
                <img src="{image_url}" alt="{description}" style="max-width:100%; border-radius:15px; box-shadow: 0 6px 12px rgba(0,0,0,0.15);">
                <p style="font-size:11px; color:#aaa; margin-top:8px; margin-bottom:5px;">Source: {source_name}</p>
                <p style="font-size:13px; color:#555; font-weight:bold; margin-top:0;">▲ {description}</p>
            </div>
            """
            final_html = final_html.replace(placeholder, image_tag)
        else:
            final_html = final_html.replace(placeholder, "")
            print(f"❌ 사진 {i+1} 검색 실패")

    # 쿠팡 배너 합체
    final_content = final_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    final_content = final_content + COUPANG_AD_HTML + DISCLAIMER_HTML
    
    return title, final_content
