import streamlit as st
import feedparser
import requests
import random
import smtplib
import ssl
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI

# ====== [기본 설정] ======
st.set_page_config(page_title="🧠 Insight Tech Blog", layout="wide")

# ====== [보안] Secrets 키 가져오기 ======
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    TELEGRAM_CHAT_ID = st.secrets["CHAT_ID"]
    SENDER_EMAIL = st.secrets["EMAIL_USER"]
    SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    PEXELS_API_KEY = st.secrets["PEXELS_API_KEY"]
except Exception as e:
    st.error(f"🚨 Secrets 설정 오류: {e}")
    st.stop()

# 모델 설정
MODEL_NAME = "gpt-4o"

# 뉴스 소스 (구글 뉴스 검색 위주로 사용)
RSS_FEEDS = {
    "TechCrunch": "https://techcrunch.com/feed/",
    "Wired": "https://www.wired.com/feed/rss",
    "Verge": "https://www.theverge.com/rss/index.xml",
}

# ====== [함수] ======

def init_client():
    return OpenAI(api_key=OPENAI_API_KEY)

def fetch_two_news(topic=None):
    """주제와 관련된 기사 2개를 가져옵니다."""
    articles = []
    
    if topic and topic.strip():
        encoded_topic = urllib.parse.quote(topic)
        rss_url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=en-US&gl=US&ceid=US:en"
        source_name = f"Google News ({topic})"
    else:
        source_name = "Random Tech News"
        rss_url = random.choice(list(RSS_FEEDS.values()))

    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None, None
        
        # 기사가 충분하면 2개, 부족하면 1개만 가져옴
        count = min(len(feed.entries), 2)
        for i in range(count):
            entry = feed.entries[i]
            articles.append({
                "title": entry.title,
                "summary": getattr(entry, 'summary', '내용 없음'),
                "link": entry.link
            })
            
        return source_name, articles
    except Exception as e:
        st.error(f"뉴스 수집 에러: {e}")
        return None, None

def generate_insight_blog(client, articles):
    """기사 2개를 합쳐서 통찰력 있는 블로그 글을 작성합니다."""
    
    # 기사 내용 합치기
    content_mix = ""
    links_text = ""
    for idx, art in enumerate(articles):
        content_mix += f"[기사 {idx+1}] 제목: {art['title']}\n내용: {art['summary']}\n\n"
        links_text += f"- 🔗 [참고 기사 {idx+1}]({art['link']})\n"

    system_prompt = """
    당신은 IT 업계의 흐름을 꿰뚫어 보는 '친절한 테크 해설가'입니다.
    초보자도 이해하기 쉬운 비유와 부드러운 말투(해요체)를 사용합니다.
    
    [작성 미션]
    주어진 2개의 기사 내용을 종합하여 하나의 완결된 블로그 포스팅을 작성하세요.
    단순 번역이 아니라, 두 기사의 연관성을 찾고 '왜 이 뉴스가 중요한지'를 설명해야 합니다.
    
    [글 구조]
    1. **제목**: 호기심을 자극하는 매력적인 제목 (이모지 포함)
    2. **들어가며**: 오늘 다룰 이슈가 무엇인지 가볍게 소개
    3. **핵심 내용 쉽게 풀기**: 
       - 두 기사의 내용을 자연스럽게 엮어서 설명
       - 어려운 IT 용어는 쉽게 풀어서 설명 (예: "LLM은 마치 책을 아주 많이 읽은 똑똑한 도서관 사서와 같아요")
    4. **인사이트 (중요 ⭐)**: 
       - 이 뉴스가 우리 삶이나 업계에 미칠 영향
       - 현직자 관점의 해석
    5. **마무리**: 독자에게 던지는 질문이나 정리
    """

    user_prompt = f"""
    아래 뉴스 기사들을 바탕으로 블로그 글을 써주세요.
    
    {content_mix}
    
    (마지막에 출처 링크는 제가 따로 붙일 테니 본문만 작성해주세요.)
    """

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content, links_text
    except Exception as e:
        return f"작성 중 오류 발생: {e}", ""

def get_visual_keyword(client, text):
    """글 내용에 어울리는 이미지 검색 키워드(영어) 추출"""
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "Extract 1 main English keyword for Pexels image search based on the text. E.g., 'Artificial Intelligence', 'Cybersecurity'."},
                {"role": "user", "content": text[:500]} # 앞부분만 참조
            ],
            temperature=0.3
        )
        return res.choices[0].message.content.strip()
    except: return "Technology"

def fetch_pexels_images(query, count=2):
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": count, "orientation": "landscape", "size": "medium"}
    try:
        res = requests.get(url, headers=headers, params=params)
        return [p['src']['landscape'] for p in res.json()['photos']] if res.status_code == 200 else []
    except: return []

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = [message[i:i+3000] for i in range(0, len(message), 3000)]
    try:
        for i, chunk in enumerate(chunks):
            text = chunk if i == 0 else f"...(이어서)\n{chunk}"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})
        return True
    except: return False

def send_email(recipient_email, subject, body, image_urls):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = recipient_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        if image_urls:
            msg.attach(MIMEText("\n\n[첨부 이미지]\n" + "\n".join(image_urls), 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        server.quit()
        return True
    except: return False

# ====== [UI] 메인 화면 ======
st.title("🧠 Insight Tech Blog")
st.caption("기사 2개 통합 분석 + 초보자용 해설 + 인사이트")

if 'generated' not in st.session_state:
    st.session_state['generated'] = None

with st.sidebar:
    st.header("🔍 주제 선정")
    topic = st.text_input("관심 키워드", placeholder="예: AI, Apple, 반도체")
    
    # 버튼 하나로 통합 (원클릭)
    if st.button("글 작성 시작 🚀", type="primary"):
        with st.spinner("1. 최신 기사를 찾고 있습니다..."):
            source, articles = fetch_two_news(topic)
            
        if articles:
            with st.spinner("2. 내용을 분석하고 인사이트를 도출 중입니다..."):
                client = init_client()
                post_body, links = generate_insight_blog(client, articles)
                
            with st.spinner("3. 어울리는 이미지를 찾고 있습니다..."):
                keyword = get_visual_keyword(client, post_body)
                images = fetch_pexels_images(keyword, count=2)
                
            # 결과 저장
            st.session_state['generated'] = {
                'post': post_body,
                'links': links,
                'images': images,
                'source': source
            }
        else:
            st.error("관련 기사를 찾지 못했습니다. 다른 키워드로 시도해보세요!")

# 결과 표시 화면
if st.session_state['generated']:
    data = st.session_state['generated']
    
    # 1. 이미지 표시 (2개 나란히)
    if data['images']:
        cols = st.columns(2)
        for i, img in enumerate(data['images']):
            cols[i].image(img, use_container_width=True)
            
    # 2. 블로그 본문
    st.markdown(data['post'])
    
    # 3. 출처 표기 (구분선 아래)
    st.divider()
    st.markdown("### 📚 참고 기사 원문")
    st.markdown(data['links'])
    
    # 4. 전송 버튼
    st.divider()
    c1, c2 = st.columns(2)
    
    full_content = f"{data['post']}\n\n{data['links']}"
    
    if c1.button("텔레그램 전송 ✈️"):
        if send_telegram(full_content):
            st.success("텔레그램으로 전송되었습니다!")
            
    if c2.button("이메일 전송 📧"):
        # 제목 추출 (첫 줄)
        subject = data['post'].split('\n')[0].replace('#', '').strip()
        if send_email(SENDER_EMAIL, f"[Insight Blog] {subject}", full_content, data['images']):
            st.success("이메일로 전송되었습니다!")
