import os
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("FOOD_BLOG_ID")

if __name__ == "__main__":
    query = "최근 한국에서 가장 유행하는 핫플레이스 식당 1곳 추천, 구글지도나 네이버지도 기준 위치, 영업시간, 인기 메뉴, 주차 등 추가 정보 상세 요약"
    context = search_latest_info(query)
    
    title, content = generate_blog_post(
        system_role="미식 큐레이터 및 로컬 푸드 탐험가",
        subject="최근 유행하는 핫플레이스 식당 리뷰 및 상세 지도 정보",
        search_context=context,
        image_keyword="delicious trendy restaurant food plating"
    )
    upload_post(BLOG_ID, title, content)
