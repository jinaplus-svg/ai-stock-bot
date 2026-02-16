import streamlit as st
import pandas as pd
import requests
import xmltodict
import plotly.express as px
import yfinance as yf
from datetime import datetime

# ------------------------------------------------------------------------------
# 1. 초기 시스템 설정 및 공통 환경 변수
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Profit4Test Dashboard")

st.title("💰 Profit4Test: 통합 투자 분석 대시보드")
st.markdown("---")

# [보안] 파이썬 차단 우회를 위한 브라우저 위장 헤더 (캠코 가이드 반영)
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# Secrets 로드
try:
    PUBLIC_API_KEY = st.secrets["public_api"]["key"]
    st.sidebar.success("✅ 공공데이터 API 키가 로드되었습니다.")
except Exception:
    st.sidebar.error("❌ API 키를 찾을 수 없습니다.")
    st.sidebar.info("로컬 실행 시 .streamlit/secrets.toml 파일을 확인하세요.")
    PUBLIC_API_KEY = ""

tab1, tab2, tab3, tab4 = st.tabs(["🏛️ 온비드 공매", "📈 주식 퀀트", "🏢 아파트 실거래", "🚗 중고차 시세"])

# ------------------------------------------------------------------------------
# 2. [탭1] 온비드 공매 (금액 가독성 개선)
# ------------------------------------------------------------------------------
with tab1:
    st.header("캠코 공매 물건 조회")
    st.caption("온비드 오픈 API 공식 가이드(v1.3) 상세기능 명세 기준")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        # SIDO는 한글 명칭 전달 (가이드 문서 반영)
        region_map = {
            "서울": "서울특별시", "경기": "경기도", "인천": "인천광역시", 
            "부산": "부산광역시", "대구": "대구광역시", "대전": "대전광역시", "광주": "광주광역시"
        }
        selected_region = st.selectbox("공매 지역 선택", list(region_map.keys()), index=0)
        sido_name = region_map[selected_region]
    with col2:
        goods_type = st.selectbox("용도", ["부동산 (전체)", "아파트", "토지"])
    with col3:
        rows = st.number_input("조회 개수", min_value=1, max_value=50, value=10)

    if st.button("공매 물건 검색", key="btn_onbid"):
        if not PUBLIC_API_KEY:
            st.error("API 키가 없습니다.")
        else:
            url = "http://openapi.onbid.co.kr/openapi/services/KamcoPblsalThingInquireSvc/getKamcoPbctCltrList"
            params = {
                'serviceKey': PUBLIC_API_KEY,
                'pageNo': '1',
                'numOfRows': str(rows),
                'DPSL_MTD_CD': '0001',   # 필수: 매각
                'CTGR_HIRK_ID': '10000', # 부동산 카테고리
                'SIDO': sido_name
            }

            try:
                with st.spinner("데이터 로드 중..."):
                    response = requests.get(url, params=params, headers=COMMON_HEADERS)
                
                if response.status_code == 200:
                    data = xmltodict.parse(response.content)
                    if 'response' in data and 'body' in data['response']:
                        body = data['response']['body']
                        if body.get('items'):
                            items = body['items']['item']
                            if isinstance(items, dict): items = [items]
                            df = pd.DataFrame(items)
                            
                            # [금액 가독성 개선] 천 단위 콤마 추가
                            for col in ['MIN_BID_PRC', 'APSL_ASES_AVG_AMT']:
                                if col in df.columns:
                                    df[col] = pd.to_numeric(df[col]).apply(lambda x: f"{x:,.0f}원")
                            
                            cols_map = {
                                'CLTR_NM': '물건명',
                                'MIN_BID_PRC': '최저입찰가',
                                'APSL_ASES_AVG_AMT': '감정가',
                                'CTGR_FULL_NM': '용도',
                                'PBCT_BEGN_DTM': '입찰시작'
                            }
                            st.dataframe(df[[c for c in cols_map.keys() if c in df.columns]].rename(columns=cols_map), use_container_width=True)
                            st.success(f"조회 성공: {len(df)}건")
                        else:
                            st.warning("진행 중인 물건이 없습니다.")
            except Exception as e:
                st.error(f"오류: {e}")

# ------------------------------------------------------------------------------
# 3. [탭2] 주식 퀀트 (Yahoo Finance)
# ------------------------------------------------------------------------------
with tab2:
    st.header("📈 주식 기술적 분석 (RSI)")
    ticker = st.text_input("티커 입력 (예: 005930.KS, NVDA)", value="005930.KS")
    
    if ticker:
        stock = yf.Ticker(ticker)
        df_stock = stock.history(period="1y")
        
        if not df_stock.empty:
            # RSI 지표 계산
            delta = df_stock['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            df_stock['RSI'] = 100 - (100 / (1 + (gain / loss)))
            
            st.plotly_chart(px.line(df_stock, y='Close', title=f"{ticker} 주가 추이"), use_container_width=True)
            
            fig_rsi = px.line(df_stock, y='RSI', title="RSI (30 이하 매수 / 70 이상 매도)")
            fig_rsi.add_hline(y=30, line_color="green", line_dash="dash")
            fig_rsi.add_hline(y=70, line_color="red", line_dash="dash")
            st.plotly_chart(fig_rsi, use_container_width=True)
        else:
            st.warning("데이터를 불러올 수 없습니다.")

# ------------------------------------------------------------------------------
# 4. [탭3] 아파트 실거래가 (지역 선택 편의성 및 데이터 오류 수정)
# ------------------------------------------------------------------------------
with tab3:
    st.header("🏢 국토교통부 아파트 실거래가 조회")
    st.caption("지역명을 선택하면 법정동 코드가 자동으로 입력됩니다.")

    # 법정동 코드 자동 매핑 리스트
    gu_code_map = {
        "강남구": "11680", "서초구": "11650", "송파구": "11710", "용산구": "11170",
        "성동구": "11200", "마포구": "11440", "영등포구": "11560", "분당구": "41135",
        "과천시": "41150", "광명시": "41210", "시흥시": "41390", "직접 입력": ""
    }

    c1, c2, c3 = st.columns([1.5, 1, 1])
    with c1:
        selected_gu = st.selectbox("시/군/구 선택", list(gu_code_map.keys()))
    with c2:
        lawd_cd = st.text_input("법정동 코드 (5자리)", value=gu_code_map[selected_gu])
    with c3:
        # 전월 데이터를 기본값으로 설정
        deal_ymd = st.text_input("계약월 (YYYYMM)", value=datetime.now().strftime("%Y%m"))

    if st.button("실거래가 조회", key="btn_apt"):
        if not PUBLIC_API_KEY:
            st.error("API 키가 없습니다.")
        else:
            url = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
            params = {
                'serviceKey': PUBLIC_API_KEY,
                'LAWD_CD': lawd_cd,
                'DEAL_YMD': deal_ymd,
                'numOfRows': '100',
                'pageNo': '1'
            }
            
            try:
                with st.spinner(f"{selected_gu} 데이터 로드 중..."):
                    res = requests.get(url, params=params, headers=COMMON_HEADERS)
                
                if res.status_code == 200:
                    data = xmltodict.parse(res.content)
                    if 'response' in data and 'body' in data['response']:
                        body = data['response']['body']
                        if body.get('items') and body['items'].get('item'):
                            item_list = body['items']['item']
                            if isinstance(item_list, dict): item_list = [item_list]
                            df_apt = pd.DataFrame(item_list)
                            
                            # [데이터 오류 수정] 금액 전처리 및 정렬
                            if '거래금액' in df_apt.columns:
                                df_apt['금액_숫자'] = df_apt['거래금액'].str.replace(',', '').str.strip().astype(int)
                                df_apt = df_apt.sort_values('금액_숫자', ascending=False)
                                df_apt['거래금액'] = df_apt['금액_숫자'].apply(lambda x: f"{x:,.0f}만원")
                            
                            show_cols = ['아파트', '거래금액', '전용면적', '층', '일', '건축년도']
                            st.dataframe(df_apt[[c for c in show_cols if c in df_apt.columns]], use_container_width=True)
                            st.success(f"✅ {selected_gu} {len(df_apt)}건 조회 성공")
                        else:
                            st.warning("조회된 거래 내역이 없습니다.")
            except Exception as e:
                st.error(f"오류: {e}")

# ------------------------------------------------------------------------------
# 5. [탭4] 중고차 시세 (데모 분석)
# ------------------------------------------------------------------------------
with tab4:
    st.header("🚗 중고차 가치 평가 분석")
    target_car = st.text_input("분석 차종", value="포르쉐 911 카레라 GTS")
    
    # 가상 데이터 데모
    df_car = pd.DataFrame({
        '연식': [2021, 2022, 2023, 2024, 2022, 2021, 2023],
        '주행거리': [45000, 25000, 8000, 1500, 32000, 55000, 12000],
        '가격': [16800, 19200, 21800, 24500, 18500, 15500, 21000]
    })
    
    fig_car = px.scatter(df_car, x='주행거리', y='가격', color='연식', 
                         size='가격', trendline="ols", title=f"{target_car} 감가상각 분석")
    st.plotly_chart(fig_car, use_container_width=True)
    st.info("💡 추세선보다 아래에 있는 점이 동일 조건 대비 저렴한 매물입니다.")
