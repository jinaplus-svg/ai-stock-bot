import os
from blog_utils import search_latest_info, generate_blog_post
from blogger_api import upload_post

BLOG_ID = os.environ.get("TRAVEL_BLOG_ID")

if __name__ == "__main__":
    query = "현재 가장 인기 있는 국내 또는 해외 여행지 1곳 추천, 구글지도 기준 주요 명소, 맛집, 영업시간, 숨겨진 팁 상세 안내"
    context = search_latest_info(query)
    
    title, content = generate_blog_post(
        system_role="프리미엄 레저 및 글로벌 여행 전문가",
        subject="현재 가장 인기 있는 여행지 추천 및 로컬 정보",
        search_context=context,
        image_keyword="beautiful travel destination landscape"
    )
    upload_post(BLOG_ID, title, content)
