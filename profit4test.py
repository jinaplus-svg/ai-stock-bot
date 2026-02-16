import streamlit as st
import pandas as pd
import requests
import xmltodict
import plotly.express as px
import yfinance as yf
from datetime import datetime

# ------------------------------------------------------------------------------
# 1. 기본 설정 및 비밀키 로드
# ------------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Profit4Test Investment")

st.title("💰 Profit4Test: 통합 투자 분석 대시보드")
st.markdown("---")

# secrets.toml (또는 Streamlit Cloud Secrets)에서 API 키를 가져옵니다.
try:
    # toml 파일에 [public_api] 섹션 아래 key 변수가 있어야 합니다.
    PUBLIC_API_KEY = st.secrets["public_api"]["key"]
    st.sidebar.success("✅ API 키가 로드되었습니다.")
except Exception as e:
    st.sidebar.error("❌ API 키를 찾을 수 없습니다.")
    st.sidebar.info("로컬 실행 시 .streamlit/secrets.toml 파일을 확인하세요.")
    PUBLIC_API_KEY = ""

# 탭 구성
tab1, tab2, tab3, tab4 = st.tabs(["🏛️ 온비드 공매", "📈 주식 퀀트", "🏢 아파트 실거래", "🚗 중고차 시세"])

# ------------------------------------------------------------------------------
# 2. [탭1] 온비드 공매 (캠코)
# ------------------------------------------------------------------------------
with tab1:
    st.header("캠코 공매 물건 조회")
    st.caption("온비드 오픈 API를 통해 공매 물건을 실시간 조회합니다.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        # 온비드 지역코드 매핑 (주요 지역)
        region_map = {"서울": "11", "경기": "41", "인천": "28", "충북": "43"}
        selected_region = st.selectbox("지역 선택", list(region_map.keys()), index=0)
        sido_cd = region_map[selected_region]
    with col2:
        # 물건 용도 (온비드 코드 기준: 001 아파트, 002 주거용건물 등)
        goods_type = st.selectbox("용도", ["전체", "아파트", "토지"])
    with col3:
        rows = st.number_input("조회 개수", min_value=10, max_value=50, value=20)

    if st.button("공매 물건 검색", key="btn_onbid"):
        if not PUBLIC_API_KEY:
            st.error("API 키가 설정되지 않았습니다.")
        else:
            # 온비드 물건정보 조회 URL
            url = "https://openapi.onbid.co.kr/openapi/services/KamcoPblsalThingInfoInqireSvc/getKamcoPblsalThingList"
            
            params = {
                'serviceKey': PUBLIC_API_KEY,  # Decoding Key
                'pageNo': '1',
                'numOfRows': str(rows),
                'CTGR_ID': '10000',     # 10000: 부동산
                'SIDO': sido_cd         # 선택한 시도 코드
            }
            
            # 용도 필터링 (간략 구현)
            if goods_type == "아파트":
                params['DPSL_MTD_CD'] = '0001' # 매각

            try:
                with st.spinner("온비드 서버 통신 중..."):
                    response = requests.get(url, params=params)
                    
                if response.status_code == 200:
                    try:
                        data = xmltodict.parse(response.content)
                        
                        # 응답 구조 유연성 처리 (데이터가 없거나 1개일 때 처리)
                        if 'response' in data and 'body' in data['response']:
                            body = data['response']['body']
                            
                            if body.get('items') is None:
                                st.warning("🔍 해당 조건에 맞는 공매 물건이 없습니다.")
                            else:
                                items = body['items']['item']
                                # 결과가 1건일 경우 리스트로 변환
                                if isinstance(items, dict): items = [items]
                                
                                df = pd.DataFrame(items)
                                # 주요 컬럼만 선택하여 보여주기 (컬럼명이 한글/영문 혼용될 수 있음 확인 필요)
                                st.dataframe(df, use_container_width=True)
                                st.success(f"총 {len(df)}건의 물건이 조회되었습니다.")
                        else:
                            st.warning("데이터 형식이 올바르지 않습니다. (XML 구조 확인 필요)")
                            # 디버깅용: st.write(data) 
                    except Exception as e:
                        st.error(f"데이터 파싱 오류: {e}")
                else:
                    st.error(f"서버 연결 실패 (Status Code: {response.status_code})")
            except Exception as e:
                st.error(f"통신 오류: {e}")

# ------------------------------------------------------------------------------
# 3. [탭2] 주식 퀀트 (Yahoo Finance)
# ------------------------------------------------------------------------------
with tab2:
    st.header("RSI 기반 매매 신호 분석")
    st.caption("LG전자 등 관심 종목의 과매도/과매수 구간을 파악합니다.")
    
    ticker = st.text_input("티커 입력 (예: 066570.KS, TSLA, BTC-USD)", value="066570.KS")
    
    if ticker:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="6mo")
            
            if not df.empty:
                # RSI 계산 Logic (14일 기준)
                delta = df['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                df['RSI'] = 100 - (100 / (1 + rs))
                
                # 주가 차트
                st.subheader(f"{ticker} 주가 추이")
                st.plotly_chart(px.line(df, y='Close', title="Price History"), use_container_width=True)
                
                # RSI 차트
                st.subheader("RSI 지표 (Momentum)")
                fig_rsi = px.line(df, y='RSI', title="RSI (30이하: 매수 / 70이상: 매도)")
                fig_rsi.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="매수 구간")
                fig_rsi.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="매도 구간")
                st.plotly_chart(fig_rsi, use_container_width=True)
                
                # 현재 상태 분석
                curr_rsi = df['RSI'].iloc[-1]
                st.metric("현재 RSI", f"{curr_rsi:.2f}")
                
                if curr_rsi <= 30: 
                    st.success("✅ 강력 매수 신호 (RSI 과매도 구간)")
                elif curr_rsi >= 70: 
                    st.error("⚠️ 매도 고려 (RSI 과매수 구간)")
                else:
                    st.info("중립 구간입니다.")
            else:
                st.warning("데이터를 불러올 수 없습니다. 티커를 확인해주세요.")
        except Exception as e:
            st.error(f"오류 발생: {e}")

# ------------------------------------------------------------------------------
# 4. [탭3] 아파트 실거래가 (국토부)
# ------------------------------------------------------------------------------
with tab3:
    st.header("국토교통부 아파트 실거래가 조회")
    
    c1, c2 = st.columns(2)
    with c1:
        lawd_cd = st.text_input("법정동 코드 (5자리)", value="11680", help="강남구: 11680, 송파구: 11710")
    with c2:
        deal_ymd = st.text_input("계약월 (YYYYMM)", value=datetime.now().strftime("%Y%m"))
    
    if st.button("실거래가 조회", key="btn_apt"):
        if not PUBLIC_API_KEY:
            st.error("API 키가 없습니다.")
        else:
            url = "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest/RTMSOBJSvc/getRTMSDataSvcAptTradeDev"
            params = {
                'serviceKey': PUBLIC_API_KEY, # Decoding Key
                'pageNo': '1',
                'numOfRows': '100',
                'LAWD_CD': lawd_cd,
                'DEAL_YMD': deal_ymd
            }
            
            try:
                res = requests.get(url, params=params)
                if res.status_code == 200:
                    try:
                        data = xmltodict.parse(res.content)
                        result_code = data['response']['header']['resultCode']
                        
                        if result_code == '00':
                            body = data['response']['body']
                            if body.get('items') is None:
                                st.warning("해당 월에 거래 내역이 없습니다.")
                            else:
                                items = body['items']['item']
                                if isinstance(items, dict): items = [items]
                                
                                df = pd.DataFrame(items)
                                # 필요한 컬럼만 정리 및 형변환
                                cols = ['아파트', '전용면적', '거래금액', '층', '월', '일', '건축년도']
                                valid_cols = [c for c in cols if c in df.columns]
                                df_show = df[valid_cols].copy()
                                
                                # 금액 포맷팅 (쉼표 제거 후 정렬용)
                                df_show['거래금액_숫자'] = df_show['거래금액'].str.replace(',', '').astype(int)
                                df_show = df_show.sort_values('거래금액_숫자', ascending=True)
                                
                                st.dataframe(df_show.drop(columns=['거래금액_숫자']), use_container_width=True)
                                
                                # 간단 통계
                                min_price = df_show['거래금액_숫자'].min()
                                max_price = df_show['거래금액_숫자'].max()
                                st.info(f"최저가: {min_price:,}만원 / 최고가: {max_price:,}만원")
                        else:
                            st.error(f"API 에러 메시지: {data['response']['header']['resultMsg']}")
                    except Exception as e:
                        st.error(f"데이터 처리 중 오류: {e}")
                else:
                    st.error("서버 접속 실패")
            except Exception as e:
                st.error(f"오류: {e}")

# ------------------------------------------------------------------------------
# 5. [탭4] 중고차 시세 (Mock Data)
# ------------------------------------------------------------------------------
with tab4:
    st.header("중고차 가치 평가 (Demo)")
    st.info("ℹ️ 엔카 등 민간 데이터는 크롤링 제한이 있어, 분석 로직 시각화 데모로 대체합니다.")
    
    target_car = st.text_input("차종 입력", value="포르쉐 911 카레라 GTS")
    
    # 가상의 데이터 생성
    data = {
        '모델': [target_car]*10,
        '연식': [2021, 2022, 2023, 2024, 2021, 2022, 2023, 2020, 2022, 2023],
        '주행거리': [45000, 25000, 8000, 2000, 52000, 30000, 12000, 70000, 28000, 9000],
        '가격(만원)': [16500, 19000, 21500, 24000, 15800, 18500, 21000, 14000, 18800, 21200],
        '상태': ['무사고']*8 + ['사고']*2
    }
    df_car = pd.DataFrame(data)
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # 산점도 차트
        fig = px.scatter(df_car, x='주행거리', y='가격(만원)', 
                         color='연식', size='가격(만원)', 
                         hover_data=['상태'],
                         title=f"{target_car} 주행거리별 가격 분포")
        st.plotly_chart(fig, use_container_width=True)
        
    with col2:
        st.write("📊 **분석 인사이트**")
        st.markdown("""
        - **저평가 매물:** 추세선 아래에 위치
        - **감가상각:** 1만km 당 약 -500만원
        - **추천:** 2022년식 3만km 이하 매물
        """)
