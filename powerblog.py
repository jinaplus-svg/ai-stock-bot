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
    if text.startswith("```html"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
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
    url = "[https://api.tavily.com/search](https://api.tavily.com/search)"
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
    url = f"[https://api.unsplash.com/search/photos?query=](https://api.unsplash.com/search/photos?query=){query}&per_page=1"
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
    if 'recommended_trends' not in st.session_state: st.session_state.recommended_trends = []

    st.markdown("#### 1. 포스팅 주제 선택")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 최신 AI/IT 트렌드 추천받기"):
            with st.spinner("AI가 최신 트렌드를 분석 중입니다..."):
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "현재 가장 주목받는 최신 AI 및 IT 트렌드 주제 3가지를 추천해줘. 1., 2., 3. 번호를 붙여서 제목만 간결하게 줄바꿈해서 출력해."}]
                )
                topics = [line.strip() for line in res.choices[0].message.content.split('\n') if line.strip() and line[0].isdigit()]
                st.session_state.recommended_trends = topics[:3]

    selected_trend = ""
    if st.session_state.recommended_trends:
        selected_trend = st.radio("👇 AI 추천 주제 중 하나를 선택하세요:", st.session_state.recommended_trends)

    manual_trend = st.text_input("📝 직접 입력 (입력 시 추천 주제보다 우선 적용됩니다)", placeholder="예: 2024년 생성형 AI 트렌드")
    final_trend_topic = manual_trend if manual_trend.strip() else selected_trend

    if st.button("✨ 트렌드 글 생성", type="primary"):
        if final_trend_topic:
            cleaned_topic = re.sub(r'^\d+\.\s*', '', final_trend_topic)
            with st.spinner(f"'{cleaned_topic}' 주제로 SEO 최적화된 글을 작성 중입니다..."):
                st.session_state.trend_title = f"[AI/IT 트렌드] {cleaned_topic}"
                prompt = f"""
                당신은 IT대디입니다. 주제: '{cleaned_topic}'
                [조건]
                1. SEO(검색엔진 최적화) 및 GEO(생성형 AI 엔진 최적화)에 적합한 구조와 후킹한 제목을 사용할 것.
                2. 공백 포함 1500자 이상, 검색에 잘 걸리는 핵심 키워드 반복 배치.
                3. 순수 HTML 태그(<h2>, <p> 등)만 사용하고, 마크다운(```html)은 절대 쓰지 말 것.
                """
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                st.session_state.trend_content = clean_html(res.choices[0].message.content)
                
                _, images = search_tavily(cleaned_topic, include_images=True)
                st.session_state.trend_image = images[0] if images else get_unsplash_image(cleaned_topic + " technology")
            st.success("트렌드 포스팅 작성 완료!")
        else:
            st.warning("주제를 선택하거나 직접 입력해주세요!")

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
    if 'recommended_news_keywords' not in st.session_state: st.session_state.recommended_news_keywords = []

    st.markdown("#### 1. 뉴스 검색 키워드 선택")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 지금 뜨는 IT 뉴스 키워드 추천받기"):
            with st.spinner("최신 뉴스 키워드를 분석 중입니다..."):
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "현재 IT/테크 분야에서 가장 핫한 뉴스 검색 키워드 3가지를 추천해줘. 1., 2., 3. 번호를 붙여서 명사형 키워드만 간결하게 줄바꿈해서 출력해."}]
                )
                keywords = [line.strip() for line in res.choices[0].message.content.split('\n') if line.strip() and line[0].isdigit()]
                st.session_state.recommended_news_keywords = keywords[:3]

    selected_keyword = ""
    if st.session_state.recommended_news_keywords:
        selected_keyword = st.radio("👇 AI 추천 검색어 중 하나를 선택하세요:", st.session_state.recommended_news_keywords)

    manual_query = st.text_input("🔍 직접 검색할 뉴스 키워드 입력 (입력 시 우선 적용)", placeholder="예: 애플 비전프로 출시")
    final_search_query = manual_query if manual_query.strip() else selected_keyword

    if st.button("기사 검색"):
        if final_search_query:
            cleaned_query = re.sub(r'^\d+\.\s*', '', final_search_query)
            with st.spinner(f"'{cleaned_query}' 관련 최신 기사를 수집 중입니다..."):
                results, images = search_tavily(f"{cleaned_query} 최신 뉴스", include_images=True)
                st.session_state.news_results = results
                st.session_state.news_image = images[0] if images else get_unsplash_image(cleaned_query + " news")
        else:
            st.warning("검색할 키워드를 선택하거나 직접 입력해주세요!")

    if st.session_state.news_results:
        st.markdown("---")
        st.markdown("#### 2. 블로그 글로 작성할 기반 기사 선택")
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
    if 'recommended_places' not in st.session_state: st.session_state.recommended_places = []

    st.markdown("#### 1. 리뷰할 핫플/핫템 선택")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🔄 요즘 뜨는 핫플/핫템 추천받기"):
            with st.spinner("AI가 최신 유행을 검색 중입니다..."):
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": "요즘 2030 사이에서 인스타그램이나 틱톡 등에서 가장 유행하는 핫플(장소)이나 핫템(제품) 3가지를 추천해줘. 1., 2., 3. 번호를 붙여서 이름만 간결하게 출력해."}]
                )
                places = [line.strip() for line in res.choices[0].message.content.split('\n') if line.strip() and line[0].isdigit()]
                st.session_state.recommended_places = places[:3]

    selected_place = ""
    if st.session_state.recommended_places:
        selected_place = st.radio("👇 AI 추천 핫플/템 중 하나를 선택하세요:", st.session_state.recommended_places)

    manual_place = st.text_input("📝 직접 입력 (입력 시 추천보다 우선 적용)", placeholder="예: 성수동 팝업스토어 오픈런 후기")
    final_review_topic = manual_place if manual_place.strip() else selected_place

    st.markdown("#### 2. 사진 첨부 (선택)")
    uploaded_files = st.file_uploader("사진을 여러 장 업로드하세요", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
    if uploaded_files:
        st.info(f"📸 총 {len(uploaded_files)}장의 사진이 첨부되었습니다.")

    if st.button("✨ 생생 후기 작성", type="primary"):
        if final_review_topic:
            cleaned_topic = re.sub(r'^\d+\.\s*', '', final_review_topic)
            with st.spinner("사진을 분석하여 인싸 감성의 블로그 글을 작성 중입니다..."):
                st.session_state.review_title = f"[방문/사용 후기] {cleaned_topic}"
                
                system_prompt = f"""
                당신은 트렌디하고 감각적인 라이프스타일 유명 블로거입니다. 
                주제: {cleaned_topic}
                
                [역할 및 톤앤매너]
                - 친근하고 활기 넘치는 '인싸' 블로거. 구어체("~했어요", "~거든요"), 최신 유행어(오픈런, 존맛탱 등) 사용.
                - 이모지(✨, 😍, 📸 등)를 풍부하게 사용.
                
                [이미지 처리 가이드 및 띄어쓰기/줄바꿈 규칙 (매우 중요)]
                1. 업로드된 이미지 순서에 맞춰서 글 내용 중간중간 알맞은 위치에 <img src="IMAGE_PLACEHOLDER_X" style="max-width:100%; border-radius:8px;"> 를 삽입하세요. (X는 1부터 시작하는 번호)
                2. 문장이 하나 끝날 때마다 반드시 HTML 태그 <br><br>를 넣어 문단 간격을 넓히고 읽기 편하게 띄어쓰기를 하세요.
                3. <img src="..."> 태그를 삽입한 직후에도 반드시 <br><br>를 넣어 사진과 그 다음 글씨가 딱 붙지 않고 여유롭게 띄어지게 하세요.
                4. 순수 HTML 태그(<h2>, <p> 등)만 출력하고 마크다운(```html)은 쓰지 마세요.
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
                
                # 플레이스홀더를 실제 이미지로 치환
                for idx, b64 in enumerate(base64_images):
                    placeholder = f"IMAGE_PLACEHOLDER_{idx+1}"
                    actual_img_src = f"data:image/jpeg;base64,{b64}"
                    raw_html = raw_html.replace(placeholder, actual_img_src)
                    
                st.session_state.review_content = raw_html
            st.success("경험담 작성 완료!")
        else:
            st.warning("주제를 선택하거나 입력해주세요!")

    if st.session_state.review_content:
        st.warning("💡 여러 장의 고화질 이미지는 구글 블로그 정책상 용량 에러를 일으킬 수 있습니다. 에러 발생 시 [이메일 전송] 후 블로그 에디터에 복사/붙여넣기 하세요.")
        with st.expander("👀 미리보기 (클릭하여 펼치기)", expanded=True):
            st.components.v1.html(st.session_state.review_content, height=600, scrolling=True)
        render_action_buttons(st.session_state.review_title, st.session_state.review_content, None)

# ------------------------------------------
# [Tab 4] 주식 시황 브리핑
# ------------------------------------------
with tab4:
    if 'stock_title' not in st.session_state: st.session_state.stock_title = ""
    if 'stock_content' not in st.session_state: st.session_state.stock_content = ""
    if 'stock_image' not in st.session_state: st.session_state.stock_image = ""

    # 한미 Top 20 딕셔너리
    US_TOP_20 = {"AAPL":"애플", "MSFT":"마이크로소프트", "NVDA":"엔비디아", "GOOGL":"알파벳", "AMZN":"아마존", "META":"메타", "TSLA":"테슬라", "BRK-B":"버크셔 해서웨이", "LLY":"일라이 릴리", "AVGO":"브로드컴", "JPM":"JP모건", "V":"비자", "UNH":"유나이티드헬스", "XOM":"엑슨모빌", "MA":"마스터카드", "JNJ":"존슨앤존슨", "PG":"P&G", "HD":"홈디포", "MRK":"머크", "COST":"코스트코"}
    KR_TOP_20 = {"005930.KS":"삼성전자", "000660.KS":"SK하이닉스", "373220.KS":"LG에너지솔루션", "207940.KS":"삼성바이오로직스", "005380.KS":"현대차", "000270.KS":"기아", "068270.KS":"셀트리온", "005490.KS":"POSCO홀딩스", "105560.KS":"KB금융", "035420.KS":"NAVER", "028260.KS":"삼성물산", "055550.KS":"신한지주", "032830.KS":"삼성생명", "012330.KS":"현대모비스", "066570.KS":"LG전자", "035720.KS":"카카오", "051910.KS":"LG화학", "096770.KS":"SK이노베이션", "033780.KS":"KT&G", "011200.KS":"HMM"}
    
    st.markdown("#### 1. 한/미 주식 시총 Top 20 정보")
    with st.expander("📊 한/미 시가총액 Top 20 리스트 보기 (클릭하여 펼치기)", expanded=False):
        col_us, col_kr = st.columns(2)
        with col_us:
            st.markdown("**🇺🇸 미국장 Top 20**")
            for k, v in US_TOP_20.items(): st.write(f"- {v} ({k})")
        with col_kr:
            st.markdown("**🇰🇷 한국장 Top 20**")
            for k, v in KR_TOP_20.items(): st.write(f"- {v} ({k})")

    st.markdown("#### 2. 분석할 종목 선택")
    all_opts = [f"{v} ({k})" for k, v in {**US_TOP_20, **KR_TOP_20}.items()]
    sel_stocks = st.multiselect("👇 Top 20 리스트에서 분석할 종목을 선택하세요 (여러 개 가능):", all_opts)
    
    manual_tickers = st.text_input("📝 직접 입력 (티커명만 쉼표로 구분. 예: TSLA, 005930.KS)", placeholder="원하는 티커를 직접 입력하세요")
    
    if st.button("✨ 주식 브리핑 생성 (1년 트렌드 + 뉴스 예측 분석)", type="primary"):
        # 선택된 종목 + 직접 입력 병합
        final_tickers = []
        for s in sel_stocks:
            match = re.search(r'\((.*?)\)', s)
            if match: final_tickers.append(match.group(1))
        if manual_tickers.strip():
            final_tickers.extend([t.strip() for t in manual_tickers.split(',') if t.strip()])
            
        if final_tickers:
            with st.spinner("최근 1년 주가 데이터와 최신 기사를 수집하여 분석 리포트를 작성 중입니다... (시간이 조금 소요될 수 있습니다)"):
                st.session_state.stock_title = "[증시 브리핑] 주요 종목 1년 트렌드 및 향후 예측"
                
                stock_data_text = ""
                news_text = ""
                
                # yfinance로 1년 데이터 및 Tavily 뉴스 검색
                for t in final_tickers:
                    try:
                        hist = yf.Ticker(t).history(period="1y")
                        if len(hist) > 0:
                            curr_close = hist['Close'].iloc[-1]
                            one_yr_ago = hist['Close'].iloc[0]
                            high_1y = hist['High'].max()
                            low_1y = hist['Low'].min()
                            chg_1y = ((curr_close - one_yr_ago) / one_yr_ago) * 100
                            
                            chg_1d = 0
                            if len(hist) >= 2:
                                chg_1d = ((curr_close - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]) * 100
                                
                            stock_data_text += f"[{t}]\n- 현재가: {curr_close:.2f}\n- 전일 대비: {chg_1d:+.2f}%\n- 1년 전 대비: {chg_1y:+.2f}%\n- 1년 최고/최저가: {high_1y:.2f} / {low_1y:.2f}\n\n"
                        
                        # 종목별 뉴스 검색
                        news_results, _ = search_tavily(f"{t} 주식 전망 실적 최신 기사", include_images=False)
                        if news_results:
                            news_text += f"[{t} 관련 뉴스]\n"
                            for n in news_results:
                                news_text += f"- {n['title']}: {n['content'][:100]}...\n"
                            news_text += "\n"
                    except Exception as e:
                        pass
                
                prompt = f"""
                당신은 경제/IT 전문 블로거입니다. 
                선택된 종목: {', '.join(final_tickers)}
                
                [수집된 주가 데이터 (1년 트렌드 포함)]
                {stock_data_text}
                
                [관련 최신 뉴스 요약]
                {news_text}
                
                [작성 조건]
                1. 1년 간의 장기 트렌드(최고/최저, 1년 수익률)와 최신 뉴스를 바탕으로 상세한 시황 분석을 할 것.
                2. 향후 주가가 상승할지 하락할지 '예측 의견'을 뉴스 기사 근거를 들어 명확하게 제시할 것.
                3. 공백 1500자 이상, 순수 HTML 태그(<h2>, <ul>, <p> 등)만 사용할 것. 마크다운(```html) 금지.
                4. 문단이나 내용이 바뀔 때마다 <br><br> 태그를 넣어 읽기 편하게 충분히 띄어쓰기를 할 것.
                5. 마지막에는 "본 글은 투자 권유가 아니며, 투자의 책임은 본인에게 있습니다"라는 문구를 굵은 글씨로 넣을 것.
                """
                res = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                st.session_state.stock_content = clean_html(res.choices[0].message.content)
                
                # 공통 대표 이미지 검색
                _, images = search_tavily("stock market trading analysis trends", include_images=True)
                st.session_state.stock_image = images[0] if images else get_unsplash_image("stock market graph")
            st.success("주식 시황 브리핑 작성 완료!")
        else:
            st.warning("분석할 종목을 선택하거나 입력해주세요!")

    if st.session_state.stock_content:
        with st.expander("👀 미리보기 (클릭하여 펼치기)", expanded=True):
            if st.session_state.stock_image: st.image(st.session_state.stock_image, use_container_width=True)
            st.components.v1.html(st.session_state.stock_content, height=500, scrolling=True)
        render_action_buttons(st.session_state.stock_title, st.session_state.stock_content, st.session_state.stock_image)
