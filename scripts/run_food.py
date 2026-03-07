import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("FOOD_BLOG_ID")

if __name__ == "__main__":
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 14: # 오전 11시 (직장인 점심 타겟)
        query = "최근 SNS에서 뜨는 서울 성수동이나 연남동의 숨겨진 점심 맛집 1곳. 메뉴 비주얼, 웨이팅 팁, 정확한 위치 요약"
        subject = "요즘 핫한 점심 성지 맛집 리뷰"
    elif hour < 18: # 오후 16시 (분위기 좋은 저녁/데이트 타겟)
        query = "최근 인스타그램에서 뷰가 좋거나 분위기 미쳤다고 소문난 파인다이닝 또는 오마카세 1곳. 특별한 메뉴, 예약 꿀팁, 구체적 장소"
        subject = "분위기 끝판왕, 기념일 추천 맛집"
    else: # 오후 21시 (야식/술집 타겟)
        query = "최근 힙스터들이 많이 가는 을지로, 하이볼 명소, 독특한 안주가 있는 로컬 술집 1곳. 시그니처 메뉴와 매장 분위기 상세 묘사"
        subject = "퇴근 후 힐링, 나만 알고 싶은 힙한 술집"
        
    context, images = search_latest_info(query) # 👈 images 변수 추가
    title, content = generate_blog_post("역할", subject, context, images) # 👈 맨 끝에 images 전달
    upload_post(BLOG_ID, title, content, "Food 블로그")
