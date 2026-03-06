import os
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def upload_post(blog_id, title, content):
    token_json = os.environ.get('GOOGLE_TOKEN')
    if not token_json:
        print("❌ GOOGLE_TOKEN이 설정되지 않았습니다.")
        return

    # 문자열로 저장된 JSON 파싱
    creds_dict = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(creds_dict)
    
    # Blogger API 서비스 빌드
    service = build('blogger', 'v3', credentials=creds)
    
    post_data = {
        'kind': 'blogger#post',
        'title': title,
        'content': content
    }
    
    try:
        request = service.posts().insert(blogId=blog_id, body=post_data, isDraft=False)
        response = request.execute()
        print(f"✅ 포스팅 성공! URL: {response.get('url')}")
    except Exception as e:
        print(f"❌ 포스팅 실패: {e}")
