import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("NEWS_BLOG_ID")

if __name__ == "__main__":
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 10: # 오전 08시 (경제/시사)
        channel = "삼프로TV"
        theme = "경제/금융 최신 이슈"
    elif hour < 15: # 오후 13시 (이슈/인물)
        channel = "바비위키(김바비)"
        theme = "흥미로운 인물이나 사건"
    else: # 오후 18시 (사회/글로벌)
        channel = "슈카월드"
        theme = "사회/글로벌 트렌드"
        
    query = f"유튜브 '{channel}'의 최근 영상 중 '{theme}'에 관련된 내용을 하나 골라 상세히 요약하고, 대중들이 흥미로워할 꿀잼 배경지식 추가"
    context = search_latest_info(query)
    title, content = generate_blog_post("유튜브 트렌드 분석가 지니", f"오늘의 {channel} 핫클립 리뷰", context)
    upload_post(BLOG_ID, title, content, "News 블로그")
