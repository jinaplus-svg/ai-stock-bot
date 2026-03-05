import streamlit as st
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI
import html
import re

# 페이지 기본 설정
st.set_page_config(page_title="유튜브 쇼츠 기획기", page_icon="🎬", layout="wide")
st.title("🎬 지식 & 자기계발 유튜브 쇼츠 기획 도우미")

# 스트림릿 Secrets에서 API 키 불러오기
try:
    yt_api_key = st.secrets["YOUTUBE_API_KEY"]
    openai_api_key = st.secrets["OPENAI_API_KEY"]
except KeyError:
    st.error("🚨 API 키가 설정되지 않았습니다. Streamlit Secrets 설정을 확인해 주세요!")
    st.stop() # 키가 없으면 실행 중단

# 1. 유튜브 특정 주제 검색 함수
def search_youtube_videos(api_key, query):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.search().list(
        part="snippet",
        q=query,
        type="video",
        order="relevance", # 관련도(정확도) 순으로 변경하여 찐 채널 영상이 나오게 함
        relevanceLanguage="ko",
        maxResults=10
    )
    response = request.execute()
    return response.get('items', [])

# 2. 영상 자막(대본) 추출 함수 (시간 포함)
def get_transcript_with_time(video_id):
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript(['ko', 'en'])
        transcript_data = transcript.fetch()
        
        # 텍스트뿐만 아니라 시간(초)을 분:초 형태로 변환하여 함께 저장합니다.
        text_with_time = ""
        for t in transcript_data:
            start_min = int(t['start'] // 60)
            start_sec = int(t['start'] % 60)
            text_with_time += f"[{start_min:02d}:{start_sec:02d}] {t['text']} \n"
            
        return text_with_time, None 
    except Exception as e:
        return None, str(e)

# 유튜브 URL에서 비디오 ID를 추출하는 헬퍼 함수
def extract_video_id(url):
    match = re.search(r"(?:v=|youtu\.be/)([^&]+)", url)
    return match.group(1) if match else None

# 3. GPT 요약 함수
def summarize_video(client, text):
    prompt = f"다음은 유튜브 영상의 대본입니다. 이 영상의 핵심 내용을 3~4줄로 명확하게 요약해 주세요.\n\n대본:\n{text[:5000]}"
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# 4. 쇼츠 포인트 추출 함수 (시간 및 대본 명시)
def extract_shorts_points(client, text):
    prompt = f"""
    당신은 전문 유튜브 쇼츠(Shorts) 기획자입니다. 
    다음 시간대별 대본을 읽고, 쇼츠로 만들었을 때 가장 몰입도가 높고 흥미로운 연속된 구간(약 30초~1분 분량) 1곳을 추천해 주세요.
    
    반드시 아래 양식에 맞춰 답변해 주세요:
    - 📌 **추천 쇼츠 제목**: (시선을 끄는 제목)
    - ⏱️ **쇼츠 추천 구간 (시간)**: (예: 01:20 ~ 02:10)
    - 📜 **해당 구간 원본 대본**: (추천한 시간대의 실제 대본 내용)
    - 💡 **추천 이유**: (왜 이 구간이 쇼츠로 적합한지)
    - 💬 **쇼츠 자막으로 쓸 문구**: (실제 영상에 들어갈 다듬어진 자막 3~4문장)

    시간대별 대본:
    {text[:8000]}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# ---------------- 메인 화면 로직 ----------------
client = OpenAI(api_key=openai_api_key)

st.subheader("🔍 분석할 영상 가져오기")

# 라디오 버튼에 '직접 URL 입력' 옵션 추가
search_topic = st.radio(
    "어떤 방식으로 영상을 가져올까요?",
    ["슈카월드 (경제/이슈)", "하와이대저택 (마인드셋/자기계발)", "자기계발 동기부여", "명상 조언", "🔗 직접 URL 입력"],
    horizontal=True
)

video_id_to_analyze = None

if search_topic == "🔗 직접 URL 입력":
    # 직접 URL을 입력받는 모드
    user_url = st.text_input("유튜브 영상의 링크를 붙여넣어 주세요 (예: https://www.youtube.com/watch?v=...)")
    if user_url:
        video_id_to_analyze = extract_video_id(user_url)
        if not video_id_to_analyze:
            st.error("올바른 유튜브 링크가 아닙니다. 다시 확인해 주세요.")
else:
    # 키워드 검색 모드
    search_keyword = search_topic.split(" ")[0] 
    
    with st.spinner(f"'{search_topic}' 관련 동영상을 검색하는 중입니다..."):
        videos = search_youtube_videos(yt_api_key, search_keyword)
        
    video_options = {html.unescape(vid['snippet']['title']): vid for vid in videos if 'videoId' in vid['id']}
    
    if not video_options:
        st.error("검색된 영상이 없습니다.")
    else:
        selected_title = st.selectbox("분석할 영상을 선택하세요:", list(video_options.keys()))
        if selected_title:
            video_id_to_analyze = video_options[selected_title]['id']['videoId']
            st.write(f"**채널명:** {video_options[selected_title]['snippet']['channelTitle']}")

# 영상 ID가 확보되었을 때 분석 시작
if video_id_to_analyze:
    video_url = f"https://www.youtube.com/watch?v={video_id_to_analyze}"
    st.write(f"**선택된 영상 링크:** [{video_url}]({video_url})")
    st.markdown("---")
    
    # 자막 추출 시도
    with st.spinner("대본(시간 포함)을 추출하는 중입니다..."):
        transcript_text, error_msg = get_transcript_with_time(video_id_to_analyze)
    
    if error_msg:
        st.error("❌ 이 영상은 대본을 추출할 수 없습니다. (음악, 짧은 쇼츠, 또는 자막이 꺼진 영상일 수 있습니다.)")
        st.code(f"에러 원인: {error_msg}")
    elif transcript_text:
        st.success("✅ 영상 대본을 시간과 함께 성공적으로 추출했습니다!")
        
        tab1, tab2 = st.tabs(["📝 영상 요약 및 대본", "✂️ 쇼츠(Shorts) 기획 결과"])
        
        with tab1:
            st.subheader("영상 내용 요약")
            with st.spinner("GPT가 내용을 요약하고 있습니다..."):
                summary = summarize_video(client, transcript_text)
                st.write(summary)
                
            with st.expander("전체 추출 대본 (시간 포함) 보기"):
                # 시간 데이터가 포함되어 있으므로 화면에 그대로 출력
                st.text(transcript_text) 
                
        with tab2:
            st.info("아래 버튼을 누르면 쇼츠 구간, 시간, 원본 대본, 자막 문구가 출력됩니다.")
            if st.button("🚀 쇼츠 포인트 추출하기", type="primary"):
                with st.spinner("쇼츠 기획안을 분석 중입니다. 잠시만 기다려 주세요..."):
                    shorts_plan = extract_shorts_points(client, transcript_text)
                    st.markdown("### 💡 쇼츠 기획 결과")
                    st.write(shorts_plan)
