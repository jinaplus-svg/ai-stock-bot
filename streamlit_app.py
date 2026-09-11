# -*- coding: utf-8 -*-
"""파동 컨트롤 — 블로그/유튜브/자동매매 봇 현황 대시보드.
로컬 PC의 dashboard_sync.py가 주기적으로 GitHub에 올려두는 dashboard_status.json만 읽는다 —
이 앱 자체는 토스/구글 API 키를 전혀 갖고 있지 않다(보안: 실거래 계좌 접근권한이 클라우드에 없음)."""
import datetime

import requests
import streamlit as st

STATUS_URL = "https://raw.githubusercontent.com/jinaplus-svg/ai-stock-bot/main/dashboard_status.json"

st.set_page_config(page_title="파동 컨트롤", page_icon="📡", layout="wide")

st.markdown("""
<style>
  .block-container { padding-top: 2rem; max-width: 1080px; }
  [data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
  .row-title { font-weight: 500; }
  .row-sub { color: var(--text-color); opacity: 0.55; font-size: 0.8rem; }
  a.row-link { text-decoration: none; color: inherit; }
  .cat-badge {
    display: inline-block; font-size: 0.72rem; font-weight: 700;
    padding: 2px 8px; border-radius: 999px; background: rgba(47,111,176,0.12); color: #2f6fb0;
  }
  .pos-pill {
    display: inline-block; font-size: 0.78rem; padding: 4px 10px; margin: 3px 4px 3px 0;
    border-radius: 8px; background: rgba(120,120,120,0.10);
  }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_status():
    res = requests.get(STATUS_URL, timeout=15)
    res.raise_for_status()
    return res.json()


def fmt_krw(v):
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f}원"


def fmt_usdt(v):
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.2f} USDT"


try:
    data = load_status()
except Exception as e:
    st.error(f"상태 데이터를 불러오지 못했어요: {e}")
    st.stop()

updated_at = datetime.datetime.fromisoformat(data["updated_at"])
age_min = (datetime.datetime.now(updated_at.tzinfo) - updated_at).total_seconds() / 60

col_title, col_meta = st.columns([3, 1])
with col_title:
    st.title("📡 파동 컨트롤")
    st.caption("블로그 6개 · 생각의파동 채널 · 자동매매 봇 3개")
with col_meta:
    freshness = "🟢 최신" if age_min < 15 else ("🟡 갱신 지연" if age_min < 60 else "🔴 갱신 안 됨")
    st.markdown(f"**{freshness}**")
    st.caption(f"{updated_at.strftime('%m/%d %H:%M')} 기준 · {int(age_min)}분 전")

st.divider()

# ── 요약 ──────────────────────────────────────────
blogs = data.get("blogs", [])
today_str = datetime.datetime.now(updated_at.tzinfo).strftime("%m/%d")
posted_today = sum(1 for b in blogs if b.get("published_kst", "").startswith(today_str))

bots = data.get("bots", {})
toss30, toss1min, binance = bots.get("toss30", {}), bots.get("toss1min", {}), bots.get("binance", {})

c1, c2, c3, c4 = st.columns(4)
c1.metric("오늘 발행", f"{posted_today} / {len(blogs)}개 블로그")
top_video = data.get("youtube", [{}])[0]
c2.metric("생각의파동 최신 조회수", f"{top_video.get('views', '—'):,}회" if isinstance(top_video.get("views"), int) else "—",
          help=top_video.get("title"))
c3.metric("1분봇 연속손실", f"{toss1min.get('consecutive_losses', '—')} / 3회",
          delta="정지 임박" if (toss1min.get("consecutive_losses") or 0) >= 2 else None,
          delta_color="inverse")
bp = data.get("account", {}).get("buying_power")
c4.metric("계좌 매수가능금액", f"{bp:,.0f}원" if bp else "—", help="30분봇·1분봇 공유 계좌")

st.divider()

# ── 블로그 ──────────────────────────────────────────
st.subheader("블로그 자동화")
for b in blogs:
    if b.get("error"):
        st.warning(f"{b['category']}: 조회 실패 ({b['error'][:80]})")
        continue
    is_fresh = b.get("published_kst", "").startswith(today_str)
    cols = st.columns([1, 6, 2])
    cols[0].markdown(f"<span class='cat-badge'>{b['category']}</span>", unsafe_allow_html=True)
    cols[1].markdown(
        f"<a class='row-link' href='{b.get('url', '#')}' target='_blank'>"
        f"<span class='row-title'>{b.get('title') or '(글 없음)'}</span></a><br>"
        f"<span class='row-sub'>{b['domain']}</span>", unsafe_allow_html=True)
    when = b.get("published_kst", "—")
    cols[2].markdown(f"{'🟢 ' if is_fresh else ''}{when}")

st.divider()

# ── 유튜브 ──────────────────────────────────────────
st.subheader("생각의파동 · 유튜브")
for v in data.get("youtube", []):
    if v.get("error"):
        st.warning(f"조회 실패: {v['error'][:80]}")
        continue
    cols = st.columns([2, 6, 2])
    cols[0].markdown(f"<span class='row-sub'>{v.get('published_kst', '—')}</span>", unsafe_allow_html=True)
    video_url = f"https://youtu.be/{v.get('video_id', '')}"
    cols[1].markdown(
        f"<a class='row-link' href='{video_url}' target='_blank'>{v.get('title', '')}</a>",
        unsafe_allow_html=True)
    cols[2].markdown(f"**{v.get('views', 0):,}회**")

st.divider()

# ── 자동매매 ──────────────────────────────────────────
st.subheader("자동매매")
bcol1, bcol2, bcol3 = st.columns(3)

with bcol1:
    st.markdown("**토스 30분봇**")
    st.caption("gemini-3.7-flash · 10종목")
    st.metric(f"손익 ({toss30.get('date', '—')})", fmt_krw(toss30.get("daily_pnl")))
    st.metric("누적 손익", fmt_krw(toss30.get("cumulative_pnl")))
    st.caption(f"오늘 거래 {toss30.get('trade_count_today', '—')}회 · 연속손실 {toss30.get('consecutive_losses', '—')}회")
    if toss30.get("positions"):
        st.caption("보유 종목")
        for p in toss30["positions"]:
            st.markdown(f"<span class='pos-pill'>{p['name']} {p.get('qty', '?')}주</span>", unsafe_allow_html=True)
    else:
        st.caption("보유 없음")

with bcol2:
    st.markdown("**토스 1분봇**")
    st.caption("규칙기반 · 10종목")
    breaker = (toss1min.get("consecutive_losses") or 0) >= 3
    st.metric(f"손익 ({toss1min.get('date', '—')})", fmt_krw(toss1min.get("daily_pnl")))
    st.metric("누적 손익", fmt_krw(toss1min.get("cumulative_pnl")))
    st.caption(f"오늘 거래 {toss1min.get('trade_count_today', '—')}회 · 연속손실 {toss1min.get('consecutive_losses', '—')}회"
               + (" · 🛑 신규진입 정지" if breaker else ""))
    if toss1min.get("positions"):
        st.caption("보유 종목")
        for p in toss1min["positions"]:
            entry = p.get("entry_price")
            entry_str = f"@{entry:,.0f}" if isinstance(entry, (int, float)) else ""
            st.markdown(f"<span class='pos-pill'>{p['name']} {p.get('qty', '?')}주 {entry_str}</span>",
                        unsafe_allow_html=True)
    else:
        st.caption("보유 없음")

with bcol3:
    st.markdown("**바이낸스 테스트넷**")
    st.caption("BTC/USDT · 홀딩 상태")
    st.metric("테스트 기간 손익", fmt_usdt(binance.get("cumulative_pnl")))
    st.caption("실계좌 연동 대기 중 — 스케줄러 비활성화됨")

st.divider()
st.caption("500만원 계좌 · 토스 30분봇/1분봇 공유 · 이 페이지는 로컬 PC가 5~10분마다 갱신하는 상태 스냅샷을 읽어와요(실거래 API 키는 클라우드에 없음)")
