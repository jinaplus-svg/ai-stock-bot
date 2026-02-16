import streamlit as st
import pandas as pd
import requests
import xmltodict
import plotly.express as px
import yfinance as yf
from datetime import datetime

# ------------------------------------------------------------------------------
# 1. 시스템 설정 및 공통 환경 변수
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Profit4Test Dashboard")

st.title("💰 Profit4Test: 통합 투자 분석 대시보드")
st.markdown("---")

# 파이썬 차단 우회를 위한 브라우저 위장 헤더
COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# Secrets 로드
try:
    PUBLIC_API_KEY = st.secrets["public_api"]["key"]
    st.sidebar.success("✅ 공공데이터 API 키가 로드되었습니다.")
except Exception:
    st.sidebar.error("❌ API 키를 찾을 수 없습니다.")
    PUBLIC_API_KEY = ""

tab1, tab2, tab3, tab4 = st.tabs(["🏛️ 온비드 공매", "📈 주식 퀀트", "🏢 아파트 실거래", "🚗 중고차 시세"])

# ------------------------------------------------------------------------------
# 2. [탭1] 온비드 공매 (금액 가독성: 천 단위 콤마 추가)
# ------------------------------------------------------------------------------
with tab1:
    st.header("캠코 공매 물건 조회")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        region_map = {"서울": "서울특별시", "경기": "경기도", "인천": "인천광역시", "부산": "부산광역시"}
        selected_region = st.selectbox("공매 지역", list(region_map.keys()), index=0)
        sido_name = region_map[selected_region]
    with col2:
        goods_type = st.selectbox("물건 용도", ["부동산 (전체)", "아파트", "토지"])
    with col3:
        rows = st.number_input("조회 개수 ", min_value=1, max_value=50, value=10)

    if st.button("공매 물건 검색", key="btn_onbid"):
        url = "http://openapi.onbid.co.kr/openapi/services/KamcoPblsalThingInquireSvc/getKamcoPbctCltrList"
        params = {
            'serviceKey': PUBLIC_API_KEY,
            'pageNo': '1', 'numOfRows': str(rows),
            'DPSL_MTD_CD': '0001', 'CTGR_HIRK_ID': '10000', 'SIDO': sido_name
        }

        try:
            with st.spinner("데이터 로드 중..."):
                response = requests.get(url, params=params, headers=COMMON_HEADERS)
            if response.status_code == 200:
                data = xmltodict.parse(response.content)
                items = data.get('response', {}).get('body', {}).get('items', {}).get('item')
                if items:
                    if isinstance(items, dict): items = [items]
                    df = pd.DataFrame(items)
                    
                    # [금액 가독성 개선] 숫자 변환 후 천 단위 콤마 추가
                    for col in ['MIN_BID_PRC', 'APSL_ASES_AVG_AMT']:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col]).apply(lambda x: f"{x:,.0f}원")
                    
                    cols_map = {'CLTR_NM': '물건명', 'MIN_BID_PRC': '최저입찰가', 'APSL_ASES_AVG_AMT': '감정가', 'CTGR_FULL_NM': '용도'}
                    st.dataframe(df[[c for c in cols_map.keys() if c in df.columns]].rename(columns=cols_map), use_container_width=True)
        except Exception as e:
            st.error(f"오류: {e}")

# ------------------------------------------------------------------------------
# 3. [탭2] 주식 퀀트 (Yahoo Finance)
# ------------------------------------------------------------------------------
with tab2:
    st.header("📈 주식 기술적 분석 (RSI)")
    ticker = st.text_input("티커 입력 (예: 005930.KS, TSLA)", value="005930.KS")
    if ticker:
        df_stock = yf.Ticker(ticker).history(period="1y")
        if not df_stock.empty:
            delta = df_stock['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            df_stock['RSI'] = 100 - (100 / (1 + (gain / loss)))
            st.plotly_chart(px.line(df_stock, y='Close', title=f"{ticker} 주가"), use_container_width=True)
            st.plotly_chart(px.line(df_stock, y='RSI', title="RSI 지표"), use_container_width=True)

# ------------------------------------------------------------------------------
# 4. [탭3] 아파트 실거래가 (Empty 오류 수정 및 지역 선택 기능)
# ------------------------------------------------------------------------------
with tab3:
    st.header("🏢 국토교통부 아파트 실거래가 조회")
    
    # 법정동 코드 자동 매핑 (시흥시 등 주요 지역 추가)
    gu_code_map = {
        "시흥시": "41390", "강남구": "11680", "서초구": "11650", "송파구": "11710",
        "분당구": "41135", "마포구": "11440", "용산구": "11170", "직접 입력": ""
    }

    c1, c2, c3 = st.columns([1.5, 1, 1])
    with c1:
        selected_gu = st.selectbox("지역 선택", list(gu_code_map.keys()), index=0)
    with c2:
        lawd_cd = st.text_input("법정동 코드", value=gu_code_map[selected_gu])
    with c3:
        # 데이터가 아직 없는 미래 날짜보다는 최근 확정된 달(202512 등)로 조회 권장
        deal_ymd = st.text_input("계약월 (YYYYMM)", value="202512")

    if st.button("실거래가 조회", key="btn_apt"):
        url = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
        params = {'serviceKey': PUBLIC_API_KEY, 'LAWD_CD': lawd_cd, 'DEAL_YMD': deal_ymd, 'numOfRows': '100', 'pageNo': '1'}
        
        try:
            with st.spinner("데이터 로드 중..."):
                res = requests.get(url, params=params, headers=COMMON_HEADERS)
            if res.status_code == 200:
                data = xmltodict.parse(res.content)
                body = data.get('response', {}).get('body', {})
                items = body.get('items')
                
                if items and items.get('item'):
                    item_list = items['item']
                    if isinstance(item_list, dict): item_list = [item_list]
                    df_apt = pd.DataFrame(item_list)
                    
                    # [핵심 수정] 항목명이 비어 보이는 문제 해결 (데이터 클렌징)
                    df_apt.columns = [col.strip() for col in df_apt.columns] # 컬럼명 공백 제거
                    
                    if '거래금액' in df_apt.columns:
                        df_apt['금액_숫자'] = df_apt['거래금액'].str.replace(',', '').str.strip().astype(int)
                        df_apt = df_apt.sort_values('금액_숫자', ascending=False)
                        df_apt['거래금액'] = df_apt['금액_숫자'].apply(lambda x: f"{x:,.0f}만원")
                    
                    # 보여줄 컬럼 리스트 (존재하는 것만 선택)
                    target_cols = ['아파트', '거래금액', '전용면적', '층', '일', '건축년도']
                    final_cols = [c for c in target_cols if c in df_apt.columns]
                    
                    if final_cols:
                        st.dataframe(df_apt[final_cols], use_container_width=True)
                        st.success(f"✅ {selected_gu} {len(df_apt)}건 조회 성공")
                    else:
                        st.warning("데이터는 있으나 표시할 항목이 없습니다. 전체 데이터를 표시합니다.")
                        st.dataframe(df_apt, use_container_width=True)
                else:
                    st.warning("거래 내역이 없습니다. (조회 월을 바꿔보세요)")
        except Exception as e:
            st.error(f"오류: {e}")

# ------------------------------------------------------------------------------
# 5. [탭4] 중고차 시세 (Demo)
# ------------------------------------------------------------------------------
with tab4:
    st.header("🚗 중고차 가치 평가")
    df_car = pd.DataFrame({
        '주행거리': [1000, 8000, 25000, 45000], '가격': [24500, 21800, 19200, 16800], '연식': [2024, 2023, 2022, 2021]
    })
    st.plotly_chart(px.scatter(df_car, x='주행거리', y='가격', color='연식', trendline="ols"), use_container_width=True)
