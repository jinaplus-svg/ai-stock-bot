import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("TRAVEL_BLOG_ID")

if __name__ == "__main__":
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 12: # 오전 10시 (힐링/자연)
        query = "제주도, 강원도 같은 광범위한 지역명 말고! '제주 구좌읍의 비밀스러운 숲길'이나 '강원도 영월의 숨은 계곡' 처럼 이름이 구체적이고 요즘 뜨는 자연 힐링 스팟 1곳 상세 소개"
        subject = "나만 알고 싶은 국내 힐링 숨은 명소"
    elif hour < 18: # 오후 15시 (이색 카페/공간)
        query = "최근 SNS에서 건축물이나 인테리어가 특이해서 인생샷 성지로 불리는 구체적인 지방의 대형 카페나 복합문화공간 1곳. 주소, 포토존 위치, 분위기 묘사"
        subject = "막 찍어도 인생샷, 핫플레이스 공간 투어"
    else: # 오후 20시 (야경/도심)
        query = "야경이 미치도록 아름다운 국내 특정 장소(예: 부산 영도의 어느 골목, 야간 개장하는 특정 고궁 등) 1곳. 감성적인 묘사와 야간 방문 팁"
        subject = "감성 터지는 환상적인 야경 스팟 추천"
        
    context = search_latest_info(query)
    title, content = generate_blog_post("감성 여행 크리에이터 지니", subject, context)
    upload_post(BLOG_ID, title, content, "Travel 블로그")
