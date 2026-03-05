import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
import re

# --- 1. 기본 설정 ---
st.set_page_config(page_title="🚀 숏폼 훅 추출기", layout="wide")

# --- 2. 시크릿(Secrets) 연동 ---
# 귀하의 깃허브 시크릿에 있는 OPENAI_API_KEY를 참조합니다.
# (주의: Streamlit Cloud 설정의 Secrets에도 동일하게 입력되어야 합니다)
try:
        # str()로 감싸서 무조건 문자열 텍스트로만 들어가게 강제합니다.
    openai_key = str(st.secrets["OPENAI_API_KEY"])
    client = OpenAI(api_key=openai_key)

except KeyError:
    st.error("⚠️ Streamlit Secrets에 'OPENAI_API_KEY'가 누락되었습니다. 세팅을 확인하세요.")
    st.stop()

# --- 3. 핵심 모터: 유튜브 파싱 및 대본 추출 ---
def get_video_id(url):
    """유튜브 URL에서 고유 비디오 ID 11자리를 추출합니다."""
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def fetch_transcript(video_id):
    """유튜브 서버에서 영상(시각)은 버리고 대본(텍스트)만 긁어옵니다."""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
        formatted_text = ""
        for item in transcript_list:
            start_time = int(item['start'])
            start_min, start_sec = divmod(start_time, 60)
            text = item['text'].replace('\n', ' ')
            formatted_text += f"[{start_min:02d}:{start_sec:02d}] {text}\n"
        return formatted_text
    except Exception as e:
        return f"Error: 자막 추출 실패 (자막이 비활성화된 영상입니다) - {e}"

# --- 4. 뇌(Brain): AI 프롬프트 실행 ---
def analyze_transcript(transcript_text):
    """가장 뼈 때리는 구간을 찾는 프롬프트를 OpenAI 모델에 주입합니다."""
    prompt = f"""너는 100만 구독자를 가진 동기부여 쇼츠 기획자야. 
이 대본에서 시청자의 인생을 당장 바꾸고 싶게 만드는 가장 뼈 때리는 40초 구간 2곳만 찾아줘. 
시작/종료 시간과 함께 그 대사가 왜 사람들을 멈춰 세울 수 있는지 이유를 적어줘.

[대본 데이터]
{transcript_text}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a top-tier YouTube Shorts producer."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content

# --- 5. UI 및 파이프라인 실행부 ---
st.title("🚀 동기부여 숏폼 훅(Hook) 추출기")
st.markdown("1시간짜리 강연을 볼 필요 없습니다. AI가 타격감 높은 텍스트만 발라냅니다.")
st.divider()

# 추천 채굴장 (버튼 클릭 시 입력창에 URL 자동 입력)
st.subheader("⛏️ 원료 채굴장 (테스트용 URL)")
cols = st.columns(3)

if 'target_url' not in st.session_state:
    st.session_state.target_url = ""

# 타겟 버튼들 (클릭 시 URL 상태 업데이트)
if cols[0].button("🔥 세바시 (현실 조언)"):
    st.session_state.target_url = "https://youtu.be/oCtda6yxZ5c"
if cols[1].button("🧠 조던 피터슨 (동기부여)"):
    st.session_state.target_url = "https://www.youtube.com/watch?v=e8yZMArnE28"
if cols[2].button("💪 데이비드 고긴스 (채찍질)"):
    st.session_state.target_url = "https://www.youtube.com/watch?v=TLKxdTmk-zc"

# URL 입력창
url_input = st.text_input("유튜브 영상 URL을 입력하세요:", value=st.session_state.target_url)

# 실행 스위치
if st.button("실행: 핵심 구간 추출", type="primary"):
    if not url_input:
        st.warning("URL을 입력해 주십시오.")
    else:
        video_id = get_video_id(url_input)
        
        if not video_id:
            st.error("유효하지 않은 유튜브 URL입니다.")
        else:
            with st.spinner("1단계: 자막 데이터를 긁어오는 중..."):
                transcript = fetch_transcript(video_id)
            
            if transcript.startswith("Error"):
                st.error(transcript)
            else:
                with st.expander("📝 추출된 원본 대본 확인"):
                    st.text_area("Transcript", transcript, height=200)
                
                with st.spinner("2단계: AI가 뼈 때리는 구간을 스캔 중입니다... (최대 30초)"):
                    final_result = analyze_transcript(transcript)
                
                st.success("분석 완료!")
                st.markdown("### 🎯 타겟 좌표 (Hook Result)")
                st.info(final_result)
