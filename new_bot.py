import os
import smtplib
import requests
import feedparser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
from datetime import datetime

# ==========================================
# [설정] 환경변수 (기존 주식 봇과 이름 통일)
# ==========================================
# 1. 새로 필요한 것 (OpenAI 키)
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') 

# 2. 기존에 설정해둔 것들 (재사용)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')       # TELEGRAM_CHAT_ID -> CHAT_ID로 변경
EMAIL_USER = os.environ.get('EMAIL_USER') # GMAIL_USER -> EMAIL_USER로 변경
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD') # GMAIL_APP_PASSWORD -> EMAIL_PASSWORD로 변경

# 받는 사람 = 보내는 사람 (나에게 쓰기)
EMAIL_RECEIVER = EMAIL_USER 

# ==========================================
# [기능 1] 구글 뉴스 RSS에서 최신 AI 기사 가져오기
# ==========================================
def get_ai_news_feed():
    # 구글 뉴스 검색어: "인공지능 OR AI" (한국어)
    rss_url = "https://news.google.com/rss/search?q=인공지능+OR+AI&hl=ko&gl=KR&ceid=KR:ko"
    
    try:
        feed = feedparser.parse(rss_url)
        news_items = []
        
        # 최신 기사 5개만 가져오기
        for entry in feed.entries[:5]:
            title = entry.title
            link = entry.link
            published = entry.published
            news_items.append(f"- 제목: {title}\n- 링크: {link}\n- 발행일: {published}")
        
        if not news_items:
            return None
            
        return "\n\n".join(news_items)
    except Exception as e:
        print(f"RSS 파싱 에러: {e}")
        return None

# ==========================================
# [기능 2] GPT로 뉴스 브리핑 작성하기
# ==========================================
def summarize_news(news_data):
    if not OPENAI_API_KEY:
        return "⚠️ OpenAI API 키가 설정되지 않아 요약을 할 수 없습니다."

    client = OpenAI(api_key=OPENAI_API_KEY)
    
    prompt = f"""
    너는 IT 전문 기자이자 뉴스레터 에디터야.
    아래는 오늘 수집된 최신 AI 관련 뉴스 기사 목록이야.
    
    [작성 규칙]
    1. 인사말: "안녕하세요! 오늘의 AI 트렌드 브리핑입니다."로 시작.
    2. 요약: 각 기사의 핵심을 1줄로 요약하고, 바로 밑에 링크를 붙여줘.
    3. 스타일: 전문적이지만 읽기 쉽게 (이모지 활용).
    
    [기사 목록]
    {news_data}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # 가성비 모델
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"❌ GPT 요약 실패: {str(e)}"

# ==========================================
# [기능 3] 전송 (텔레그램, 메일)
# ==========================================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: 
        print("텔레그램 토큰이 없습니다.")
        return

    # 메시지 길이 제한 처리 (4096자)
    if len(message) > 4000:
        message = message[:4000] + "\n...(내용이 길어 생략됨)"
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {'chat_id': CHAT_ID, 'text': message} # 마크다운 제거 (에러 방지)
    
    try:
        requests.post(url, data=data)
        print(">> 텔레그램 전송 완료")
    except Exception as e:
        print(f">> 텔레그램 전송 실패: {e}")

def send_email(subject, body):
    if not EMAIL_USER or not EMAIL_PASSWORD: 
        print("이메일 설정이 없습니다.")
        return
        
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        smtp = smtplib.SMTP('smtp.gmail.com', 587)
        smtp.starttls()
        smtp.login(EMAIL_USER, EMAIL_PASSWORD)
        smtp.send_message(msg)
        smtp.quit()
        print(">> 이메일 전송 완료")
    except Exception as e:
        print(f">> 이메일 전송 실패: {e}")

# ==========================================
# [메인 실행]
# ==========================================
if __name__ == "__main__":
    print("📰 AI 뉴스 수집 봇 가동...")
    
    # 1. 뉴스 가져오기
    raw_news = get_ai_news_feed()
    
    if raw_news:
        print("기사 수집 완료. 요약 중...")
        
        # 2. GPT 요약
        summary_text = summarize_news(raw_news)
        
        today = datetime.now().strftime("%Y-%m-%d")
        final_msg = f"📰 [{today}] 오늘의 AI 뉴스\n\n{summary_text}"
        
        # 3. 전송
        send_telegram(final_msg)
        send_email(f"[{today}] 매일 아침 AI 뉴스 브리핑", final_msg)
        
        print("✅ 모든 작업 완료!")
    else:
        print("수집된 뉴스가 없거나 오류가 발생했습니다.")
