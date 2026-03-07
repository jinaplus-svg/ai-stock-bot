import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("IT_BLOG_ID")

if __name__ == "__main__":
    print("💻 IT 블로그 자동 포스팅 시작...")
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 12:
        query = "최신 AI 및 컴퓨터공학 논문 중 가장 흥미로운 1개 선정해서 핵심 내용 쉽게 요약"
        subject = "최신 AI/테크 인사이트"
    elif hour < 16:
        query = "최근 GitHub에서 별(Star)을 많이 받고 있는 유용한 생산성 도구나 신박한 오픈소스 라이브러리 1개 소개"
        subject = "오늘의 신박한 깃허브 트렌딩 툴"
    else:
        query = "애플, 구글, 일론 머스크 등 글로벌 빅테크 기업들의 오늘 하루 가장 파격적이거나 재미있었던 행보/신제품 소식 1개"
        subject = "오늘의 글로벌 빅테크 꿀잼 이슈"
        
    context = search_latest_info(query)
    title, content = generate_blog_post(
        system_role="테크 긱(Geek) 리뷰어 지니",
        subject=subject,
        search_context=context
    )
    upload_post(BLOG_ID, title, content, "IT 블로그")
