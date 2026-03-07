import os
import json
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def send_telegram_message(blog_name, url):
    """텔레그램으로 포스팅 성공 알림 및 링크 전송"""
    token = os.environ.get('TELEGRAM_TOKEN')
    chat_id = os.environ.get('CHAT_ID')
    if token and chat_id:
        text = f"🎉 [{blog_name}] 새 포스팅이 업로드되었습니다!\n👉 확인하기: {url}"
        req_url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(req_url, data={"chat_id": chat_id, "text": text})

def upload_post(blog_id, title, content, blog_name="블로그"):
    token_json = os.environ.get('GOOGLE_TOKEN')
    if not token_json:
        print("❌ GOOGLE_TOKEN이 설정되지 않았습니다.")
        return

    creds_dict = json.loads(token_json)
    creds = Credentials.from_authorized_user_info(creds_dict)
    service = build('blogger', 'v3', credentials=creds)
    
    post_data = {'kind': 'blogger#post', 'title': title, 'content': content}
    
    try:
        request = service.posts().insert(blogId=blog_id, body=post_data, isDraft=False)
        response = request.execute()
        post_url = response.get('url')
        print(f"✅ 포스팅 성공! URL: {post_url}")
        
        # 성공 시 텔레그램 알림 발송
        send_telegram_message(blog_name, post_url)
    except Exception as e:
        print(f"❌ 포스팅 실패: {e}")
