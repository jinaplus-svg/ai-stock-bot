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
# [설정] 환경 변수에서 비밀키 가져오기 (보안 필수)
# =================================================
TAVILY_API_KEY = os.environ.get('TAVILY_API_KEY')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
EMAIL_USER = os.environ.get('EMAIL_USER')        # 본인 구글 이메일
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD') # 구글 앱 비밀번호

SCAN_LIMIT = 100 

# =================================================
# [설정] 콘솔 출력용 색상 (텔레그램 전송시에는 이모지로 대체)
# =================================================
C_SUCCESS = "\033[94m" # 파랑
C_FAIL = "\033[91m"    # 빨강
C_RESET = "\033[0m"
C_BOLD = "\033[1m"

# =================================================
# 1. 알림 발송 함수 (텔레그램 + 이메일)
# =================================================
def send_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try:
        # 텔레그램 마크다운 등의 특수문자 충돌 방지를 위해 plain text로 전송하거나 예외처리
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
        msg['To'] = EMAIL_USER # 나에게 보내기
        msg['Subject'] = subject

        msg.attach(MIMEText(content, 'plain'))

        # 구글 SMTP 서버 연결
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
        print(">> 이메일 전송 완료")
    except Exception as e:
        print(f"이메일 전송 실패: {e}")

# =================================================
# 2. 데이터 및 뉴스 로직
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
        response = requests.post(url, json=payload, timeout=3)
        data = response.json()
        news_list = []
        if 'results' in data:
            for result in data['results']:
                title = result['title']
                if len(title) > 45: title = title[:45] + "..."
                news_list.append({'title': title, 'url': result['url']})
        return news_list
    except:
        return []

def get_trading_days():
    try:
        # 삼성전자 기준으로 최근 영업일 확보
        df = fdr.DataReader('005930', start=(datetime.now() - timedelta(days=20)))
        return df.index.tolist()
    except:
        return []

def analyze_candidates(target_date_str, verification_mode=False):
    """
    verification_mode=True일 경우:
    target_date(추천일) 다음날의 시가(Open)를 확인하여 수익률을 계산함
    """
    print(f"\n🔎 [{target_date_str}] 데이터 분석 중...", end="")
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
    total = len(df_krx)
    count = 0
    
    for idx, row in df_krx.iterrows():
        count += 1
        # 깃허브 액션 로그가 너무 길어지지 않게 10개 단위로만 점 찍기
        if count % 10 == 0:
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
            
            # --- [조건 체크] ---
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
                result_dict = {
                    '종목명': name,
                    '추천일_종가': int(target_row['Close']),
                    '추천일_등락률': round(change_rate, 2),
                    '거래대금': int(trade_amount / 100000000)
                }

                # [검증 모드] 추천일 다음날(즉, 오늘) 시가 수익률 확인
                if verification_mode:
                    # 데이터 프레임에 다음날 데이터가 있어야 함
                    if len(df) > target_idx + 1:
                        next_day_row = df.iloc[target_idx + 1]
                        gap_return = (next_day_row['Open'] - target_row['Close']) / target_row['Close'] * 100
                        result_dict['시가_수익률'] = round(gap_return, 2)
                    else:
                        result_dict['시가_수익률'] = 0.0 # 데이터 아직 없음

                candidates.append(result_dict)
        except: continue
            
    print(" 완료!")
    return candidates

# =================================================
# 3. 메인 실행
# =================================================
def main():
    # 깃허브 서버(UTC) -> 한국 시간(KST)
    now_kst = datetime.utcnow() + timedelta(hours=9)
    today_str = now_kst.strftime("%Y-%m-%d")
    
    dates = get_trading_days()
    if not dates: 
        print("장 운영일 정보를 가져올 수 없습니다.")
        return

    dates.sort()
    # 최근 거래일(오늘)과 그 전 거래일(어제) 구하기
    # (만약 오늘이 장날이 아니면 가장 최근 장날이 today로 잡힙니다)
    today_date = dates[-1]
    yesterday_date = dates[-2]

    today_str_real = today_date.strftime("%Y-%m-%d")
    yesterday_str_real = yesterday_date.strftime("%Y-%m-%d")

    print(f"🚀 분석 시작 (Today: {today_str_real}, Yesterday: {yesterday_str_real})")
    
    # -----------------------------------------------------
    # [1] 어제(Top 5) 추천 종목 성적표 확인
    # -----------------------------------------------------
    msg = f"📅 [{today_str_real}] 종가 베팅 리포트\n\n"
    msg += "📊 [어제 Top 5 성적표]\n"
    msg += f"(기준: {yesterday_str_real} 종가매수 -> 오늘 시초가 매도)\n"
    msg += "-" * 30 + "\n"

    # 어제 날짜로 분석을 다시 돌려서 후보를 뽑고, 오늘 시가와 비교
    past_candidates = analyze_candidates(yesterday_str_real, verification_mode=True)
    
    if past_candidates:
        # 어제 추천순위와 똑같이 '등락률' 순으로 정렬 후 상위 5개 추출
        past_top5 = sorted(past_candidates, key=lambda x: x['추천일_등락률'], reverse=True)[:5]
        
        success_cnt = 0
        for item in past_top5:
            gap = item.get('시가_수익률', 0.0)
            # 이모지 처리 (성공=파랑, 실패=빨강)
            emoji = "🔵" if gap > 0 else "🔴"
            msg += f"{emoji} {item['종목명']}: {gap:+}% \n"
            if gap > 0: success_cnt += 1
        
        win_rate = int((success_cnt / len(past_top5)) * 100)
        msg += f"\n🏆 승률: {win_rate}% ({success_cnt}/{len(past_top5)})\n"
    else:
        msg += "데이터 부족으로 검증 불가\n"

    msg += "\n" + "=" * 30 + "\n\n"

    # -----------------------------------------------------
    # [2] 오늘(Top 5) 강력 매수 추천
    # -----------------------------------------------------
    msg += "🔥 [오늘의 종베 Top 5]\n"
    msg += "-" * 30 + "\n"
    
    today_candidates = analyze_candidates(today_str_real, verification_mode=False)

    if today_candidates:
        # 등락률 순 정렬 (가장 힘 쎈 놈이 1등)
        top_list = sorted(today_candidates, key=lambda x: x['추천일_등락률'], reverse=True)[:5]
        
        for i, item in enumerate(top_list):
            rank = i + 1
            msg += f"{rank}. {item['종목명']} (+{item['추천일_등락률']}%)\n"
            msg += f"   💰 {item['추천일_종가']:,}원 / {item['거래대금']}억\n"
            
            # 뉴스 검색
            news_items = get_stock_news(item['종목명'])
            if news_items:
                for n in news_items:
                    msg += f"   📰 {n['title']}\n"
                    msg += f"   🔗 {n['url']}\n"
            msg += "\n"
    else:
        msg += "오늘은 조건에 맞는 종목이 없습니다. (휴식 권장)\n"

    # -----------------------------------------------------
    # [3] 결과 전송
    # -----------------------------------------------------
    print("\n[생성된 메시지 미리보기]")
    print(msg)
    
    print("\n>> 텔레그램 전송 중...")
    send_telegram(msg)
    
    print(">> 이메일 전송 중...")
    send_email(f"[{today_str_real}] 종가베팅 분석 리포트", msg)
    
    print("✅ 모든 작업 완료!")

if __name__ == "__main__":
    main()
