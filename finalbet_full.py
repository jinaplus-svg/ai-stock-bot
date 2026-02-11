import FinanceDataReader as fdr
import pandas as pd
from datetime import datetime, timedelta
import time
import sys
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# =================================================
# [설정] 환경 변수에서 비밀키 가져오기
# =================================================
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
EMAIL_USER = os.environ.get('EMAIL_USER')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')

SCAN_LIMIT = 100 

# =================================================
# 1. 알림 발송 함수
# =================================================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
        requests.post(url, data=data)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

def send_email(subject, content):
    if not EMAIL_USER or not EMAIL_PASSWORD: return
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = EMAIL_USER 
        msg['Subject'] = subject
        msg.attach(MIMEText(content, 'plain'))

        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
        print(">> 이메일 전송 완료")
    except Exception as e:
        print(f"이메일 전송 실패: {e}")

# =================================================
# 2. 분석 및 뉴스 로직
# =================================================
def get_stock_news(stock_name):
    if not TAVILY_API_KEY: return []
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY,
        "query": f"{stock_name} 특징주", 
        "search_depth": "basic",
        "topic": "news",
        "max_results": 2,
        "include_domains": ["naver.com", "hankyung.com", "mk.co.kr", "edaily.co.kr"] 
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        data = response.json()
        news_list = []
        if 'results' in data:
            for result in data['results']:
                news_list.append({'title': result['title'], 'url': result['url']})
        return news_list
    except:
        return []

def get_trading_days():
    try:
        df = fdr.DataReader('005930', start=(datetime.now() - timedelta(days=20)))
        return df.index.tolist()
    except:
        return []

def analyze_candidates(target_date_str):
    print(f"🔎 [{target_date_str}] 데이터 분석 시작...")
    try:
        df_krx = fdr.StockListing('KRX')
        cols = ['Close', 'Amount', 'ChagesRatio']
        for col in cols:
            if col in df_krx.columns:
                df_krx[col] = pd.to_numeric(df_krx[col], errors='coerce')
        df_krx.dropna(subset=cols, inplace=True)
        df_krx = df_krx.sort_values(by='Amount', ascending=False).head(SCAN_LIMIT)
    except:
        return []

    candidates = []
    
    for idx, row in df_krx.iterrows():
        try:
            code = row['Code']
            name = row['Name']
            start_dt = (datetime.strptime(target_date_str, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
            df = fdr.DataReader(code, start=start_dt)
            
            if target_date_str not in df.index.strftime("%Y-%m-%d"): continue
            target_row = df.loc[target_date_str]
            target_idx = df.index.get_loc(target_date_str)
            
            if target_row['Close'] == 0: continue
            
            is_full_candle = (target_row['High'] - target_row['Close']) / target_row['Close'] <= 0.025
            trade_amount = target_row['Close'] * target_row['Volume']
            is_big_money = trade_amount >= 10000000000
            
            if target_idx > 0:
                prev_close = df.iloc[target_idx - 1]['Close']
                change_rate = (target_row['Close'] - prev_close) / prev_close * 100
                is_strong = 5.0 <= change_rate < 29.5
            else: is_strong = False

            if len(df) >= 20:
                ma5 = df['Close'].iloc[target_idx-4 : target_idx+1].mean()
                ma20 = df['Close'].iloc[target_idx-19 : target_idx+1].mean()
                is_uptrend = (ma5 > ma20) and (target_row['Close'] >= ma5)
            else: is_uptrend = False

            if is_full_candle and is_big_money and is_strong and is_uptrend:
                candidates.append({
                    '종목명': name,
                    '현재가': int(target_row['Close']),
                    '등락률': round(change_rate, 2),
                    '거래대금': int(trade_amount / 100000000)
                })
        except: continue
            
    return candidates

# =================================================
# 3. 메인 실행
# =================================================
def main():
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_str = now_kst.strftime("%Y-%m-%d")
    
    dates = get_trading_days()
    if not dates: return

    print(f"🚀 분석 시작 (Today: {today_str})")
    
    results = analyze_candidates(today_str)
    
    msg = f"🚀 [{today_str}] 종가 베팅 Top 5\n"
    msg += "=" * 30 + "\n\n"

    if results:
        top_list = sorted(results, key=lambda x: x['등락률'], reverse=True)[:5]
        
        for i, item in enumerate(top_list):
            rank = i + 1
            msg += f"{rank}. {item['종목명']} (+{item['등락률']}%)\n"
            msg += f"   💰 {item['현재가']:,}원 / {item['거래대금']}억\n"
            
            news_items = get_stock_news(item['종목명'])
            if news_items:
                for n in news_items:
                    msg += f"   📰 {n['title']}\n   🔗 {n['url']}\n"
            msg += "\n"
    else:
        msg += "오늘은 조건에 맞는 종목이 없습니다.\n"

    print(msg)
    
    send_telegram(msg)
    send_email(f"[{today_str}] 종가베팅 추천 리포트", msg)

if __name__ == "__main__":
    main()
