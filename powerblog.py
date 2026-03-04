import streamlit as st
import requests
import json
import smtplib
import base64
import re
import yfinance as yf
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ==========================================
# 1. 초기 설정 및 시크릿 키
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
def clean_html(text):
    """AI가 출력한 마크다운 HTML 찌꺼기 제거"""
    text = text.strip()
    # 시작 부분의 ```html 또는 ``` 제거
    if text.startswith("```html"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    # 끝 부분의 ``` 제거
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def get_google_auth():
    """구글 블로그 인증 객체 생성"""
    token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds

def post_to_blogger(title, content, image_url=None):
    """구글 블로그에 포스팅 발행"""
    creds = get_google_auth()
    service = build('blogger', 'v3', credentials=creds)
    full_html = ""
    if image_url:
        full_html += f'<div style="text-align: center; margin-bottom: 30px;"><img src="{image_url}" style="max-width: 100%; border-radius: 8px;" /></div>'
    full_html += content
    body = {"title": title, "content": full_html}
    request = service.posts().insert(blogId=BLOG_ID, body=body, isDraft=False)
    return request.execute().get('url')

def send_email(to_email, title, content, image_url=None):
    """결과물을 이메일로 전송 (HTML 포맷)"""
    msg = MIMEMultipart("alternative")
    msg['Subject'] = title
    msg['From'] = EMAIL_USER
    msg['To'] = to_email
    
    html_body = f"<html><body><h2>{title}</h2>"
    if image_url:
        html_body += f'<img src="{image_url}" style="max-width: 600px; border-radius: 8px;" /><br><br>'
    html_body += f"{content}</body></html>"
    
    msg.attach(MIMEText(html_body, 'html'))
    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(EMAIL_USER, EMAIL_PASSWORD)
    server.sendmail(EMAIL_USER, to_email, msg.as_string())
    server.quit()

def search_tavily(query, include_images=True):
    """Tavily API로 최신 기사 및 관련 이미지 검색"""
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "include_images": include_images,
        "max_results": 3
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        data = response.json()
        return data.get('results', []), data.get('images', [])
    return [], []

def get_unsplash_image(query):
    """Unsplash 대체 이미지 검색"""
    url = f"https://api.unsplash.com/search/photos?query={query}&per_page=1"
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}", "Accept-Version": "v1"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200 and response.json().get('results'):
        return response.json()['results'][0]['urls']['regular']
    return None

def encode_image_to_base64(uploaded_file):
    """이미지 파일을 Base64 문자열로 인코딩 (OpenAI Vision 용도)"""
    return base64.b64encode(uploaded_file.read()).decode('utf-8')

def render_action_buttons(title, content, image_url):
    """블로그 발행 및 이메일 전송 공통 버튼 렌더링"""
    st.write("---")
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("#### 🌐 블로그 발행")
        if st.button("🚀 블로그에 포스팅하기", key=f"blog_{title}"):
            with st.spinner("발행 중..."):
                try:
                    url = post_to_blogger(title, content, image_url)
                    st.success(f"포스팅 성공! [확인하기]({url})")
                except Exception as e:
                    st.error(f"오류: {e}")
    with col2:
        st.markdown("#### ✉️ 이메일 전송")
        target_email = st.text_input("받을 이메일 주소", value=EMAIL_USER, key=f"email_input_{title}")
        if st.button("전송하기", key=f"email_btn_{title}"):
            with st.spinner("발송 중..."):
                try:
                    send_email(target_email, title, content, image_url)
                    st.success(f"전송 완료!")
                except Exception as e:
                    st.error(f"오류: {e}")

# ==========================================
# 3. Main UI (웹페이지 상단 탭 방식)
# ==========================================
st.title("🚀 IT대디의 블로그 스튜디오")
st.markdown("원하시는 포스팅 모드를 상단 탭에서 선택하여 글을 작성해 보세요.")

# 4가지 탭 구성
tab1, tab2, tab3, tab4 = st.tabs([
    "💡 AI 트렌드 자동화", 
    "📰 기사 요약 리뷰", 
    "📸 생생 경험담/사용 후기", 
    "📈 주식 시황 브리핑"
])

# ------------------------------------------
# [Tab 1] AI 트렌드 자동화
# ------------------------------------------
with tab1:
    if 'trend_title' not in st.session_state: st.session_state.trend_title = ""
    if 'trend_content' not in st.session_state: st.session_state.trend_content = ""
    if 'trend_image' not in st.session_state: st.session_state.trend_image = ""

    trend_topic = st.text_input("📝 작성할 트렌드 주제를 입력하세요 (예: 2024년 생성형 AI 트렌드)")
    
    if st.button("✨ 트렌드 글 생성", type="primary"):
        if trend_topic:
            with st.spinner("SEO 최적화된 트렌드 글을 작성 중입니다..."):
                st.session_state.trend_title = f"[AI/IT 트렌드] {trend_topic}"
                prompt = f"""
                당신은 IT대디입니다. 주제: '{trend_topic}'
                [조건]
                1. SEO(검색엔진 최적화) 및 GEO(생성형 AI 엔진 최적화)에 적합한 구조와 후킹한 제목을 사용할 것.
                2. 공백 포함 1500자 이상, 검색에 잘 걸리는 핵심 키워드 반복 배치.
                3. 순수 HTML 태그(<h2>, <p> 등)만 사용하고, 마크다운(```html)은 절대 쓰지 말 것.
                """
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                st.session_state.trend_content = clean_html(res.choices[0].message.content)
                
                # Tavily 이미지 검색 우선 적용 (없으면 Unsplash)
                _, images = search_tavily(trend_topic, include_images=True)
                st.session_state.trend_image = images[0] if images else get_unsplash_image("technology trend")
            st.success("트렌드 포스팅 작성 완료!")

    if st.session_state.trend_content:
        with st.expander("👀 미리보기 (클릭하여 펼치기)", expanded=True):
            st.subheader(st.session_state.trend_title)
            if st.session_state.trend_image: st.image(st.session_state.trend_image, use_container_width=True)
            st.components.v1.html(st.session_state.trend_content, height=400, scrolling=True)
        render_action_buttons(st.session_state.trend_title, st.session_state.trend_content, st.session_state.trend_image)

# ------------------------------------------
# [Tab 2] 기사 요약 리뷰
# ------------------------------------------
with tab2:
    if 'news_results' not in st.session_state: st.session_state.news_results = []
    if 'news_title' not in st.session_state: st.session_state.news_title = ""
    if 'news_content' not in st.session_state: st.session_state.news_content = ""
    if 'news_image' not in st.session_state: st.session_state.news_image = ""

    search_query = st.text_input("🔍 검색할 뉴스 키워드 (예: 애플 비전프로 출시)")
    if st.button("기사 검색"):
        if search_query:
            with st.spinner("최신 기사 수집 중..."):
                results, images = search_tavily(f"{search_query} 최신 뉴스", include_images=True)
                st.session_state.news_results = results
                st.session_state.news_image = images[0] if images else get_unsplash_image(search_query + " news")

    if st.session_state.news_results:
        st.markdown("**👇 블로그 글로 작성할 기사를 선택하세요:**")
        opts = [f"{idx+1}. {a['title']}" for idx, a in enumerate(st.session_state.news_results)]
        sel_idx = st.radio("기사 선택:", range(len(opts)), format_func=lambda x: opts[x])
        sel_article = st.session_state.news_results[sel_idx]

        if st.button("✨ 요약 리뷰 생성", type="primary"):
            with st.spinner("독자가 이해하기 쉽게 리뷰 작성 중..."):
                st.session_state.news_title = f"[IT 뉴스 요약] {sel_article['title']}"
                prompt = f"""
                당신은 친절한 IT 전문가입니다. 뉴스: {sel_article['title']} / 내용: {sel_article['content']}
                [조건]
                1. 초보자도 이해하기 쉽도록 친근한 말투와 이모지(💡, 📊, 🔥 등)를 적재적소에 활용할 것.
                2. 공백 1500자 이상, HTML 태그만 사용. 마크다운(```html) 금지.
                3. 마지막에 원본 출처({sel_article['url']})를 명시.
                """
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                st.session_state.news_content = clean_html(res.choices[0].message.content)
            st.success("뉴스 요약 작성 완료!")

    if st.session_state.news_content:
        with st.expander("👀 미리보기 (클릭하여 펼치기)", expanded=True):
            st.subheader(st.session_state.news_title)
            if st.session_state.news_image: st.image(st.session_state.news_image, use_container_width=True)
            st.components.v1.html(st.session_state.news_content, height=400, scrolling=True)
        render_action_buttons(st.session_state.news_title, st.session_state.news_content, st.session_state.news_image)

# ------------------------------------------
# [Tab 3] 생생 경험담/사용 후기
# ------------------------------------------
with tab3:
    if 'review_title' not in st.session_state: st.session_state.review_title = ""
    if 'review_content' not in st.session_state: st.session_state.review_content = ""
    
    review_topic = st.text_input("📍 방문한 장소나 제품명 (예: 성수동 핫플 카페 오픈런 후기)")
    uploaded_files = st.file_uploader("사진을 여러 장 업로드하세요", type=["png", "jpg", "jpeg"], accept_multiple_files=True)

    if uploaded_files:
        st.info(f"📸 총 {len(uploaded_files)}장의 사진이 첨부되었습니다.")

    if st.button("✨ 생생 후기 작성", type="primary"):
        if review_topic:
            with st.spinner("사진을 분석하여 인싸 감성의 블로그 글을 작성 중입니다..."):
                st.session_state.review_title = f"[방문 후기] {review_topic}"
                
                # 사용자가 제공한 인싸 블로거 프롬프트 적용
                system_prompt = f"""
                당신은 트렌디하고 감각적인 라이프스타일 유명 블로거입니다. 
                주제: {review_topic}
                
                [역할 및 톤앤매너]
                - 친근하고 활기 넘치는 '인싸' 블로거. 구어체("~했어요", "~거든요"), 최신 유행어(오픈런, 존맛탱 등) 사용.
                - 이모지(✨, 😍, 📸 등)를 풍부하게 사용.
                
                [이미지 분석 및 처리 가이드]
                - 업로드된 이미지 순서에 맞춰서 글 내용 중간중간 알맞은 위치에 <img src="IMAGE_PLACEHOLDER_X" style="max-width:100%; border-radius:8px;"> 를 삽입하세요. (X는 1부터 시작하는 사진 번호)
                - 서론, 본론(사진 속 분위기, 음식 등을 생생하게 묘사), 정보 요약 섹션(구글/네이버 지도 참고 정보란), 해시태그로 구성.
                - 거짓 정보 금지. 알 수 없는 정보는 '여기에 입력하세요' 등으로 표시.
                - 마크다운(```html)은 절대 쓰지 말고 순수 HTML 태그만 출력.
                """

                messages_payload = [{"role": "system", "content": system_prompt}]
                user_content = [{"type": "text", "text": "제가 찍은 사진들을 바탕으로 매력적인 포스팅을 작성해주세요!"}]
                
                base64_images = []
                for idx, file in enumerate(uploaded_files):
                    b64 = encode_image_to_base64(file)
                    base64_images.append(b64)
                    user_content.append({
                        "type": "image_url", 
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                    })
                
                messages_payload.append({"role": "user", "content": user_content})
                
                res = client.chat.completions.create(model="gpt-4o-mini", messages=messages_payload)
                raw_html = clean_html(res.choices[0].message.content)
                
                # 텍스트 내의 IMAGE_PLACEHOLDER_X를 실제 Base64 이미지 데이터로 치환
                for idx, b64 in enumerate(base64_images):
                    placeholder = f"IMAGE_PLACEHOLDER_{idx+1}"
                    actual_img_src = f"data:image/jpeg;base64,{b64}"
                    raw_html = raw_html.replace(placeholder, actual_img_src)
                    
                st.session_state.review_content = raw_html
            st.success("경험담 작성 완료!")

    if st.session_state.review_content:
        st.warning("💡 여러 장의 고화질 이미지는 구글 블로그 정책상 용량 에러를 일으킬 수 있습니다. 에러 발생 시 [이메일 전송] 후 블로그 에디터에 복사 붙여넣기 하세요.")
        with st.expander("👀 미리보기 (클릭하여 펼치기)", expanded=True):
            st.components.v1.html(st.session_state.review_content, height=600, scrolling=True)
        # 본문 안에 이미지가 렌더링되므로 상단 대표 이미지는 넘기지 않음
        render_action_buttons(st.session_state.review_title, st.session_state.review_content, None)

# ------------------------------------------
# [Tab 4] 주식 시황 브리핑
# ------------------------------------------
with tab4:
    if 'stock_title' not in st.session_state: st.session_state.stock_title = ""
    if 'stock_content' not in st.session_state: st.session_state.stock_content = ""
    if 'stock_image' not in st.session_state: st.session_state.stock_image = ""
    
    tickers_input = st.text_input("🔍 분석할 종목 티커 쉼표로 입력 (예: AAPL, TSLA, 005930.KS)")
    
    if st.button("✨ 주식 브리핑 생성", type="primary"):
        if tickers_input:
            with st.spinner("주가 데이터를 분석하고 시황 리포트를 작성 중입니다..."):
                st.session_state.stock_title = "[증시 브리핑] 주요 종목 주가 동향 및 분석"
                
                # yfinance를 이용한 가격 변동률 계산
                tickers = [t.strip() for t in tickers_input.split(',') if t.strip()]
                stock_data = []
                for t in tickers:
                    try:
                        hist = yf.Ticker(t).history(period="2d")
                        if len(hist) >= 2:
                            prev_close = hist['Close'].iloc[0]
                            curr_close = hist['Close'].iloc[-1]
                            chg = ((curr_close - prev_close) / prev_close) * 100
                            stock_data.append(f"{t}: 변동률 {chg:+.2f}%")
                    except:
                        pass
                
                prompt = f"""
                당신은 경제/IT 전문 블로거입니다. 오늘 수집된 주요 주식 데이터: {', '.join(stock_data)}
                
                [조건]
                1. 주가가 올랐다면 호재를, 떨어졌다면 악재나 조정의 이유를 최신 동향과 엮어 분석할 것.
                2. 공백 1500자 이상, 순수 HTML 태그(<h2>, <ul> 등)만 사용. 마크다운(```html) 금지.
                3. 마지막에는 "본 글은 투자 권유가 아니며, 투자의 책임은 본인에게 있습니다"라는 문구를 굵은 글씨로 넣을 것.
                """
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                st.session_state.stock_content = clean_html(res.choices[0].message.content)
                
                # Tavily 이미지 검색
                _, images = search_tavily("stock market trading analysis", include_images=True)
                st.session_state.stock_image = images[0] if images else get_unsplash_image("stock market graph")
            st.success("주식 시황 브리핑 작성 완료!")

    if st.session_state.stock_content:
        with st.expander("👀 미리보기 (클릭하여 펼치기)", expanded=True):
            if st.session_state.stock_image: st.image(st.session_state.stock_image, use_container_width=True)
            st.components.v1.html(st.session_state.stock_content, height=500, scrolling=True)
        render_action_buttons(st.session_state.stock_title, st.session_state.stock_content, st.session_state.stock_image)
