import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("IT_BLOG_ID")

if __name__ == "__main__":
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 12: # 오전 09시 (딥다이브 테크)
        query = "최신 생성형 AI 모델이나 로봇공학 관련 흥미로운 기술 논문 또는 외신 심층 보도 1개 요약"
        subject = "최신 딥테크 인사이트"
    elif hour < 16: # 오후 14시 (개발자 트렌드)
        query = "최근 GitHub에서 별(Star)을 많이 받고 있는 유용한 생산성 도구나 신박한 오픈소스 라이브러리 1개 소개"
        subject = "오늘의 신박한 깃허브 트렌딩 툴"
    else: # 오후 19시 (IT 대중 뉴스)
        query = "애플, 구글, 일론 머스크 등 글로벌 빅테크 기업들의 오늘 하루 가장 파격적이거나 재미있었던 행보/신제품 소식 1개"
        subject = "오늘의 글로벌 빅테크 꿀잼 이슈"
        
    context, images = search_latest_info(query)
    title, content = generate_blog_post("테크 긱(Geek) 리뷰어 지니", subject, context, images)
    upload_post(BLOG_ID, title, content, "IT 블로그")
