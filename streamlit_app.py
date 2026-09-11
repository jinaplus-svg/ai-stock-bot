# -*- coding: utf-8 -*-
"""파동 컨트롤 — 블로그/유튜브/자동매매 봇 현황 대시보드.
로컬 PC의 dashboard_sync.py가 주기적으로 GitHub에 올려두는 dashboard_status.json / dashboard_history.json만
읽는다 — 이 앱 자체는 토스/구글 API 키를 전혀 갖고 있지 않다(보안: 실거래 계좌 접근권한이 클라우드에 없음)."""
import datetime

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

REPO_RAW = "https://raw.githubusercontent.com/jinaplus-svg/ai-stock-bot/main"
STATUS_URL = f"{REPO_RAW}/dashboard_status.json"
HISTORY_URL = f"{REPO_RAW}/dashboard_history.json"

ACCENT = "#2f6fb0"
GOOD = "#2e9e5b"
BAD = "#c0392b"

st.set_page_config(page_title="파동 컨트롤", page_icon="📡", layout="wide")

st.markdown("""
<style>
  .block-container { padding-top: 2rem; max-width: 1100px; }
  [data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
  [data-testid="stMetric"] {
    background: rgba(120,120,120,0.06); border-radius: 12px; padding: 14px 16px;
    border: 1px solid rgba(120,120,120,0.12);
  }
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
  .bot-card {
    border: 1px solid rgba(120,120,120,0.15); border-radius: 14px; padding: 16px 18px;
    height: 100%;
  }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_status():
    res = requests.get(STATUS_URL, timeout=15)
    res.raise_for_status()
    return res.json()


@st.cache_data(ttl=60)
def load_history():
    res = requests.get(HISTORY_URL, timeout=15)
    if res.status_code != 200:
        return pd.DataFrame()
    rows = res.json()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"])
    return df.sort_values("ts")


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


def pnl_color(v):
    if v is None:
        return "var(--text-color)"
    return GOOD if v >= 0 else BAD


def line_chart(df, y_cols, names, colors, y_suffix="", height=260):
    fig = go.Figure()
    for col, name, color in zip(y_cols, names, colors):
        if col not in df.columns:
            continue
        sub = df.dropna(subset=[col])
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["ts"], y=sub[col], name=name, mode="lines",
            line=dict(color=color, width=2.2),
            hovertemplate="%{y:,.0f}" + y_suffix + "<br>%{x|%m/%d %H:%M}<extra>" + name + "</extra>",
        ))
    fig.update_layout(
        height=height, margin=dict(l=0, r=10, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(120,120,120,0.15)", tickformat=","),
        font=dict(color="var(--text-color)"),
        hovermode="x unified",
    )
    return fig


try:
    data = load_status()
except Exception as e:
    st.error(f"상태 데이터를 불러오지 못했어요: {e}")
    st.stop()

history = load_history()

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

# ── 총자산 (현금 + 주식 평가금액) ──────────────────────────────
account = data.get("account", {})
cash = account.get("buying_power")
stock_value = account.get("stock_value_krw")
total_value = account.get("total_value_krw")
unrealized = account.get("unrealized_pnl_krw")

st.subheader("💰 총자산")
a1, a2, a3, a4 = st.columns(4)
a1.metric("총자산 (현금 + 주식)", f"{total_value:,.0f}원" if total_value is not None else "—")
a2.metric("현금 (매수가능금액)", f"{cash:,.0f}원" if cash is not None else "—")
a3.metric("주식 평가금액", f"{stock_value:,.0f}원" if stock_value is not None else "—")
a4.metric("평가손익 (미실현)", fmt_krw(unrealized) if unrealized is not None else "—")

if not history.empty and "total_value_krw" in history.columns:
    st.plotly_chart(
        line_chart(history, ["total_value_krw"], ["총자산"], [ACCENT], height=220),
        use_container_width=True, config={"displayModeBar": False},
    )
else:
    st.caption("추세 그래프는 데이터가 쌓이는 대로(10분 간격) 표시돼요.")

st.divider()

tab_summary, tab_blog, tab_yt, tab_bots = st.tabs(["📋 요약", "✍️ 블로그", "🎬 유튜브", "🤖 자동매매"])

# ── 요약 탭 ──────────────────────────────────────────
with tab_summary:
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
    c3.metric("1분봇 연속손실", f"{toss1min.get('consecutive_losses', '—')} / 5회",
              delta="정지 임박" if (toss1min.get("consecutive_losses") or 0) >= 3 else None,
              delta_color="inverse")
    c4.metric("오늘 봇 손익 합계", fmt_krw((toss30.get("daily_pnl") or 0) + (toss1min.get("daily_pnl") or 0)))

    st.markdown("##### 봇별 누적손익 추세 (KRW)")
    if not history.empty:
        st.plotly_chart(
            line_chart(history, ["cum_pnl_toss30", "cum_pnl_toss1min"], ["30분봇", "1분봇"],
                       [ACCENT, "#e0824c"], height=240),
            use_container_width=True, config={"displayModeBar": False},
        )
    else:
        st.caption("데이터가 쌓이는 대로 표시돼요.")

# ── 블로그 탭 ──────────────────────────────────────────
with tab_blog:
    blogs = data.get("blogs", [])
    today_str = datetime.datetime.now(updated_at.tzinfo).strftime("%m/%d")
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

# ── 유튜브 탭 ──────────────────────────────────────────
with tab_yt:
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

# ── 자동매매 탭 ──────────────────────────────────────────
with tab_bots:
    bots = data.get("bots", {})
    toss30, toss1min, binance = bots.get("toss30", {}), bots.get("toss1min", {}), bots.get("binance", {})

    bcol1, bcol2, bcol3 = st.columns(3)

    with bcol1:
        st.markdown("<div class='bot-card'>", unsafe_allow_html=True)
        st.markdown("**토스 30분봇**")
        st.caption("gemini-3.7-flash(폴백 3.5) · 10종목")
        st.metric(f"손익 ({toss30.get('date', '—')})", fmt_krw(toss30.get("daily_pnl")))
        st.metric("누적 손익", fmt_krw(toss30.get("cumulative_pnl")))
        st.caption(f"오늘 거래 {toss30.get('trade_count_today', '—')}회 · 연속손실 {toss30.get('consecutive_losses', '—')}회")
        if toss30.get("positions"):
            st.caption("보유 종목")
            for p in toss30["positions"]:
                pnl = p.get("unrealized_pnl")
                pnl_str = f" ({pnl:+,.0f})" if isinstance(pnl, (int, float)) else ""
                st.markdown(f"<span class='pos-pill'>{p['name']} {p.get('qty', '?')}주{pnl_str}</span>",
                            unsafe_allow_html=True)
        else:
            st.caption("보유 없음")
        st.markdown("</div>", unsafe_allow_html=True)

    with bcol2:
        st.markdown("<div class='bot-card'>", unsafe_allow_html=True)
        st.markdown("**토스 1분봇**")
        st.caption("규칙기반(모멘텀+거래량+RSI) · 10종목")
        breaker = (toss1min.get("consecutive_losses") or 0) >= 5
        st.metric(f"손익 ({toss1min.get('date', '—')})", fmt_krw(toss1min.get("daily_pnl")))
        st.metric("누적 손익", fmt_krw(toss1min.get("cumulative_pnl")))
        st.caption(f"오늘 거래 {toss1min.get('trade_count_today', '—')}회 · 연속손실 {toss1min.get('consecutive_losses', '—')}/5회"
                   + (" · 🛑 신규진입 정지" if breaker else ""))
        if toss1min.get("positions"):
            st.caption("보유 종목")
            for p in toss1min["positions"]:
                entry = p.get("entry_price")
                entry_str = f"@{entry:,.0f}" if isinstance(entry, (int, float)) else ""
                pnl = p.get("unrealized_pnl")
                pnl_str = f" ({pnl:+,.0f})" if isinstance(pnl, (int, float)) else ""
                st.markdown(f"<span class='pos-pill'>{p['name']} {p.get('qty', '?')}주 {entry_str}{pnl_str}</span>",
                            unsafe_allow_html=True)
        else:
            st.caption("보유 없음")
        st.markdown("</div>", unsafe_allow_html=True)

    with bcol3:
        st.markdown("<div class='bot-card'>", unsafe_allow_html=True)
        st.markdown("**바이낸스 테스트넷**")
        st.caption("BTC/USDT · 홀딩 상태")
        st.metric("테스트 기간 손익", fmt_usdt(binance.get("cumulative_pnl")))
        st.caption("실계좌 연동 대기 중 — 스케줄러 비활성화됨")
        if not history.empty and "cum_pnl_binance_usdt" in history.columns:
            st.plotly_chart(
                line_chart(history, ["cum_pnl_binance_usdt"], ["누적손익"], ["#7d5ba6"], height=140),
                use_container_width=True, config={"displayModeBar": False},
            )
        st.markdown("</div>", unsafe_allow_html=True)

st.divider()
st.caption("500만원 계좌 · 토스 30분봇/1분봇 공유 · 이 페이지는 로컬 PC가 10분마다 갱신하는 상태 스냅샷을 읽어와요(실거래 API 키는 클라우드에 없음)")
