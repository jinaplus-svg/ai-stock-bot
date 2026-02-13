import streamlit as st
import feedparser
import requests
import random
import smtplib
import ssl
import urllib.parse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI  # 개인 OpenAI 사용

# ====== [기본 설정] ======
st.set_page_config(page_title="💰 Profit Blog Master", layout="wide")

# ====== [보안] Secrets에서 키 가져오기 ======
# 이미지에 있는 이름 그대로 매칭했습니다.
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    TELEGRAM_TOKEN = st.secrets["TELEGRAM_TOKEN"]
    # 이미지의 'CHAT_ID'는 텔레그램 채팅방 ID로 연결
    TELEGRAM_CHAT_ID = st.secrets["CHAT_ID"] 
    # 이미지의 'EMAIL_USER'는 보내는 사람 이메일
    SENDER_EMAIL = st.secrets["EMAIL_USER"]
    # 이미지의 'EMAIL_PASSWORD'는 앱 비밀번호
    SENDER_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    
    # [추가 필요] 아래 두 개는 꼭 추가해주세요!
    PEXELS_API_KEY = st.secrets["PEXELS_API_KEY"]
    COUPANG_ID = st.secrets["COUPANG_ID"]
    
except FileNotFoundError:
    st.error("🚨 Secrets 설정이 없습니다. Streamlit Cloud 대시보드에 키를 등록해주세요.")
    st.stop()
except KeyError as e:
    st.error(f"🚨 Secrets에 다음 키가 빠져있습니다: {e}")
    st.info("GitHub Secrets뿐만 아니라, Streamlit Cloud 배포 화면의 'Secrets'에도 같은 값을 넣어주셔야 합니다!")
    st.stop()

# 개인 API용 모델 설정 (gpt-4o 권장)
MODEL_NAME = "gpt-4o"

RSS_FEEDS = {
    "TechCrunch (AI)": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge (Tech)": "https://www.theverge.com/rss/index.xml",
    "Wired (Latest)": "https://www.wired.com/feed/rss",
    "MIT Tech Review": "https://www.technologyreview.com/feed/",
}

# ====== [함수] ======

def init_client():
    # Azure 설정 없이 개인 키만 넣으면 됩니다.
    return OpenAI(api_key=OPENAI_API_KEY)

def fetch_news(topic=None):
    if topic and topic.strip():
        encoded_topic = urllib.parse.quote(topic)
        rss_url = f"https://news.google.com/rss/search?q={encoded_topic}&hl=en-US&gl=US&ceid=US:en"
        source_name = f"Google News ({topic})"
    else:
        source_name, rss_url = random.choice(list(RSS_FEEDS.items()))

    try:
        feed = feedparser.parse(rss_url)
        if not feed.entries: return None, None, None
        entry = feed.entries[0] if topic else random.choice(feed.entries[:3])
        return source_name, entry, rss_url
    except Exception as e:
        st.error(f"뉴스 수집 에러: {e}")
        return None, None, None

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
            msg.attach(MIMEText("\n\n[이미지 링크]\n" + "\n".join(image_urls), 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, recipient_email, msg.as_string())
        server.quit()
        return True
    except: return False

def get_product_keyword(client, title, summary):
    try:
        res = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "Extract ONE specific product keyword (noun) for shopping search. If abstract, output 'Tech Gadget'."},
                {"role": "user", "content": f"Headline: {title}\nSummary: {summary}"}
            ],
            temperature=0.3
        )
        return res.choices[0].message.content.strip()
    except: return "IT기기"

def generate_blog_post(client, title, summary, link, product_keyword, profit_link):
    link_section = ""
    if profit_link:
        link_section = f"""
        \n\n---
        \n💎 **추천 아이템**
        \n"{product_keyword} 관련 제품, 쿠팡에서 확인해보세요! 👇"
        \n👉 **[할인 상품 보러가기]({profit_link})**
        \n\n(이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.)
        """
    
    system_prompt = f"""
    당신은 인기 IT 블로거 '지니'입니다. 
    기사를 읽고 블로그 글을 작성해주세요. (부드러운 해요체, 이모지 사용)
    
    [구조]
    1. 제목 (이모지 포함)
    2. 3줄 요약
    3. 본문 (쉽고 재밌게)
    4. 마무리 인사
    5. 출처 표기: "🔗 기사 원문: {link}"
    """
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Title: {title}\nSummary: {summary}"}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content + link_section
    except Exception as e: return f"Error: {e}"

def fetch_pexels_images(query, count=3):
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": count, "orientation": "landscape", "size": "medium"}
    try:
        res = requests.get(url, headers=headers, params=params)
        return [p['src']['landscape'] for p in res.json()['photos']] if res.status_code == 200 else []
    except: return []

# ====== [UI] 메인 로직 ======

st.title("💸 AI 수익화 블로그 생성기")
st.caption("Personal Edition (OpenAI)")

if 'step' not in st.session_state: st.session_state['step'] = 1
if 'news_info' not in st.session_state: st.session_state['news_info'] = None

with st.sidebar:
    st.header("1. 주제 선정")
    topic = st.text_input("검색 주제", placeholder="예: Robotics, iPhone")
    
    if st.button("뉴스 검색 & 키워드 추출 🔍", type="primary"):
        with st.spinner("AI가 돈 되는 키워드를 찾는 중..."):
            source, entry, _ = fetch_news(topic)
            if entry:
                client = init_client()
                keyword = get_product_keyword(client, entry.title, getattr(entry, 'summary', ''))
                
                st.session_state['news_info'] = {
                    'source': source,
                    'title': entry.title,
                    'summary': getattr(entry, 'summary', ''),
                    'link': entry.link,
                    'keyword': keyword
                }
                st.session_state['step'] = 2
            else:
                st.error("뉴스를 찾지 못했습니다.")

if st.session_state['step'] >= 2 and st.session_state['news_info']:
    info = st.session_state['news_info']
    
    st.info(f"📢 뉴스 발견: **{info['title']}**")
    st.success(f"💰 추천 키워드: **[{info['keyword']}]**")
    
    st.markdown("---")
    st.subheader("2. 수익 링크 입력 (쿠팡 파트너스)")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**'{info['keyword']}'** 검색 후 생성된 링크를 넣어주세요.")
    with col2:
        st.link_button("쿠팡 파트너스 접속 👉", "https://partners.coupang.com/")
    
    profit_link = st.text_input("복사한 링크 붙여넣기 👇", placeholder="https://link.coupang.com/a/.....")
    
    if st.button("블로그 글 최종 완성하기 ✨"):
        with st.spinner("글을 쓰고 이미지를 가져오는 중..."):
            client = init_client()
            
            final_post = generate_blog_post(
                client, info['title'], info['summary'], info['link'], info['keyword'], profit_link
            )
            images = fetch_pexels_images(info['keyword'], count=3)
            
            st.session_state['final_result'] = {
                'post': final_post,
                'images': images,
                'profit_link': profit_link
            }
            st.session_state['step'] = 3

if st.session_state['step'] == 3 and 'final_result' in st.session_state:
    res = st.session_state['final_result']
    
    st.markdown("### 📝 발행용 글 완성!")
    
    if res['images']:
        cols = st.columns(3)
        for i, img in enumerate(res['images']):
            cols[i].image(img, use_container_width=True)
        
    st.markdown(res['post'])
    st.divider()
    
    c1, c2 = st.columns(2)
    if c1.button("텔레그램 전송 ✈️"):
        if send_telegram(res['post']): st.success("전송 완료!")
    if c2.button("이메일 전송 📧"):
        # 받는 사람도 내 이메일(SENDER_EMAIL)로 설정 (테스트용)
        if send_email(SENDER_EMAIL, "블로그 포스팅", res['post'], res['images']): st.success("전송 완료!")
