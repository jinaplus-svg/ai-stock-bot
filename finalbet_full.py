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
import feedparser  # 구글 뉴스 파싱용 (필수)
import urllib.parse

# =================================================
# [설정] 환경 변수 (보안)
# =================================================
# 텔레그램 및 이메일 설정
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
EMAIL_USER = os.environ.get('EMAIL_USER')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')

# Tavily는 이제 뉴스 검색에 쓰지 않으므로 삭제해도 됩니다.

SCAN_LIMIT = 100 

# =================================================
# 1. 뉴스 검색 함수 (구글 뉴스 RSS 활용)
# =================================================
def get_stock_news(stock_name):
    """
    구글 뉴스 RSS를 통해 '특징주' 뉴스를 크롤링합니다. (한국 전용)
    """
    try:
        # 검색어 URL 인코딩 (예: "삼성전자 특징주")
        query = urllib.parse.quote(f"{stock_name} 특징주")
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
        
        feed = feedparser.parse(rss_url)
        news_list = []
        
        # 최신 기사 2개만 추출
        for entry in feed.entries[:2]:
            news_list.append({
                'title': entry.title,
                'url': entry.link
            })
        return news_list
    except Exception as e:
        print(f"뉴스 검색 에러: {e}")
        return []

# =================================================
# 2. 알림 전송 함수
# =================================================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': message}
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
# 3. 데이터 분석 로직 (검증 기능 포함)
# =================================================
def get_trading_days():
    try:
        df = fdr.DataReader('005930', start=(datetime.now() - timedelta(days=20)))
        return df.index.tolist()
    except:
        return []

def analyze_candidates(target_date_str, verification_mode=False):
    """
    주식 후보 분석 및 검증 함수
    verification_mode=True: 추천일 다음날의 시가 수익률을 계산 (성적표용)
    """
    print(f"\n🔎 [{target_date_str}] 데이터 분석 중...", end="")
    try:
        df_krx = fdr.StockListing('KRX')
        cols = ['Close', 'Amount', 'ChagesRatio']
        for col in cols:
            if col in df_krx.columns:
                df_krx[col] = pd.to_numeric(df_krx[col], errors='coerce')
        df_krx.dropna(subset=cols, inplace=True)
        # 거래대금 상위 100개만 스캔
        df_krx = df_krx.sort_values(by='Amount', ascending=False).head(SCAN_LIMIT)
    except:
        return []

    candidates = []
    count = 0
    
    for idx, row in df_krx.iterrows():
        count += 1
        if count % 20 == 0: # 로그 너무 길지 않게
            sys.stdout.write(".")
            sys.stdout.flush()

        try:
            code = row['Code']
            name = row['Name']
            start_dt = (datetime.strptime(target_date_str, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
            df = fdr.DataReader(code, start=start_dt)
            
            if target_date_str not in df.index.strftime("%Y-%m-%d"): continue
            target_row = df.loc[target_date_str]
            target_idx = df.index.get_loc(target_date_str)
            
            if target_row['Close'] == 0: continue
            
            # --- [종가베팅 조건] ---
            # 1. 꽉찬 양봉 (윗꼬리 2.5% 이내)
            is_full_candle = (target_row['High'] - target_row['Close']) / target_row['Close'] <= 0.025
            # 2. 거래대금 100억 이상
            trade_amount = target_row['Close'] * target_row['Volume']
            is_big_money = trade_amount >= 10000000000
            # 3. 등락률 (5% 이상)
            if target_idx > 0:
                prev_close = df.iloc[target_idx - 1]['Close']
                change_rate = (target_row['Close'] - prev_close) / prev_close * 100
                is_strong = 5.0 <= change_rate < 29.5
            else: is_strong = False
            # 4. 정배열
            if len(df) >= 20:
                ma5 = df['Close'].iloc[target_idx-4 : target_idx+1].mean()
                ma20 = df['Close'].iloc[target_idx-19 : target_idx+1].mean()
                is_uptrend = (ma5 > ma20) and (target_row['Close'] >= ma5)
            else: is_uptrend = False

            if is_full_candle and is_big_money and is_strong and is_uptrend:
                result = {
                    '종목명': name,
                    '추천일_종가': int(target_row['Close']),
                    '추천일_등락률': round(change_rate, 2),
                    '거래대금': int(trade_amount / 100000000)
                }
                
                # [검증 모드] 다음날 시가 확인
                if verification_mode:
                    if len(df) > target_idx + 1:
                        next_day = df.iloc[target_idx + 1]
                        gap = (next_day['Open'] - target_row['Close']) / target_row['Close'] * 100
                        result['시가_수익률'] = round(gap, 2)
                    else:
                        result['시가_수익률'] = 0.0
                
                candidates.append(result)
        except: continue
            
    print(" 완료!")
    return candidates

# =================================================
# 4. 메인 실행
# =================================================
def main():
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_str = now_kst.strftime("%Y-%m-%d")
    
    dates = get_trading_days()
    if not dates: return
    dates.sort()

    # 오늘과 어제 날짜 확정
    today_real = dates[-1].strftime("%Y-%m-%d")
    yesterday_real = dates[-2].strftime("%Y-%m-%d")
    
    print(f"🚀 실행 날짜: {today_real} (어제: {yesterday_real})")

    # ------------------------------------------------
    # [1] 어제 추천주 성적표 작성
    # ------------------------------------------------
    msg = f"📊 [{today_real}] 종가베팅 성적표\n"
    msg += f"(기준: {yesterday_real} 종가매수 -> 오늘 시초가 매도)\n"
    msg += "-" * 25 + "\n"

    past_list = analyze_candidates(yesterday_real, verification_mode=True)
    
    if past_list:
        past_top5 = sorted(past_list, key=lambda x: x['추천일_등락률'], reverse=True)[:5]
        success_cnt = 0
        
        for item in past_top5:
            gap = item.get('시가_수익률', 0.0)
            emoji = "🔵" if gap > 0 else "🔴" # 수익이면 파랑, 손실이면 빨강
            msg += f"{emoji} {item['종목명']}: {gap:+}% \n"
            if gap > 0: success_cnt += 1
            
        win_rate = int(success_cnt / len(past_top5) * 100)
        msg += f"\n🏆 승률: {win_rate}% ({success_cnt}/{len(past_top5)})\n"
    else:
        msg += "어제는 추천 종목이 없었습니다.\n"
    
    msg += "\n" + "=" * 25 + "\n\n"

    # ------------------------------------------------
    # [2] 오늘 추천주 발굴 (구글 뉴스 포함)
    # ------------------------------------------------
    msg += "🔥 [오늘의 종베 Top 5]\n"
    msg += "-" * 25 + "\n"
    
    today_list = analyze_candidates(today_real, verification_mode=False)
    
    if today_list:
        today_top5 = sorted(today_list, key=lambda x: x['추천일_등락률'], reverse=True)[:5]
        
        for i, item in enumerate(today_top5):
            msg += f"{i+1}. {item['종목명']} (+{item['추천일_등락률']}%)\n"
            msg += f"   💰 {item['추천일_종가']:,}원 / {item['거래대금']}억\n"
            
            # 여기서 구글 뉴스 검색
            news = get_stock_news(item['종목명'])
            if news:
                for n in news:
                    msg += f"   📰 {n['title']}\n"
                    msg += f"   🔗 {n['url']}\n"
            else:
                msg += "   (관련 특이뉴스 없음)\n"
            msg += "\n"
    else:
        msg += "오늘은 쉴 때입니다. (조건 만족 종목 없음)\n"

    # ------------------------------------------------
    # [3] 결과 전송
    # ------------------------------------------------
    print(msg)
    send_telegram(msg)
    send_email(f"[{today_real}] 종가베팅 & 어제성적 리포트", msg)

if __name__ == "__main__":
    main()
