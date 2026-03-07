import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("STOCK_BLOG_ID")

if __name__ == "__main__":
    print("📈 Stock 블로그 자동 포스팅 시작... (심층 버전)")
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 10: # 오전 07시 (미국 유망 중소형주)
        target = "미국 주식 시장 (NASDAQ/NYSE)"
        query = "애플, 엔비디아, 테슬라 같은 대형주 제외! 오늘 미국 증시에서 새롭게 급등했거나 주목받는 '숨겨진 유망 중소형주' 또는 '신규 상장 테마주' 1개 집중 분석, 정확한 종목명 및 티커, 해당 기업의 기술력, 시장 전망, 최근 호재 뉴스 심층 요약"
    elif hour < 15: # 오후 12시 (한국 오전장 주도주)
        target = "한국 주식 시장 (KOSPI/KOSDAQ 오전장)"
        query = "삼성전자, SK하이닉스, 에코프로 등 뻔한 대형주 제외! 오늘 한국 오전장에서 기관/외국인 수급이 몰리며 새롭게 떠오른 '개별 테마주'나 '강소기업' 1개 선정, 정확한 종목명 및 코드, 상승 이유 분석, 과거 주가 흐름 비교"
    else: # 오후 17시 (한국 특징주 마감)
        target = "한국 주식 시장 (마감 특징주)"
        query = "뻔한 대장주 제외! 오늘 장 마감 기준 가장 큰 이슈를 만들었거나 호재 뉴스가 있는 한국 증시의 '숨은 흑진주' 같은 종목 1개 선정, 정확한 종목명 및 코드, 뉴스 상세 요약 및 내일이 기대되는 이유 분석"
        
    context = search_latest_info(query)
    title, content = generate_blog_post(
        system_role="트렌드 캐치 주식 트레이더 지니",
        subject=f"오늘의 {target} 숨은 급등주 심층 분석",
        search_context=context
    )
    upload_post(BLOG_ID, title, content, "Stock 블로그")
