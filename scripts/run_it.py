import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("IT_BLOG_ID")

if __name__ == "__main__":
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 12: # 오전 9시
        query = "최신 AI 및 컴퓨터공학 ArXiv 논문 중 가장 흥미로운 1개 선정해서 핵심 내용 쉽게 요약"
        subject = "최신 AI 논문 인사이트"
        img = "artificial intelligence futuristic technology"
    elif hour < 18: # 오후 2시
        query = "오늘 GitHub에서 가장 급상승(Trending) 중인 오픈소스 프로젝트 1개 소개 및 기능 설명"
        subject = "오늘의 깃허브 트렌딩 오픈소스"
        img = "software development code screen"
    else: # 오후 9시
        query = "오늘 가장 인기 많았던 최신 IT/테크 기사 내용 요약 및 시사점"
        subject = "오늘의 주요 IT 뉴스 브리핑"
        img = "latest technology gadget laptop"
        
    context = search_latest_info(query)
    title, content = generate_blog_post("전자공학 및 AI 전문 테크 리뷰어", subject, context, img)
    upload_post(BLOG_ID, title, content)
