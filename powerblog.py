import streamlit as st
import requests
import json
import smtplib
import base64
import yfinance as yf
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ==========================================
# 1. 초기 설정 및 시크릿 키 불러오기
# ==========================================
st.set_page_config(page_title="IT대디의 블로그 스튜디오", page_icon="🚀", layout="wide")

try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    UNSPLASH_ACCESS_KEY = st.secrets["UNSPLASH_ACCESS_KEY"]
    BLOG_ID = st.secrets["BLOG_ID"]
    GOOGLE_OAUTH_TOKEN_STR = st.secrets["GOOGLE_OAUTH_TOKEN"]
    EMAIL_USER = st.secrets["EMAIL_USER"]
    EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
    TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY", "") 
except KeyError as e:
    st.error(f"시크릿 키 설정이 누락되었습니다: {e}")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/blogger']

# ==========================================
# 2. 공통 기능 함수
# ==========================================
def get_google_auth():
    token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds

def get_unsplash_image(query):
    url = f"https://api.unsplash.com/search/photos?query={query}&per_page=1"
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}", "Accept-Version": "v1"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200 and response.json().get('results'):
        return response.json()['results'][0]['urls']['regular']
    return None

def post_to_blogger(title, content, image_url):
    creds = get_google_auth()
    service = build('blogger', 'v3', credentials=creds)
    full_html = ""
    if image_url:
        full_html += f'<div style="text-align: center; margin-bottom: 30px;"><img src="{image_url}" style="max-width: 100%; border-radius: 8px;" /></div>'
    full_html += content
    body = {"title": title, "content": full_html}
    request = service.posts().insert(blogId=BLOG_ID, body=body, isDraft=False)
    return request.execute().get('url')

def search_news_tavily(query):
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": f"{query} 최신 뉴스 기사",
        "search_depth": "advanced",
        "include_images": False,
        "max_results": 3
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return response.json().get('results', [])
    return []

def encode_image_to_base64(uploaded_file):
    return base64.b64encode(uploaded_file.read()).decode('utf-8')

def get_stock_data(tickers_str):
    """yfinance를 이용해 여러 종목의 현재가 및 등락폭 수집"""
    tickers = [t.strip() for t in tickers_str.split(',') if t.strip()]
    results = []
    
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2d")
            if len(hist) >= 2:
                prev_close = hist['Close'].iloc[0]
                current = hist['Close'].iloc[-1]
                change_pct = ((current - prev_close) / prev_close) * 100
                
                status = "상승 📈" if change_pct > 0 else "하락 📉" if change_pct < 0 else "보합 ➖"
                results.append(f"- **{ticker}**: 현재가 {current:,.2f} / 변동: {change_pct:+.2f}% ({status})")
            else:
                results.append(f"- **{ticker}**: 최근 데이터 부족")
        except Exception as e:
            results.append(f"- **{ticker}**: 데이터 조회 실패")
    
    return "\n".join(results)

# ==========================================
# 3. Streamlit 사이드바 메뉴 구성
# ==========================================
st.sidebar.title("🛠️ 포스팅 모드 선택")
menu = st.sidebar.radio(
    "어떤 글을 작성할까요?",
    ("💡 AI 트렌드 자동화", "📰 최신 기사 요약 리뷰", "📸 생생 경험담/사용 후기", "📈 주식 시황 브리핑")
)
st.sidebar.divider()
st.sidebar.info("💡 각 메뉴별로 작성된 글은 독립적으로 관리됩니다.")

# ==========================================
# [모드 1, 2, 3] 기존 기능 유지 (생략 없이 포함됨)
# ==========================================

if menu == "💡 AI 트렌드 자동화":
    st.title("💡 AI/IT 트렌드 블로그 포스팅")
    # ... (이전과 동일한 모드 1 코드) ...
    if 'trend_topics' not in st.session_state: st.session_state.trend_topics = []
    if 'trend_title' not in st.session_state: st.session_state.trend_title = ""
    if 'trend_content' not in st.session_state: st.session_state.trend_content = ""
    if 'trend_image' not in st.session_state: st.session_state.trend_image = ""

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 AI 트렌드 추천받기"):
            with st.spinner("트렌드 분석 중..."):
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "IT 최신 트렌드 주제 3가지를 '1. 제목' 형태로 간결하게 줄바꿈해서 줘."}]
                )
                topics = [line.strip() for line in response.choices[0].message.content.split('\n') if line.strip() and line[0].isdigit()]
                st.session_state.trend_topics = topics[:3]

    selected_topic = ""
    if st.session_state.trend_topics:
        selected_topic = st.radio("👇 주제 선택:", st.session_state.trend_topics)

    manual_topic = st.text_input("📝 직접 입력 (입력 시 우선 적용)")
    final_topic = manual_topic if manual_topic.strip() else selected_topic

    if st.button("✨ 선택한 주제로 글 생성", type="primary"):
        if final_topic:
            with st.spinner("글 작성 중..."):
                st.session_state.trend_title = f"[AI/IT 트렌드] {final_topic.replace('1. ', '').replace('2. ', '').replace('3. ', '')}"
                prompt = f"당신은 IT대디입니다. 주제: {final_topic}. 분량 1500자 이상, 애드센스 승인용 전문적인 IT 블로그 글을 순수 HTML 태그(<h2>, <p> 등)로 작성해."
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                st.session_state.trend_content = res.choices[0].message.content
                st.session_state.trend_image = get_unsplash_image("technology artificial intelligence")
            st.success("작성 완료!")

    if st.session_state.trend_content:
        with st.expander("👀 미리보기", expanded=True):
            st.subheader(st.session_state.trend_title)
            if st.session_state.trend_image: st.image(st.session_state.trend_image, use_container_width=True)
            st.components.v1.html(st.session_state.trend_content, height=400, scrolling=True)
        if st.button("🚀 블로그에 발행하기 (트렌드)"):
            url = post_to_blogger(st.session_state.trend_title, st.session_state.trend_content, st.session_state.trend_image)
            st.success(f"포스팅 성공! [확인하기]({url})")

elif menu == "📰 최신 기사 요약 리뷰":
    st.title("📰 최신 기사 검색 및 요약 포스팅")
    if 'news_results' not in st.session_state: st.session_state.news_results = []
    if 'news_content' not in st.session_state: st.session_state.news_content = ""
    
    search_query = st.text_input("🔍 검색할 키워드를 입력하세요 (예: 오픈AI 소라, 테슬라 자율주행)")
    if st.button("기사 검색하기"):
        with st.spinner("최신 기사를 수집 중입니다..."):
            st.session_state.news_results = search_news_tavily(search_query)

    if st.session_state.news_results:
        article_options = [f"{idx+1}. {article['title']}" for idx, article in enumerate(st.session_state.news_results)]
        selected_article_idx = st.radio("글을 작성할 기반 기사를 선택하세요:", range(len(article_options)), format_func=lambda x: article_options[x])
        selected_article = st.session_state.news_results[selected_article_idx]

        if st.button("✨ 이 기사로 블로그 글 생성", type="primary"):
            with st.spinner("기사를 분석하고 통찰력 있는 글을 작성 중입니다..."):
                st.session_state.news_title = f"[IT 뉴스 인사이트] {selected_article['title']}"
                news_prompt = f"당신은 IT대디입니다. 다음 뉴스 내용을 바탕으로 독자들에게 트렌드를 짚어주는 정보성 블로그 글을 작성하세요.\n제목: {selected_article['title']}\n내용: {selected_article['content']}\n조건: 공백 포함 1500자 이상, HTML 태그만 사용, 출처 링크({selected_article['url']}) 포함."
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": news_prompt}])
                st.session_state.news_content = res.choices[0].message.content
                st.session_state.news_image = get_unsplash_image(search_query + " news technology")
            st.success("작성 완료!")

    if st.session_state.news_content:
        with st.expander("👀 미리보기", expanded=True):
            st.components.v1.html(st.session_state.news_content, height=400, scrolling=True)
        if st.button("🚀 블로그에 발행하기 (뉴스)"):
            url = post_to_blogger(st.session_state.news_title, st.session_state.news_content, st.session_state.news_image)
            st.success(f"포스팅 성공! [확인하기]({url})")

elif menu == "📸 생생 경험담/사용 후기":
    st.title("📸 내돈내산 경험담 / 제품 리뷰 포스팅")
    if 'review_content' not in st.session_state: st.session_state.review_content = ""
    
    review_topic = st.text_input("📍 리뷰할 장소나 제품명을 입력하세요")
    uploaded_file = st.file_uploader("사진을 업로드하세요 (선택)", type=["png", "jpg", "jpeg"])

    if st.button("✨ 생생 후기 글 생성하기", type="primary"):
        if review_topic:
            with st.spinner("후기를 작성 중입니다..."):
                st.session_state.review_title = f"[직접 경험한 후기] {review_topic}"
                system_prompt = f"당신은 IT대디입니다. 주제: '{review_topic}'에 대한 솔직하고 생생한 후기를 작성해주세요. HTML 태그만 사용, 1500자 이상."
                
                if uploaded_file:
                    base64_image = encode_image_to_base64(uploaded_file)
                    messages_payload = [{"role": "user", "content": [{"type": "text", "text": system_prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}]
                else:
                    messages_payload = [{"role": "user", "content": system_prompt}]
                
                res = client.chat.completions.create(model="gpt-4o-mini", messages=messages_payload)
                st.session_state.review_content = res.choices[0].message.content
                st.session_state.review_uploaded_image = get_unsplash_image(review_topic) if not uploaded_file else ""
            st.success("작성 완료!")

    if st.session_state.review_content:
        with st.expander("👀 미리보기", expanded=True):
            st.components.v1.html(st.session_state.review_content, height=400, scrolling=True)
        if st.button("🚀 블로그에 발행하기 (리뷰)"):
            url = post_to_blogger(st.session_state.review_title, st.session_state.review_content, st.session_state.review_uploaded_image)
            st.success(f"포스팅 성공! [확인하기]({url})")

# ==========================================
# [모드 4] 주식 시황 브리핑 (신규 기능)
# ==========================================
elif menu == "📈 주식 시황 브리핑":
    st.title("📈 AI 주식 시황 및 종목 분석")
    st.markdown("관심 있는 주식 티커(기호)를 입력하면 실시간 등락폭을 확인하고, AI가 시황을 분석해 줍니다.")

    if 'stock_content' not in st.session_state: st.session_state.stock_content = ""
    if 'stock_title' not in st.session_state: st.session_state.stock_title = ""
    if 'stock_image' not in st.session_state: st.session_state.stock_image = ""

    # 한국 주식은 '.KS'(코스피)나 '.KQ'(코스닥)를 붙이고, 미국 주식은 티커 그대로 입력합니다.
    tickers_input = st.text_input(
        "🔍 분석할 종목 티커를 쉼표(,)로 구분해 입력하세요", 
        value="AAPL, TSLA, 066570.KS", 
        help="미국주식 예: AAPL(애플), NVDA(엔비디아) / 한국주식 예: 005930.KS(삼성전자), 066570.KS(LG전자)"
    )

    if st.button("✨ 실시간 시황 분석 글 생성", type="primary"):
        if tickers_input:
            with st.spinner("실시간 주가 데이터를 수집하고 분석 리포트를 작성 중입니다..."):
                # 1. yfinance로 주식 데이터 가져오기
                stock_data_text = get_stock_data(tickers_input)
                
                st.session_state.stock_title = "[증시 브리핑] 주요 관심 종목 주가 동향 및 AI 분석"
                
                # 2. GPT에게 주식 데이터를 주고 분석 글 요청
                stock_prompt = f"""
                당신은 경제와 IT에 해박한 지식을 가진 'IT대디' 블로거입니다. 
                아래는 오늘 수집된 주요 주식 종목의 실시간 가격 및 변동률 데이터입니다.

                [오늘의 주식 데이터]
                {stock_data_text}
                
                이 데이터를 바탕으로 독자들에게 현재 시장 상황과 각 종목이 왜 오르고 내렸는지(최신 IT 업계 동향과 엮어서)를 분석해주는 블로그 포스팅을 작성해 주세요.
                
                [조건]
                1. 주가가 올랐다면 호재를, 떨어졌다면 악재나 조정의 이유를 논리적으로 추론하여 설명할 것.
                2. 공백 포함 1,500자 이상, 순수 HTML 태그(<h2>, <h3>, <p>, <ul> 등)만 사용할 것.
                3. 글의 마지막에는 "본 글은 투자 권유가 아니며, 투자의 책임은 본인에게 있습니다"라는 문구를 굵은 글씨로 넣을 것.
                """
                
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": stock_prompt}])
                st.session_state.stock_content = res.choices[0].message.content
                st.session_state.stock_image = get_unsplash_image("stock market graph trading")
                
            st.success("주식 시황 브리핑 작성 완료!")

    if st.session_state.stock_content:
        st.info("💡 실시간 주가 데이터가 성공적으로 반영되었습니다.")
        with st.expander("👀 주식 포스팅 미리보기", expanded=True):
            st.subheader(st.session_state.stock_title)
            if st.session_state.stock_image: st.image(st.session_state.stock_image, use_container_width=True)
            st.components.v1.html(st.session_state.stock_content, height=500, scrolling=True)
            
        if st.button("🚀 블로그에 발행하기 (주식)"):
            with st.spinner("발행 중..."):
                url = post_to_blogger(st.session_state.stock_title, st.session_state.stock_content, st.session_state.stock_image)
                st.success(f"포스팅 성공! [확인하기]({url})")
