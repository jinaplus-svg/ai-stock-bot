# -*- coding: utf-8 -*-
"""일회성 스크립트: main_autoposter.py가 매일 글을 올리는 것과 동일한 GOOGLE_TOKEN 계정(그 블로그의
실제 관리자/소유자 계정)으로 IT/Food/Travel/Stock/News 5개 블로그에 '소개' 페이지를 올린다.
로컬 PC의 token.pickle 계정은 이 5개 블로그에서 관리자 권한이 없어 Pages API가 403을 반환했음
(실제 확인됨) — 반면 GOOGLE_TOKEN은 이미 매일 posts().insert()로 발행 중인, 진짜 권한을 가진
계정이라 여기서는 문제없이 동작해야 한다. GitHub Actions에서만 GOOGLE_TOKEN 값을 읽을 수 있어
이 스크립트도 워크플로우로 1회 실행한다."""
import os
import sys
import json

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

GOOGLE_OAUTH_TOKEN_STR = os.environ.get("GOOGLE_TOKEN")
SCOPES = ["https://www.googleapis.com/auth/blogger"]

BLOGS = [
    {"category": "IT", "blog_id": "3604625893082334613", "html_file": "about_page_IT.html"},
    {"category": "Food", "blog_id": "4369107221236736479", "html_file": "about_page_Food.html"},
    {"category": "Travel", "blog_id": "4346940314985817707", "html_file": "about_page_Travel.html"},
    {"category": "Stock", "blog_id": "7724943683997188616", "html_file": "about_page_Stock.html"},
    {"category": "News", "blog_id": "2731304246767986979", "html_file": "about_page_News.html"},
]


def _get_blogger_service():
    token_info = json.loads(GOOGLE_OAUTH_TOKEN_STR)
    creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("blogger", "v3", credentials=creds)


def find_existing_about_page(service, blog_id):
    pages = service.pages().list(blogId=blog_id).execute()
    for p in pages.get("items", []):
        if p.get("title", "").strip() in ("소개", "About", "블로그 소개"):
            return p.get("id")
    return None


def main():
    service = _get_blogger_service()
    for blog in BLOGS:
        print(f"\n=== {blog['category']} ===")
        try:
            with open(blog["html_file"], encoding="utf-8") as f:
                html_content = f.read()
        except FileNotFoundError:
            print(f"❌ {blog['html_file']} 없음 — 건너뜀")
            continue

        try:
            existing_id = find_existing_about_page(service, blog["blog_id"])
            if existing_id:
                page = service.pages().update(
                    blogId=blog["blog_id"], pageId=existing_id,
                    body={"title": "소개", "content": html_content}).execute()
                print(f"✅ 업데이트: {page.get('url')}")
            else:
                page = service.pages().insert(
                    blogId=blog["blog_id"], body={"title": "소개", "content": html_content}).execute()
                print(f"✅ 신규 생성: {page.get('url')}")
        except Exception as e:
            print(f"❌ 실패: {e}")


if __name__ == "__main__":
    main()
