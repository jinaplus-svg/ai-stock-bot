import streamlit as st
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
import re

# ---------------------------------------------------------
# 1. 시스템 엔진 및 보안 장착
# ---------------------------------------------------------
st.set_page_config(page_title="🚀 PRO 숏폼 훅 추출기", layout="wide")

try:
    # 공식 루트: Streamlit Secrets에서 두 개의 키를 모두 호출
    YOUTUBE_API_KEY = str(st.secrets["YOUTUBE_API_KEY"])
    OPENAI_API_KEY = str(st.secrets["OPENAI_API_KEY"])
    
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    client = OpenAI(api_key=OPENAI_API_KEY)
except KeyError as e:
    st.error(f"⚠️ Secrets 설정이 누락되었습니다: {e}")
    st.stop()

# ---------------------------------------------------------
# 2. 공식 API 기반 데이터 수집 모듈
# ---------------------------------------------------------
def get_video_info(video_id):
    """구글 공식 API를 사용하여 영상 제목과 정보를 가져옵니다."""
    request = youtube.videos().list(part="snippet", id=video_id)
    response = request.execute()
    if response['items']:
        return response['items'][0]['snippet']['title']
    return "알 수 없는 영상"

def get_video_id(url):
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def fetch_transcript_pro(video_id):
    """무적의 자막 추출: 공식 API로 경로를 확인하고 텍스트를 파싱합니다."""
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        # 한국어 최우선 -> 영어 -> 그다음 아무거나(자동생성 포함)
        try:
            transcript = transcript_list.find_transcript(['ko', 'en'])
        except:
            transcript = next(iter(transcript_list))
            
        fetched_data = transcript.fetch()
        formatted_text = ""
        for item in fetched_data:
            start_time = int(item['start'])
            start_min, start_sec = divmod(start_time, 60)
            text = item['text'].replace('\n', ' ')
            formatted_text += f"[{start_min:02d}:{start_sec:02d}] {text}\n"
        return formatted_text
    except Exception as e:
        return f"Error: 자막 추출 불가 ({e})"

# ---------------------------------------------------------
# 3. AI 전략 분석 모듈 (100만 유튜버 기획자 뇌)
# ---------------------------------------------------------
def analyze_content(title, transcript):
    prompt = f"""너는 100만 구독자를 가진 숏폼 전문 기획자야.
아래 영상의 '제목'과 '전체 대본'을 분석해서, 숏폼으로 만들었을 때 조회수가 폭발할 '최고의 훅(Hook)' 구간 2곳을 선정해줘.

영상 제목: {title}

[분석 지침]
1. 시청자의 시선을 3초 안에 뺏을 수 있는 강렬한 문장이 포함된 구간일 것.
2. 정확한 [시작시간-종료시간]을 표시할 것.
3. 해당 구간의 '대사 내용'과 '선정 이유'를 상세히 적어줘.
4. 결과는 무조건 한국어로 작성해.

대본 데이터:
{transcript}
"""
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You are a viral content expert."},
                  {"role": "user", "content": prompt}],
        temperature=0.8
    )
    return response.choices[0].message.content

# ---------------------------------------------------------
# 4. 인터랙티브 UI (사용자 환경)
# ---------------------------------------------------------
st.title("🎯 PRO급 숏폼 타겟팅 시스템")
st.markdown("구글 공식 API와 GPT-4o-mini 엔진을 결합한 가장 안정적인 숏폼 생산 기계입니다.")
st.divider()

# 추천 채굴장
st.subheader("⛏️ 분석 타겟 추천")
cols = st.columns(3)
if 'target_url' not in st.session_state: st.session_state.target_url = ""

samples = {
    "🔥 슈카월드 (경제/이슈)": "https://www.youtube.com/watch?v=F0f-E4kQO4Y",
    "🧠 조던 피터슨 (심리)": "https://www.youtube.com/watch?v=e8yZMArnE28",
    "💪 데이비드 고긴스 (동기부여)": "https://www.youtube.com/watch?v=TLKxdTmk-zc"
}

for i, (name, url) in enumerate(samples.items()):
    if cols[i].button(name): st.session_state.target_url = url

target_url = st.text_input("유튜브 링크를 입력하세요:", value=st.session_state.target_url)

if st.button("🚀 숏폼 하이라이트 발췌 시작", type="primary"):
    video_id = get_video_id(target_url)
    if not video_id:
        st.error("URL이 올바르지 않습니다.")
    else:
        with st.status("🛠️ 시스템 가동 중...", expanded=True) as status:
            st.write("1️⃣ 구글 API 접속 및 영상 정보 확인 중...")
            title = get_video_info(video_id)
            st.write(f"📺 영상 제목: **{title}**")
            
            st.write("2️⃣ 고밀도 자막 데이터 추출 중...")
            transcript = fetch_transcript_pro(video_id)
            
            if "Error" in transcript:
                st.error(transcript)
                status.update(label="분석 실패", state="error")
            else:
                st.write("3️⃣ AI 기획자가 터지는 구간을 선별 중...")
                analysis = analyze_content(title, transcript)
                
                st.success("✅ 분석 완료!")
                status.update(label="분석 성공", state="complete")
                
                st.divider()
                st.markdown("### 🏆 AI 기획자의 숏폼 발췌 리포트")
                st.info(analysis)
                
                with st.expander("📝 전체 대본 데이터 보기"):
                    st.text_area("Transcript Data", transcript, height=300)
