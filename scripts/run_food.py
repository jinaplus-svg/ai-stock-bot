import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("FOOD_BLOG_ID")

if __name__ == "__main__":
    print("🍱 Food 블로그 자동 포스팅 시작... (심층 버전)")
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 14: # 오전 11시 포스팅 (직장인 점심 타겟)
        query = "최근 SNS에서 뜨는 서울 성수동이나 연남동의 숨겨진 점심 맛집 1곳 추천, 정확한 상호명, 실제 방문자 후기, 시그니처 메뉴의 맛과 비주얼 묘사, 구글 지도 기반 위치 및 영업시간 상세 요약"
        subject = "성수/연남 숨은 점심 맛집 심층 리뷰"
    elif hour < 18: # 오후 16시 포스팅 (분위기 좋은 저녁/데이트 타겟)
        query = "최근 인스타그램에서 뷰가 좋거나 분위기 미쳤다고 소문난 파인다이닝 또는 오마카세 1곳 추천, 정확한 상호명, 코스 요리 구성, 예약 꿀팁, 구체적 장소 정보"
        subject = "기념일 추천, 분위기 핫플레이스 식당 리뷰"
    else: # 오후 21시 포스팅 (야식/술집 타겟)
        query = "최근 힙스터들이 많이 가는 을지로, 하이볼 명소, 독특한 안주가 있는 로컬 술집 1곳 추천, 정확한 상호명, 매장 분위기 상세 묘사 및 시그니처 안주 후기"
        subject = "퇴근 후 힐링, 나만 알고 싶은 힙한 술집 리뷰"
        
    context = search_latest_info(query)
    
    title, content = generate_blog_post(
        system_role="미식 큐레이터 및 푸드 탐험가 지니",
        subject=subject,
        search_context=context
    )
    upload_post(BLOG_ID, title, content, "Food 블로그")
