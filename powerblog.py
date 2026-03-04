import streamlit as st
import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ==========================================
# 1. 초기 설정 및 시크릿 키 불러오기
# ==========================================
st.set_page_config(page_title="IT대디의 블로그 자동화", page_icon="🤖", layout="wide")

try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
    UNSPLASH_ACCESS_KEY = st.secrets["UNSPLASH_ACCESS_KEY"]
    BLOG_ID = st.secrets["BLOG_ID"]
    GOOGLE_OAUTH_TOKEN_STR = st.secrets["GOOGLE_OAUTH_TOKEN"]
    # 이메일 발송용 시크릿 (Gmail 권장)
    EMAIL_USER = st.secrets["EMAIL_USER"]
    EMAIL_PASSWORD = st.secrets["EMAIL_PASSWORD"]
except KeyError as e:
    st.error(f"시크릿 키 설정이 누락되었습니다: {e}")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)
SCOPES = ['https://www.googleapis.com/auth/blogger']

# ==========================================
# 2. Session State 초기화 (상태 유지용)
# ==========================================
if 'topics' not in st.session_state:
    st.session_state.topics = []
if 'generated_title' not in st.session_state:
    st.session_state.generated_title = ""
if 'generated_content' not in st.session_state:
    st.session_state.generated_content = ""
if 'image_url' not in st.session_state:
    st.session_state.image_url = ""

# ==========================================
# 3. 기능 함수들
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

def fetch_trending_topics():
    """최신 AI/IT 트렌드 주제 3개 추출"""
    prompt = "현재 가장 주목받는 최신 AI 및 IT 트렌드 중에서 블로그 포스팅으로 매력적인 주제 3가지를 추천해줘. 1., 2., 3. 번호를 붙여서 제목만 간결하게 줄바꿈해서 출력해."
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    content = response.choices[0].message.content
    # GPT 응답에서 텍스트 라인만 추출하여 리스트로 저장
    topics = [line.strip() for line in content.split('\n') if line.strip() and line[0].isdigit()]
    st.session_state.topics = topics[:3]

def generate_trend_blog(topic):
    """선택/입력된 주제로 블로그 글 및 이미지 생성"""
    st.session_state.generated_title = f"[AI/IT 트렌드] {topic.replace('1. ', '').replace('2. ', '').replace('3. ', '')}"
    
    prompt = f"""
    당신은 'IT대디'라는 닉네임을 가진 15년 차 IT 전문 블로거입니다.
    다음 주제로 애드센스 승인과 방문자 유입에 유리한 블로그 포스팅을 작성해주세요.
    주제: {topic}
    
    [조건]
    1. 분량은 공백 포함 1,500자 이상으로 상세히 작성할 것.
    2. 전문적이면서도 아빠처럼 친절하고 이해하기 쉬운 말투 사용.
    3. 구글 블로그에 바로 올릴 수 있게 순수 HTML 태그(<h2>, <h3>, <p>, <ul>, <li>, <b> 등)만 사용할 것 (마크다운 생략).
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    st.session_state.generated_content = response.choices[0].message.content
    st.session_state.image_url = get_unsplash_image("technology artificial intelligence trend")

def post_to_blogger():
    """구글 블로그 발행"""
    creds = get_google_auth()
    service = build('blogger', 'v3', credentials=creds)
    
    full_html = ""
    if st.session_state.image_url:
        full_html += f'<div style="text-align: center; margin-bottom: 30px;"><img src="{st.session_state.image_url}" style="max-width: 100%; border-radius: 8px;" /></div>'
    full_html += st.session_state.generated_content
    
    body = {"title": st.session_state.generated_title, "content": full_html}
    request = service.posts().insert(blogId=BLOG_ID, body=body, isDraft=False)
    return request.execute().get('url')

def send_email(to_email):
    """생성된 HTML 내용을 이메일로 전송"""
    msg = MIMEMultipart("alternative")
    msg['Subject'] = st.session_state.generated_title
    msg['From'] = EMAIL_USER
    msg['To'] = to_email

    html_body = f"""
    <html>
      <body>
        <h2>{st.session_state.generated_title}</h2>
        <img src="{st.session_state.image_url}" style="max-width: 600px; border-radius: 8px;" />
        <br><br>
        {st.session_state.generated_content}
      </body>
    </html>
    """
    part = MIMEText(html_body, 'html')
    msg.attach(part)

    # Gmail SMTP 서버 설정 (네이버/카카오 등 다른 메일이면 서버 주소 변경 필요)
    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(EMAIL_USER, EMAIL_PASSWORD)
    server.sendmail(EMAIL_USER, to_email, msg.as_string())
    server.quit()

# ==========================================
# 4. Streamlit UI 화면 구성
# ==========================================
st.title("🤖 IT대디의 블로그 자동화 시스템")
st.markdown("최신 트렌드 분석부터 블로그 발행, 이메일 전송까지 한 번에 해결하세요!")
st.divider()

# --- STEP 1: 주제 선택 ---
st.header("Step 1. 포스팅 주제 선택")

col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🔄 AI가 추천하는 최신 트렌드 3개 가져오기"):
        with st.spinner("트렌드 분석 중..."):
            fetch_trending_topics()

# 추천 주제가 있으면 라디오 버튼 표시
selected_topic = ""
if st.session_state.topics:
    selected_topic = st.radio("👇 맘에 드는 주제를 선택하세요:", st.session_state.topics)

st.markdown("**또는 직접 쓰고 싶은 주제를 입력하세요:**")
manual_topic = st.text_input("📝 직접 입력 (입력 시 추천 주제보다 우선 적용됩니다)")

final_topic = manual_topic if manual_topic.strip() else selected_topic

if st.button("✨ 선택한 주제로 글 생성하기", type="primary"):
    if final_topic:
        with st.spinner("AI가 이미지를 찾고 정성껏 글을 작성 중입니다... (약 20초 소요)"):
            generate_trend_blog(final_topic)
        st.success("글 작성이 완료되었습니다! 아래 화면을 확인해주세요.")
    else:
        st.warning("주제를 선택하거나 직접 입력해주세요!")

st.divider()

# --- STEP 2: 미리보기 및 발행 ---
if st.session_state.generated_content:
    st.header("Step 2. 미리보기 및 액션")
    
    # 미리보기 영역
    with st.expander("👀 작성된 블로그 미리보기 (클릭하여 펼치기)", expanded=True):
        st.subheader(st.session_state.generated_title)
        if st.session_state.image_url:
            st.image(st.session_state.image_url, use_container_width=True)
        st.components.v1.html(st.session_state.generated_content, height=500, scrolling=True)
    
    st.write("---")
    
    # 액션 영역 (블로그 발행 / 이메일 전송)
    action_col1, action_col2 = st.columns([1, 1])
    
    with action_col1:
        st.markdown("#### 🌐 구글 블로그에 바로 올리기")
        if st.button("🚀 블로그에 포스팅하기"):
            with st.spinner("업로드 중입니다..."):
                try:
                    post_url = post_to_blogger()
                    st.success(f"🎉 포스팅 성공! [여기에서 확인하세요]({post_url})")
                    st.balloons()
                except Exception as e:
                    st.error(f"업로드 오류: {e}")

    with action_col2:
        st.markdown("#### ✉️ 이메일로 전송하기")
        # 기본값을 Secrets에 등록된 본인 이메일로 설정
        target_email = st.text_input("받을 사람 이메일", value=EMAIL_USER)
        if st.button("전송하기"):
            with st.spinner("이메일 발송 중..."):
                try:
                    send_email(target_email)
                    st.success(f"✅ {target_email} 주소로 메일을 성공적으로 보냈습니다!")
                except Exception as e:
                    st.error(f"이메일 발송 오류: {e}")
