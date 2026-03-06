import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("NEWS_BLOG_ID")

if __name__ == "__main__":
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 11: # 오전 8시
        channel = "삼프로TV"
    elif hour < 18: # 오후 12시 30분
        channel = "바비위키(김바비)"
    else: # 오후 10시
        channel = "슈카월드"
        
    query = f"유튜브 '{channel}' 채널의 가장 최신 영상 내용 요약해주고, 이 주제와 관련된 대중들이 흥미로워할 만한 재미있는 배경 지식이나 에피소드 추가해줘. 만약 최신 영상이 없다면 채널의 대표적인 인기 주제로 해줘."
    context = search_latest_info(query)
    
    title, content = generate_blog_post(
        system_role="유튜브 트렌드 분석가 및 스토리텔러",
        subject=f"{channel} 최신 이슈 및 관련 꿀잼 지식",
        search_context=context,
        image_keyword=f"youtube creator broadcasting {channel}"
    )
    upload_post(BLOG_ID, title, content)
