import os
import pytz
from datetime import datetime
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("TRAVEL_BLOG_ID")

if __name__ == "__main__":
    print("✈️ Travel 블로그 자동 포스팅 시작... (심층 버전)")
    kst = pytz.timezone('Asia/Seoul')
    hour = datetime.now(kst).hour
    
    if hour < 12: # 오전 10시 (힐링/자연 명소)
        query = "제주도, 강원도 같은 광범위한 지역명 말고! '제주 구좌읍의 비밀스러운 숲길'이나 '강원도 영월의 숨은 계곡' 처럼 이름이 구체적이고 요즘 뜨는 자연 힐링 스팟 1곳 상세 소개, 정확한 장소명, 실제 방문자 후기, 자연 풍경 묘사, 주차 정보 및 가는 방법 상세 요약"
        subject = "나만 알고 싶은 국내 힐링 숨은 명소 심층 리뷰"
    elif hour < 18: # 오후 15시 (이색 카페/공간)
        query = "최근 SNS에서 건축물이나 인테리어가 특이해서 인생샷 성지로 불리는 구체적인 지방의 대형 카페나 복합문화공간 1곳 추천, 정확한 상호명, 포토존 위치, 분위기 묘사, 구글 지도 주소 및 영업시간 요약"
        subject = "막 찍어도 인생샷, 핫플레이스 공간 투어 심층 리뷰"
    else: # 오후 20시 (야경/도심 스팟)
        query = "야경이 미치도록 아름다운 국내 특정 장소(예: 부산 영도의 어느 골목, 야간 개장하는 특정 고궁 등) 1곳 추천, 정확한 장소명, 감성적인 묘사와 야간 방문 팁 상세 안내"
        subject = "감성 터지는 환상적인 국내 야경 스팟 추천"
        
    context = search_latest_info(query)
    title, content = generate_blog_post(
        system_role="감성 여행 크리에이터 지니",
        subject=subject,
        search_context=context
    )
    upload_post(BLOG_ID, title, content, "Travel 블로그")
