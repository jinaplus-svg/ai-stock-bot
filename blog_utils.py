import os
import requests
from openai import OpenAI

# API 키 및 클라이언트 초기화
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")

COUPANG_AD_HTML = """
<div style="text-align: center; margin: 30px 0;">
    <a href="https://link.coupang.com/a/dYVf3W" target="_blank">
        <img src="https://image9.coupangcdn.com/image/affiliate/banner/ba0d7b0572b94e82be0592e35d1fcc51@2x.jpg" alt="추천 상품 보러가기" style="max-width: 100%; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    </a>
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
    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/v1/search?query={keyword}&per_page=1"
    try:
        res = requests.get(url, headers=headers).json()
        if res.get('photos'):
            return res['photos'][0]['src']['large']
    except:
        pass
    return ""

def generate_blog_post(system_role, subject, search_context, image_keyword):
    # 썸네일 이미지 가져오기
    image_url = get_thumbnail_image(image_keyword)
    image_html = f'<div style="text-align:center;"><img src="{image_url}" alt="{image_keyword}" style="max-width:100%; border-radius:12px; margin-bottom:25px;"></div>' if image_url else ""
    
    prompt = f"""
    당신은 '{system_role}' 분야의 최고 전문가입니다. 독자들에게 친근하고 재미있게 정보를 전달해주세요.
    다음 최신 정보를 바탕으로 블로그 포스팅을 HTML 형식으로 작성해주세요.
    
    [최신 정보]: {search_context}
    [주제]: {subject}
    
    [작성 규칙]
    1. 첫 줄은 무조건 <h1>포스팅 제목</h1> 으로 시작하세요. (SEO 최적화된 매력적인 제목)
    2. 본문은 이모지를 적절히 섞어 친근한 말투(해요체 등)로 작성하세요. 가독성을 위해 <h2>, <h3>, <p>, <ul> 등을 적극 활용하세요.
    3. 본문의 흐름이 중간쯤 전환되는 적절한 위치에 정확히 [COUPANG_AD] 라고 텍스트를 한 번만 삽입하세요.
    4. 글의 마무리를 짓고, 맨 마지막 줄에는 관련 해시태그 10개를 띄어쓰기로 구분하여 작성하세요. (예: #맛집 #데이트코스)
    5. HTML 태그 밖의 마크다운 기호(```html 등)는 절대 출력하지 마세요.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.75
    )
    
    raw_html = response.choices[0].message.content.strip()
    
    # 제목 추출 및 본문에서 제거
    title = "오늘의 인사이트"
    if "<h1>" in raw_html and "</h1>" in raw_html:
        title = raw_html.split("<h1>")[1].split("</h1>")[0]
        raw_html = raw_html.replace(f"<h1>{title}</h1>", "")
    
    # 쿠팡 광고 및 마무리 문구 조합
    final_content = raw_html.replace("[COUPANG_AD]", COUPANG_AD_HTML)
    final_content = image_html + final_content + COUPANG_AD_HTML + DISCLAIMER_HTML
    
    return title, final_content
