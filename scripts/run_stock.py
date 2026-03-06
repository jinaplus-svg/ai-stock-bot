import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("STOCK_BLOG_ID")

if __name__ == "__main__":
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 12: # 오전 7시 실행 시
        target = "미국 주식 시장(나스닥, S&P500)"
        image_keyword = "wall street stock market graph"
    else:         # 오후 4시 실행 시
        target = "한국 주식 시장(코스피, 코스닥)"
        image_keyword = "stock market chart finance korea"
        
    query = f"오늘 {target} 가장 이슈가 많았던 주식 1~2개 선정, 관련 기사 요약 및 최근 주가 변동 정보"
    context = search_latest_info(query)
    
    title, content = generate_blog_post(
        system_role="데이터 기반 주식 분석가 및 트레이더",
        subject=f"오늘의 {target} 핫이슈 종목 분석",
        search_context=context,
        image_keyword=image_keyword
    )
    upload_post(BLOG_ID, title, content)
