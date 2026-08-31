import os
import sys
import json
import time
import hmac
import hashlib
import requests
import datetime
from openai import OpenAI

# ==========================================
# 설정
# ==========================================
BINANCE_API_KEY = os.environ.get("BINANCE_TESTNET_API_KEY")
BINANCE_SECRET_KEY = os.environ.get("BINANCE_TESTNET_SECRET_KEY")
BINANCE_BASE = "https://testnet.binance.vision"  # [테스트넷] 실자금 전환 전까지는 이 도메인만 사용

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

SYMBOL = "BTCUSDT"
BASE_ASSET = "BTC"
QUOTE_ASSET = "USDT"

# 🚨 안전장치 — GPT의 판단과 무관하게 코드 레벨에서 강제
MAX_TRADE_USDT = 50.0          # 1회 최대 매수/매도 금액
DAILY_LOSS_LIMIT_USDT = 100.0  # 하루 누적 손실 한도 (넘으면 그날은 거래 중단)

STATE_FILE = "trading_state.json"

gpt_client = OpenAI(api_key=OPENAI_API_KEY)


def send_telegram(text):
    if not (TELEGRAM_TOKEN and CHAT_ID):
        print("(텔레그램 미설정, 콘솔에만 출력)\n" + text)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(f"⚠️ 텔레그램 알림 실패: {e}")


# ==========================================
# 1. 상태 저장/로드 — 일일 손실 한도 추적용 (GH Actions는 매번 새 컨테이너라 파일로 영속화)
# ==========================================
def load_state():
    default = {"date": "", "daily_pnl_usdt": 0.0, "trade_count_today": 0, "history": []}
    if not os.path.exists(STATE_FILE):
        return default
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        return default

    kst = datetime.timezone(datetime.timedelta(hours=9))
    today_str = datetime.datetime.now(kst).strftime("%Y-%m-%d")
    if state.get("date") != today_str:
        # 날짜 바뀌면 일일 손실 카운터 리셋 (거래 이력은 최근 30개만 유지)
        state = {"date": today_str, "daily_pnl_usdt": 0.0, "trade_count_today": 0,
                  "history": state.get("history", [])[-30:]}
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ==========================================
# 2. 바이낸스 API (테스트넷)
# ==========================================
def _sign(query):
    return hmac.new(BINANCE_SECRET_KEY.encode(), query.encode(), hashlib.sha256).hexdigest()


def _signed_request(method, path, params=None):
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10000
    query = "&".join(f"{k}={v}" for k, v in params.items())
    query += f"&signature={_sign(query)}"
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}
    url = f"{BINANCE_BASE}{path}?{query}"
    res = requests.post(url, headers=headers, timeout=15) if method == "POST" else requests.get(url, headers=headers, timeout=15)
    res.raise_for_status()
    return res.json()


def get_account_balances():
    data = _signed_request("GET", "/api/v3/account")
    balances = {b["asset"]: float(b["free"]) for b in data.get("balances", [])}
    return balances


def get_klines(symbol=SYMBOL, interval="1h", limit=24):
    """최근 N개 캔들 (공개 API, 인증 불필요)"""
    res = requests.get(f"{BINANCE_BASE}/api/v3/klines",
                        params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
    res.raise_for_status()
    return res.json()  # [[open_time, open, high, low, close, volume, ...], ...]


def get_symbol_filters(symbol=SYMBOL):
    res = requests.get(f"{BINANCE_BASE}/api/v3/exchangeInfo", params={"symbol": symbol}, timeout=15)
    res.raise_for_status()
    info = res.json()["symbols"][0]
    filters = {f["filterType"]: f for f in info["filters"]}
    step_size = float(filters.get("LOT_SIZE", {}).get("stepSize", "0.00001"))
    min_notional = float(filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {})).get("minNotional", "5"))
    return step_size, min_notional


def round_step(quantity, step_size):
    """[FIX] step_size가 1e-05 같은 과학적 표기일 때 문자열 기반 소수점 자릿수 계산이 깨지는 문제가 있어
    Decimal로 바꿔서 부동소수점 오차 없이 정확히 내림 처리."""
    from decimal import Decimal, ROUND_DOWN
    step = Decimal(str(step_size))
    qty = Decimal(str(quantity))
    if step == 0:
        return quantity
    steps = (qty / step).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * step)


def place_market_order(side, quote_usdt_amount, last_price):
    """side: 'BUY' or 'SELL'. quote_usdt_amount 기준으로 수량을 계산해서 시장가 주문."""
    step_size, min_notional = get_symbol_filters(SYMBOL)
    if quote_usdt_amount < min_notional:
        raise ValueError(f"주문 금액({quote_usdt_amount})이 최소 주문금액({min_notional})보다 작음")

    if side == "BUY":
        # 매수는 quoteOrderQty로 바로 지정 가능 (수량 계산 불필요)
        return _signed_request("POST", "/api/v3/order", {
            "symbol": SYMBOL, "side": "BUY", "type": "MARKET", "quoteOrderQty": round(quote_usdt_amount, 2)
        })
    else:
        # 매도는 base asset 수량을 stepSize에 맞춰 반올림해서 지정
        qty = round_step(quote_usdt_amount / last_price, step_size)
        if qty <= 0:
            raise ValueError("매도 가능 수량이 0 이하")
        return _signed_request("POST", "/api/v3/order", {
            "symbol": SYMBOL, "side": "SELL", "type": "MARKET", "quantity": qty
        })


# ==========================================
# 3. 신호 수집 — 가격 패턴 + 시장 뉴스
# ==========================================
def analyze_price_pattern(klines):
    closes = [float(k[4]) for k in klines]
    if len(closes) < 6:
        return {"trend": "unknown", "change_pct": 0.0, "last_price": closes[-1] if closes else 0}
    short_ma = sum(closes[-6:]) / 6
    long_ma = sum(closes) / len(closes)
    change_pct = (closes[-1] - closes[0]) / closes[0] * 100
    trend = "상승" if short_ma > long_ma else "하락" if short_ma < long_ma else "횡보"
    return {"trend": trend, "change_pct": round(change_pct, 2), "last_price": closes[-1],
            "short_ma": round(short_ma, 2), "long_ma": round(long_ma, 2)}


def fetch_market_news():
    if not TAVILY_API_KEY:
        return ""
    try:
        payload = {"api_key": TAVILY_API_KEY, "query": "비트코인 BTC 오늘 시황 뉴스",
                   "search_depth": "basic", "include_raw_content": False, "max_results": 3,
                   "topic": "news", "days": 1}
        res = requests.post("https://api.tavily.com/search", json=payload, timeout=15)
        if res.status_code == 200:
            results = res.json().get("results", [])
            return "\n".join(f"- {r.get('title')}: {r.get('content', '')[:200]}" for r in results)
    except Exception as e:
        print(f"⚠️ 뉴스 수집 실패: {e}")
    return ""


# ==========================================
# 4. 매매 판단 (GPT) — 판단은 GPT, 최종 리스크 강제는 코드
# ==========================================
def decide_trade(pattern, news, balances, state):
    prompt = f"""
    당신은 신중한 암호화폐 단기 트레이더입니다. 아래 정보를 보고 BUY/SELL/HOLD 중 하나만 판단하세요.

    [가격 패턴 - 최근 24시간, 1시간봉]
    추세: {pattern['trend']}, 구간 변동률: {pattern['change_pct']}%, 현재가: {pattern['last_price']} USDT
    단기이평(6h): {pattern.get('short_ma')}, 장기이평(24h): {pattern.get('long_ma')}

    [오늘의 시장 뉴스]
    {news or '뉴스 없음'}

    [현재 보유]
    USDT: {balances.get('USDT', 0):.2f}, BTC: {balances.get('BTC', 0):.6f}

    [오늘 누적 손익]
    {state['daily_pnl_usdt']:.2f} USDT (오늘 {state['trade_count_today']}회 거래함)

    반드시 아래 JSON 형식으로만 답하세요:
    {{"action": "BUY|SELL|HOLD", "reason": "한 문장 이유"}}
    """
    res = gpt_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    text = res.choices[0].message.content.strip()
    text = text.strip("`").replace("json", "", 1).strip() if text.startswith("```") else text
    try:
        return json.loads(text)
    except Exception:
        return {"action": "HOLD", "reason": f"응답 파싱 실패: {text[:200]}"}


# ==========================================
# 메인
# ==========================================
def main():
    state = load_state()

    if state["daily_pnl_usdt"] <= -DAILY_LOSS_LIMIT_USDT:
        send_telegram(f"🛑 [트레이딩봇] 오늘 손실 한도(-{DAILY_LOSS_LIMIT_USDT} USDT) 도달 — 거래를 중단합니다.\n"
                       f"현재 손익: {state['daily_pnl_usdt']:.2f} USDT")
        save_state(state)
        return

    balances = get_account_balances()
    klines = get_klines()
    pattern = analyze_price_pattern(klines)
    news = fetch_market_news()

    decision = decide_trade(pattern, news, balances, state)
    action = decision.get("action", "HOLD").upper()
    reason = decision.get("reason", "")

    log = f"🤖 [트레이딩봇] {SYMBOL} 판단: {action}\n📊 추세: {pattern['trend']} ({pattern['change_pct']}%) / 현재가 {pattern['last_price']}\n💬 사유: {reason}"

    if action == "HOLD":
        send_telegram(log + "\n\n⏸ 이번 시간엔 관망합니다.")
        save_state(state)
        return

    trade_amount = min(MAX_TRADE_USDT, balances.get("USDT", 0) if action == "BUY" else MAX_TRADE_USDT)

    if action == "BUY" and balances.get("USDT", 0) < 10:
        send_telegram(log + "\n\n⚠️ USDT 잔고 부족으로 매수 보류")
        save_state(state)
        return
    if action == "SELL" and balances.get("BTC", 0) * pattern["last_price"] < 10:
        send_telegram(log + "\n\n⚠️ BTC 보유량 부족으로 매도 보류")
        save_state(state)
        return

    try:
        order = place_market_order(action, trade_amount, pattern["last_price"])
        filled_qty = float(order.get("executedQty", 0))
        filled_quote = float(order.get("cummulativeQuoteQty", 0))
        state["trade_count_today"] += 1
        state["history"].append({
            "time": datetime.datetime.utcnow().isoformat(), "action": action,
            "qty": filled_qty, "quote": filled_quote, "reason": reason
        })
        send_telegram(log + f"\n\n✅ 체결 완료: {action} {filled_qty} {BASE_ASSET} (약 {filled_quote:.2f} {QUOTE_ASSET})")
    except Exception as e:
        send_telegram(log + f"\n\n❌ 주문 실패: {e}")

    save_state(state)


if __name__ == "__main__":
    main()
