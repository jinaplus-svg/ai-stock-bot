import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
import re

# ---------------------------------------------------------
# 1. 기본 설정 및 보안 시스템 가동
# ---------------------------------------------------------
st.set_page_config(page_title="🚀 숏폼 훅 추출기 (Cloud Ver.)", layout="wide")

# Streamlit Cloud의 [Settings] -> [Secrets]에서 API 키를 안전하게 불러옵니다.
try:
    OPENAI_API_KEY = str(st.secrets["OPENAI_API_KEY"])
except KeyError:
    st.error("⚠️ Streamlit Cloud의 Secrets에 'OPENAI_API_KEY'가 설정되지 않았습니다.")
    st.stop()

# ---------------------------------------------------------
# 2. 핵심 모터: 유튜브 ID 추출 및 무적의 대본 파싱
# ---------------------------------------------------------
def get_video_id(url):
    """유튜브 URL에서 고유 비디오 ID를 추출합니다."""
    pattern = r'(?:v=|\/)([0-9A-Za-z_-]{11}).*'
    match = re.search(pattern, url)
    return match.group(1) if match else None

def fetch_transcript(video_id):
    """언어(한국어/영어/자동생성) 따지지 않고, 유튜브에 존재하는 첫 번째 자막을 강제로 뜯어냅니다."""
    try:
        # 비디오의 모든 자막 트랙을 스캔
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # 언어 불문, 가장 먼저 잡히는 자막(수동 또는 자동생성)을 타겟팅
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
        return f"Error: 자막 추출 실패 - 자막이 완전히 비활성화된 영상이거나 지역 차단된 영상입니다. ({e})"

# ---------------------------------------------------------
# 3. 뇌(Brain): AI 프롬프트 실행
# ---------------------------------------------------------
def analyze_transcript(transcript_text, api_key):
    """가장 뼈 때리는 구간을 찾는 프롬프트를 OpenAI 모델에 주입합니다."""
    client = OpenAI(api_key=api_key)
    prompt = f"""너는 100만 구독자를 가진 동기부여 쇼츠 기획자야. 
이 대본에서 시청자의 인생을 당장 바꾸고 싶게 만드는 가장 뼈 때리는 40초 구간 2곳만 찾아줘. 
시작/종료 시간과 함께 그 대사가 왜 사람들을 멈춰 세울 수 있는지 이유를 적어줘.
(주의: 대본 원본이 영어라도, 결과와 분석은 반드시 '한국어'로 작성해)

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

# ---------------------------------------------------------
# 4. UI 및 파이프라인 실행부
# ---------------------------------------------------------
st.title("🚀 클라우드 구동형: 동기부여 숏폼 훅(Hook) 추출기")
st.markdown("당신의 숏폼 공장이 온라인에 배포되었습니다. 1시간짜리 강연의 타점(Hook)을 10초 만에 발라냅니다.")
st.divider()

# 추천 채굴장 (버튼 클릭 시 입력창에 URL 자동 입력)
st.subheader("⛏️ 원료 채굴장 (클릭하여 URL 입력)")
cols = st.columns(3)

if 'target_url' not in st.session_state:
    st.session_state.target_url = ""

if cols[0].button("🔥 세바시 (현실 조언)"):
    st.session_state.target_url = "https://youtu.be/oCtda6yxZ5c"
if cols[1].button("🧠 조던 피터슨 (동기부여)"):
    st.session_state.target_url = "https://www.youtube.com/watch?v=e8yZMArnE28"
if cols[2].button("💪 데이비드 고긴스 (채찍질)"):
    st.session_state.target_url = "https://www.youtube.com/watch?v=TLKxdTmk-zc"

url_input = st.text_input("유튜브 영상 URL을 직접 입력하세요:", value=st.session_state.target_url)

# 실행 스위치
if st.button("실행: 핵심 구간 추출", type="primary"):
    if not url_input:
        st.warning("⚠️ URL을 입력해 주십시오.")
    else:
        video_id = get_video_id(url_input)
        if not video_id:
            st.error("❌ 유효하지 않은 유튜브 URL입니다.")
        else:
            with st.spinner("1단계: 자막 방어막을 뚫고 무조건 텍스트를 긁어오는 중..."):
                transcript = fetch_transcript(video_id)
            
            if transcript.startswith("Error"):
                st.error(transcript)
            else:
                with st.expander("📝 추출된 원본 대본 확인 (해외 영상은 영어로 보입니다)"):
                    st.text_area("Transcript", transcript, height=200)
                
                with st.spinner("2단계: AI가 뼈 때리는 구간을 스캔하고 한국어로 번역 중입니다... (최대 30초)"):
                    try:
                        final_result = analyze_transcript(transcript, OPENAI_API_KEY)
                        st.success("🎉 분석 완료!")
                        st.info(final_result)
                    except Exception as ai_error:
                        st.error(f"AI 분석 오류: {ai_error}")