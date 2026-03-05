import streamlit as st
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from openai import OpenAI

# 페이지 기본 설정
st.set_page_config(page_title="유튜브 쇼츠 기획기", page_icon="🎬", layout="wide")
st.title("🎬 트렌딩 유튜브 & 쇼츠 기획 도우미")

# Streamlit Secrets에서 API 키 불러오기 (안전한 방식)
try:
    yt_api_key = st.secrets["YOUTUBE_API_KEY"]
    openai_api_key = st.secrets["OPENAI_API_KEY"]
except KeyError:
    st.error("🚨 API 키가 설정되지 않았습니다! Streamlit Cloud 설정에서 Secrets를 먼저 입력해 주세요.")
    st.stop() # 키가 없으면 여기서 실행을 멈춥니다.

# 1. 유튜브 인기 영상 가져오기 함수
def get_trending_videos(api_key):
    youtube = build('youtube', 'v3', developerKey=api_key)
    request = youtube.videos().list(
        part="snippet",
        chart="mostPopular",
        regionCode="KR",
        maxResults=10 # 상위 10개 가져오기
    )
    response = request.execute()
    return response.get('items', [])

# 2. 영상 자막(대본) 추출 함수
def get_transcript(video_id):
    try:
        # 한국어 우선, 없으면 영어 자막 시도
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
        text = " ".join([t['text'] for t in transcript_list])
        return text
    except Exception as e:
        return None

# 3. GPT 요약 함수
def summarize_video(client, text):
    prompt = f"다음은 유튜브 영상의 대본입니다. 이 영상의 핵심 내용을 3~4줄로 명확하게 요약해 주세요.\n\n대본:\n{text[:3000]}"
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# 4. 쇼츠 포인트 추출 함수
def extract_shorts_points(client, text):
    prompt = f"""
    당신은 전문 유튜브 쇼츠(Shorts) 기획자입니다. 
    다음 대본을 읽고 쇼츠로 만들었을 때 가장 조회수가 높을 만한 흥미롭거나 재미있는 구간을 1곳 추천해 주세요.
    
    반드시 아래 양식에 맞춰 답변해 주세요:
    - 📌 **추천 쇼츠 제목**: (시선을 끄는 제목)
    - ⏱️ **내용 및 추천 이유**: (어떤 내용이며 왜 이 구간이 좋은지)
    - 💬 **쇼츠 자막으로 쓸 문구**: (실제 영상에 들어갈 자막 3~4문장)

    대본:
    {text[:4000]}
    """
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=openai_api_key)

st.subheader("🔥 현재 한국 유튜브 인기 동영상")

with st.spinner("인기 동영상을 불러오는 중입니다..."):
    try:
        videos = get_trending_videos(yt_api_key)
        
        # 비디오 제목으로 선택 박스 만들기
        video_options = {vid['snippet']['title']: vid for vid in videos}
        selected_title = st.selectbox("분석할 영상을 선택하세요:", list(video_options.keys()))
        
        if selected_title:
            selected_video = video_options[selected_title]
            video_id = selected_video['id']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            channel_title = selected_video['snippet']['channelTitle']
            
            # 영상 정보 출력
            st.write(f"**채널명:** {channel_title}")
            st.write(f"**링크:** [{video_url}]({video_url})")
            
            st.markdown("---")
            
            # 자막 추출 및 분석
            transcript_text = get_transcript(video_id)
            
            if transcript_text:
                st.success("✅ 영상 대본을 성공적으로 추출했습니다!")
                
                # 탭을 사용하여 UI를 깔끔하게 분리
                tab1, tab2 = st.tabs(["📝 영상 요약 및 대본", "✂️ 쇼츠(Shorts) 포인트 기획"])
                
                with tab1:
                    st.subheader("영상 내용 요약")
                    with st.spinner("GPT가 내용을 요약하고 있습니다..."):
                        summary = summarize_video(client, transcript_text)
                        st.write(summary)
                        
                    with st.expander("전체 추출 대본 보기"):
                        st.write(transcript_text)
                        
                with tab2:
                    st.info("버튼을 누르면 GPT가 대본을 분석하여 쇼츠로 만들기 좋은 구간을 추천해 줍니다.")
                    if st.button("🚀 쇼츠 포인트 추출하기", type="primary"):
                        with st.spinner("쇼츠 기획안을 작성하는 중입니다. 잠시만 기다려 주세요..."):
                            shorts_plan = extract_shorts_points(client, transcript_text)
                            st.markdown("### 💡 쇼츠 기획 결과")
                            st.write(shorts_plan)
            else:
                st.error("❌ 이 영상은 자막(CC)이 제공되지 않아 텍스트를 추출할 수 없습니다. 다른 영상을 선택해 주세요.")
                
    except Exception as e:
        st.error(f"데이터를 불러오는 중 오류가 발생했습니다. API 키가 정확한지 확인해 주세요. (에러: {e})")
