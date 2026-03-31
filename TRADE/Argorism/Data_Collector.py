import sys
import os
import json # 토큰 저장을 위한 모듈 추가
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta # 토큰 유효기간 계산을 위한 모듈 추가
from concurrent.futures import ThreadPoolExecutor, as_completed

# =====================================================================
# [환경 설정] 프로젝트 루트 경로 설정
# =====================================================================
# 현재 파일의 위치를 기준으로 3단계 위(루트 폴더)를 시스템 경로에 추가합니다.
# 이렇게 해야 COMMON 폴더 안의 모듈들을 에러 없이 불러올 수 있습니다.
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if root_dir not in sys.path:
    sys.path.append(root_dir)
    
import COMMON.KIS_Manager as KIS
from COMMON.Flag import SystemConfig 
from COMMON.DB_Manager import JubbyDB_Manager 

# =====================================================================
# 🛠️ [독립 워커용 가짜 API 클래스] (신규 추가)
# 멀티프로세싱 워커 안에서 KIS_API를 새로 생성하면 토큰을 또 발급받으려다
# 1분 제한 에러(EGW00133)가 발생합니다. 이를 방지하기 위해 데이터만 담는 껍데기 클래스를 만듭니다.
# =====================================================================
class DummyAPI:
    def __init__(self, app_key, app_secret, access_token, base_url):
        self.app_key = app_key
        self.app_secret = app_secret
        self.access_token = access_token
        self.base_url = base_url

# =====================================================================
# 🛠️ [독립 워커 함수] 개별 종목 수집 및 DB 저장
# =====================================================================
# 각 종목(code)마다 이 함수가 하나씩 할당되어 독립적으로(동시에) 실행됩니다.
def collect_worker(code, app_key, app_secret, access_token, base_url, market_dict):
    try:
        # 1. DB 매니저 생성 (각 워커마다 독립적인 DB 연결을 위해 여기서 생성)
        db_worker = JubbyDB_Manager()
        
        # 2. 내부 로그 저장용 함수 정의
        def worker_log(level, msg):
            try: db_worker.insert_log(level.upper(), msg)
            except: print(f"[{level.upper()}] {msg}")
            
        # 3. 🔥 핵심 수정: KIS_API 객체를 새로 만들지 않고, 메인에서 넘겨받은 토큰만 사용!
        # 이렇게 해야 워커들이 실행될 때마다 토큰 발급 요청을 해서 서버에 튕기는 현상이 사라집니다.
        api_worker = DummyAPI(app_key, app_secret, access_token, base_url)
        
        # 4. 주가 데이터 수집 (한국투자증권 또는 야후파이낸스)
        raw_df = fetch_data_logic(api_worker, code, is_market_index=False, log_func=worker_log)
        
        # 5. 수집된 데이터가 정상적으로 존재한다면?
        if raw_df is not None and not raw_df.empty:
            
            # 🔥 [DB 연동] 정답지 생성 기준값을 DB에서 가져옵니다 (없으면 기본값 세팅)
            try:
                future_win = int(db_worker.get_shared_setting("AI_TRAIN", "FUTURE_WINDOW", "10"))
                p_target = float(db_worker.get_shared_setting("AI_TRAIN", "PROFIT_TARGET", "1.5"))
                s_loss = float(db_worker.get_shared_setting("AI_TRAIN", "STOP_LOSS", "1.0"))
            except:
                future_win, p_target, s_loss = 10, 1.5, 1.0
                
            # 6. AI 딥러닝이 먹기 좋게 보조지표(RSI, MACD 등)와 정답지(Target)를 계산합니다.
            processed_df = calculate_indicators_logic(raw_df, market_dict, future_win, p_target, s_loss)
            
            # 7. 계산된 최종 데이터를 DB에 차곡차곡 저장합니다.
            if processed_df is not None and not processed_df.empty:
                db_worker.save_training_data(processed_df, SystemConfig.MARKET_MODE)
                return len(processed_df) # 수집 성공 시, 몇 줄을 수집했는지 반환
                
    except Exception as e:
        try: db_worker.insert_log("ERROR", f"❌ [{code}] 작업 중 오류: {e}")
        except: pass
        
    return 0 # 실패 시 0 반환

# =====================================================================
# 📈 [데이터 수집 로직] API 호출부 (국내 / 해외 / 🚀해외선물 통합)
# =====================================================================
def fetch_data_logic(api, stock_code, is_market_index=False, log_func=None):
    # -------------------------------------------------------------
    # 1. 해외선물 모드일 경우 (야후 파이낸스 라이브러리 사용)
    # -------------------------------------------------------------
    if SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
        try:
            import yfinance as yf # 야후 파이낸스
        except ImportError:
            if log_func: log_func("🚨 yfinance 라이브러리가 설치되지 않았습니다. (pip install yfinance 필요)", "ERROR")
            return None

        # 주삐 시스템의 코드를 야후 파이낸스 전용 티커로 변환 (나스닥, S&P, 다우 등)
        yf_ticker = stock_code
        if "NQ" in stock_code: yf_ticker = "NQ=F"
        elif "ES" in stock_code: yf_ticker = "ES=F"
        elif "YM" in stock_code: yf_ticker = "YM=F"
        elif "GC" in stock_code: yf_ticker = "GC=F" # 금
        elif "CL" in stock_code: yf_ticker = "CL=F" # 크루드 오일

        try:
            # 최근 7일치 1분봉 데이터를 긁어옵니다. (야후 무료 API 제한사항)
            df_yf = yf.download(yf_ticker, period="7d", interval="1m", progress=False)
            if df_yf.empty: return None
            
            # 멀티인덱스(컬럼이 2줄인 경우) 평탄화 작업
            if isinstance(df_yf.columns, pd.MultiIndex): df_yf.columns = df_yf.columns.get_level_values(0)
            
            # 인덱스를 컬럼으로 빼고, 날짜와 시간을 분리합니다.
            df_yf = df_yf.reset_index()
            dt_col = 'Datetime' if 'Datetime' in df_yf.columns else 'Date'
            df_yf['date'] = df_yf[dt_col].dt.strftime('%Y%m%d') # YYYYMMDD 형태
            df_yf['time'] = df_yf[dt_col].dt.strftime('%H%M%S') # HHMMSS 형태
            
            # 영문 컬럼명을 소문자로 통일
            df_yf.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
            df_res = df_yf[['date', 'time', 'open', 'high', 'low', 'close', 'volume']].copy()
            df_res['code'] = stock_code
            
            # 숫자형 데이터로 강제 변환
            df_res[['open', 'high', 'low', 'close', 'volume']] = df_res[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
            return df_res.dropna().reset_index(drop=True)
        except Exception as e:
            if log_func: log_func(f"🚨 야후 파이낸스 수집 에러 [{stock_code}]: {e}", "ERROR")
            return None

    # -------------------------------------------------------------
    # 2. 국내주식 / 해외주식 모드일 경우 (한국투자증권 API 사용)
    # -------------------------------------------------------------
    all_chunks = [] 
    target_time = "153000" if SystemConfig.MARKET_MODE == "DOMESTIC" else "160000" # 최초 시작 시간 (오후 3시 30분 / 오후 4시)
    next_key = "" # 과거 데이터를 계속 이어서 받기 위한 열쇠(Key)
    
    # 지수(시장 종합)는 15번 반복, 일반 종목은 65번 반복하여 과거 분봉을 긁어옵니다.
    loop_count = 15 if (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC") else 65

    for i in range(loop_count):
        # 2-1. 시장 모드에 따른 URL 및 요청 파라미터 셋업
        if SystemConfig.MARKET_MODE == "DOMESTIC" or (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC"):
            url = f"{api.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            tr_id = "FHKST03010200" # 국내 주식 분봉 TR 코드
            params = {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": target_time, "FID_PW_DATA_INCU_YN": "Y"}
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{api.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
            tr_id = "HHDFS76950200" # 해외 주식 분봉 TR 코드
            params = {"AUTH": "", "EXCD": "NAS", "SYMB": stock_code, "NMIN": "1", "PINC": "1", "NEXT": next_key, "NREC": "120", "FILL": "", "KEYB": next_key}

        # 2-2. 헤더에 토큰과 앱키를 담아서 발송 준비
        headers = {"content-type": "application/json", "authorization": f"Bearer {api.access_token}", "appkey": api.app_key, "appsecret": api.app_secret, "tr_id": tr_id, "custtype": "P"}
        
        # 2-3. 진짜로 서버에 요청!
        res = requests.get(url, headers=headers, params=params)
        
        # 2-4. 정상적으로 대답(200번)이 왔다면 처리 시작
        if res.status_code == 200 and res.json().get('rt_cd') == '0':
            data = res.json().get('output2', [])
            if not data: break # 더 이상 과거 데이터가 없으면 탈출
            
            df_chunk = pd.DataFrame(data)
            cols = df_chunk.columns.tolist()
            
            # API 종류(국내/해외)에 따라 컬럼명이 다르므로, 유연하게 매칭하여 찾아냅니다.
            c_date = next((c for c in ['stck_bsop_date', 'xymd', 'date'] if c in cols), cols[0])
            c_time = next((c for c in ['stck_cntg_hour', 'xhms', 'xhm', 'time'] if c in cols), cols[1])
            c_open = next((c for c in ['stck_oprc', 'open', 'oprc'] if c in cols), None)
            c_high = next((c for c in ['stck_hgpr', 'high', 'hgpr'] if c in cols), None)
            c_low = next((c for c in ['stck_lwpr', 'low', 'lwpr'] if c in cols), None)
            c_close = next((c for c in ['stck_prpr', 'last', 'close', 'prpr'] if c in cols), None)
            c_vol = next((c for c in ['evol', 'cntg_vol', 'vold', 'vol', 'acml_vol'] if c in cols), None)
            
            if None in [c_open, c_high, c_low, c_close, c_vol]: break # 중요 데이터가 빠져있으면 에러 방지용 탈출
            
            # 데이터를 예쁘게 정리
            df_chunk = df_chunk[[c_date, c_time, c_open, c_high, c_low, c_close, c_vol]]
            df_chunk.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
            all_chunks.append(df_chunk) # 모아둔 바구니에 담기
            
            # 다음번 반복 때 더 과거 데이터를 부르기 위한 셋업
            if SystemConfig.MARKET_MODE == "OVERSEAS":
                next_key = res.json().get('output1', {}).get('next', "")
                if not next_key: break
            else:
                target_time = data[-1]['stck_cntg_hour'] # 국내 주식은 마지막 시간을 기준으로 다음 요청을 함
                if int(target_time) <= 90000: break # 오전 9시 이전이면 장 시작 전이므로 탈출
            
            # API 서버가 아파하지 않게(초당 요청 제한 방어) 0.35초 휴식
            time.sleep(0.35) 
        else:
            # 실패 시 1.5초 대기 후 다음 반복 시도
            time.sleep(1.5); continue
            
    # 바구니에 담긴 조각들을 하나로 합치고 시간순으로 정렬
    if not all_chunks: return None
    df = pd.concat(all_chunks).drop_duplicates().sort_values(['date', 'time'])
    df['code'] = stock_code
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
    
    return df.reset_index(drop=True)

# =====================================================================
# 🧠 [지표 계산 및 정답지 생성] 🔥 초단타/돌파 매매용
# =====================================================================
# 🔥 [파라미터 변경] 파라미터로 future_window, profit_target, stop_loss를 받습니다.
def calculate_indicators_logic(df, market_dict, future_window=10, profit_target=1.5, stop_loss=1.0):
    # 데이터가 너무 적으면 지표 계산이 불가능하므로 버립니다.
    if df is None or len(df) < 30: return None
    
    # 1. 등락률 및 거래량 변화율
    df['return'] = df['close'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) * 100 
    df['vol_change'] = df['volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) 

    # 2. RSI (상대강도지수 - 현재 매수/매도 과열 상태를 나타냄)
    delta = df['close'].diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    rs = up.ewm(com=13).mean() / (down.ewm(com=13).mean() + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 3. MACD & 이동평균선
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()

    # =========================================================================
    # 🟢 [핵심 추가] 다중 시간대(Multi-Timeframe) 거시 추세 피처
    # =========================================================================
    df['MA60'] = df['close'].rolling(60).mean()   # 1시간 추세 (큰 숲)
    df['MA120'] = df['close'].rolling(120).mean() # 2시간 추세 (더 큰 숲)
    
    # 장기 이격도 (현재 주가가 1~2시간 평균치보다 얼마나 높은가/낮은가)
    df['Disparity_60'] = (df['close'] / (df['MA60'] + 1e-9)) * 100
    df['Disparity_120'] = (df['close'] / (df['MA120'] + 1e-9)) * 100
    
    # 거시 추세 정배열 점수 (1: 완벽한 상승장, 0: 하락장/역배열)
    df['Macro_Trend'] = np.where((df['close'] > df['MA60']) & (df['MA60'] > df['MA120']), 1, 0)
    # =========================================================================
    
    # 4. 볼린저 밴드 (주가의 변동폭을 그물처럼 감싸는 지표)
    df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
    df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
    df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / (df['MA20'] + 1e-9)) * 100 # 밴드의 좁고 넓음
    
    # 5. 이격도 (주가가 이동평균선으로부터 얼마나 멀어졌는가?)
    df['Disparity_5'] = (df['close'] / (df['MA5'] + 1e-9)) * 100
    df['Disparity_20'] = (df['close'] / (df['MA20'] + 1e-9)) * 100

    # 6. 거래량 에너지 (최근 20봉 대비 현재 거래량이 얼마나 터졌는가?)
    df['Vol_Energy'] = df['volume'] / (df['volume'].rolling(20).mean() + 1e-9)

    # 7. OBV (세력의 매집/이탈을 파악하는 거래량 지표)
    direction = np.where(df['close'] > df['close'].shift(1), 1, -1)
    direction = np.where(df['close'] == df['close'].shift(1), 0, direction)
    obv = (df['volume'] * direction).cumsum()
    df['OBV_Trend'] = obv.pct_change().replace([np.inf, -np.inf], 0).fillna(0)

    # 8. ATR (주가의 실제 변동성 - 손절선 잡을 때 유용함)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    df['ATR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

    # 9. 캔들 꼬리 분석 & 매수 압력 (위꼬리가 긴지, 아래꼬리가 긴지)
    df['High_Tail'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['Low_Tail'] = df[['open', 'close']].min(axis=1) - df['low']
    df['Buying_Pressure'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
    
    # 10. 시장(코스피/나스닥) 대비 해당 종목의 상대적 강세
    df['Market_Return_1m'] = df['time'].map(market_dict).fillna(0.0)

    # -----------------------------------------------------------------
    # 🔥 [핵심] 초단타 AI 모델을 위한 "정답지(Target)" 만들기
    # -----------------------------------------------------------------
    # 설명: 지금 이 분봉에서 샀을 때, 향후 n분 안에 'n% 수익'을 달성할 수 있으면서도,
    # 'n% 손실(손절선)'을 터치하지 않는 안전한 자리인지 점수(1 또는 0)를 매깁니다.

    # shift(-future_window)를 통해 미래 데이터를 현재 줄로 끌어와서 검사
    df['future_max'] = df['close'].shift(-future_window).rolling(window=future_window, min_periods=1).max()
    df['future_min'] = df['close'].shift(-future_window).rolling(window=future_window, min_periods=1).min()

    # 수익 목표 달성 O, 그리고 손절선 터치 X 이면 1(매수 타점), 아니면 0(버림)
    df['Target_Buy'] = np.where(
        (df['future_max'] >= df['close'] * (1 + profit_target/100)) & 
        (df['future_min'] > df['close'] * (1 - stop_loss/100)), # >= 에서 > 로 수정하여 손절 터치 엄격히 방어
        1, 0
    )
    # -----------------------------------------------------------------

    return df.dropna().reset_index(drop=True)

# =====================================================================
# 🚀 [메인 수집 매니저] UltraDataCollector
# =====================================================================
class UltraDataCollector:
    def __init__(self, app_key, app_secret, account_no, is_mock=True, log_callback=None, existing_token=None):
        self.app_key, self.app_secret = app_key, app_secret
        self.account_no, self.is_mock = account_no, is_mock
        self.log_callback = log_callback
        self.db = JubbyDB_Manager() 
        self.api = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        
        # 🔥 [안전장치 1] 메인 프로그램에서 이미 발급받은 토큰을 인자로 넘겨줬다면?
        # 새로 발급받지 않고 그걸 그대로 뺏어 씁니다! (1분 제한 원천 차단)
        if existing_token:
            self.access_token = existing_token
            self.api.access_token = existing_token
            self._save_token_to_file(existing_token) # 파일에도 잊지 않고 저장
            self.send_log("♻️ 메인 시스템에서 전달받은 토큰을 사용합니다.", "INFO")
        else:
            # 넘겨받은 게 없다면, 파일에서 찾거나 스스로 60초 기다려서라도 발급받습니다.
            self.access_token = self._get_safe_access_token()
            self.api.access_token = self.access_token
            
        self.market_dict = {} 

    def _save_token_to_file(self, token):
        """
        [내부 함수] 발급받은 소중한 토큰을 23시간 동안 기억하도록 파일에 저장합니다.
        """
        import sys, os
        # 🔥 스마트 경로 적용: EXE 모드면 EXE 옆에, 아니면 프로젝트 최상단 폴더에 저장
        if getattr(sys, 'frozen', False): 
            token_file = os.path.join(os.path.dirname(sys.executable), "kis_token_cache.json")
        else: 
            token_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "kis_token_cache.json")
        
        save_data = {
            "access_token": token,
            "expire_time": (datetime.now() + timedelta(hours=23)).strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            with open(token_file, "w", encoding="utf-8") as f:
                json.dump(save_data, f)
        except Exception as e:
            self.send_log(f"⚠️ 토큰 파일 저장 실패: {e}", "WARNING")

    def _get_safe_access_token(self):
        """
        [핵심 함수] 토큰을 파일에서 읽어오고, 실패하면 서버에 요청하되 
        1분 제한에 걸리면 죽지 않고 60초 기다렸다가 다시 가져오는 불사조 로직입니다.
        """
        import sys, os
        # 🔥 동일하게 스마트 경로 적용
        if getattr(sys, 'frozen', False): 
            token_file = os.path.join(os.path.dirname(sys.executable), "kis_token_cache.json")
        else: 
            token_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "kis_token_cache.json")
        
        # 1. 파일이 존재하는지 검사
        if os.path.exists(token_file):
            try:
                with open(token_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                expire_time = datetime.strptime(data["expire_time"], "%Y-%m-%d %H:%M:%S")
                
                # 아직 23시간이 안 지났다면 파일에서 꺼내 씁니다!
                if datetime.now() < expire_time:
                    self.send_log("♻️ 유효한 API 토큰을 파일에서 불러왔습니다. (1분 제한 회피)", "INFO")
                    return data["access_token"]
            except Exception:
                pass # 파일이 깨졌으면 무시하고 새로 발급
                
        # 2. 파일이 없거나(처음 실행) 만료되었다면 서버에 새로 요청
        self.send_log("🎫 KIS API 새로운 토큰 발급을 시도합니다...", "INFO")
        
        # 🔥 [안전장치 2] 1분 제한 에러(EGW00133) 발생 시 60초 대기 후 재시도
        max_retries = 2 # 총 2번 시도해봅니다.
        for attempt in range(max_retries):
            self.api.get_access_token()
            new_token = self.api.access_token
            
            # 발급 성공!
            if new_token:
                self._save_token_to_file(new_token)
                self.send_log("✅ 새 토큰 발급 및 파일 저장 성공!", "SUCCESS")
                return new_token
            
            # 발급 실패 (대부분 1분 제한)
            else:
                # 아직 재시도 기회가 남아있다면?
                if attempt < max_retries - 1:
                    self.send_log("🚨 1분 발급 제한(EGW00133) 감지! 프로그램이 죽지 않고 60초간 숨을 참습니다...", "WARNING")
                    self.send_log("⏳ 60초 뒤 자동으로 재시도합니다. 잠시만 기다려주세요...", "WARNING")
                    time.sleep(60) # 60초 동안 코드 실행을 일시정지 (여기서 에러가 해결됨!)
                else:
                    self.send_log("❌ 60초 대기 후에도 토큰 발급에 실패했습니다.", "ERROR")
                    return None
                    
        return None

    def send_log(self, msg, log_type="INFO"):
        if self.log_callback: self.log_callback(msg, log_type)
        else: print(f"[{log_type}] {msg}") 
        try: self.db.insert_log(log_type.upper(), msg)
        except: pass

    def run_collection(self, stock_list):
        if not self.access_token:
            self.send_log("🚨 토큰이 없어 수집을 중단합니다.", "ERROR")
            return "FAILED"

        if SystemConfig.MARKET_MODE == "DOMESTIC": table_name = "TrainData_Domestic"
        elif SystemConfig.MARKET_MODE == "OVERSEAS": table_name = "TrainData_Overseas"
        else: table_name = "TrainData_Futures"

        self.send_log(f"🧹 '{table_name}' 테이블을 초기화하고 새 데이터를 준비합니다...", "INFO")
        conn = self.db._get_connection(self.db.python_db_path)
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.commit()
        finally: conn.close()

        if SystemConfig.MARKET_MODE == "DOMESTIC": market_ticker = '069500' 
        elif SystemConfig.MARKET_MODE == "OVERSEAS": market_ticker = 'QQQ'  
        else: market_ticker = 'NQM26' 

        m_df = fetch_data_logic(self.api, market_ticker, is_market_index=True, log_func=self.send_log)
        if m_df is not None:
            m_df['Market_Return_1m'] = m_df['close'].pct_change() * 100
            self.market_dict = dict(zip(m_df['time'], m_df['Market_Return_1m'].fillna(0)))

        total_stocks = len(stock_list)
        accumulated_rows = 0
        
        shared_token = self.access_token
        shared_base_url = self.api.base_url

        # =====================================================================
        # 🚀 [핵심 수정] 10개 스레드 + 15개 묶음 초고속 멀티스레딩 (디도스 방어막 포함)
        # =====================================================================
        batch_size = 15  # 증권사 1초 20회 제한 방어 -> 15개씩 묶어서 던짐
        max_workers = 10 # 10명의 스레드(작업자) 동시 고용
        processed_count = 0
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 전체 주식 리스트를 15개 단위로 쪼개서 작업
            for i in range(0, total_stocks, batch_size):
                start_time = time.time() # ⏱️ 현재 묶음 작업 시작 시간 기록
                batch_codes = stock_list[i : i + batch_size]
                
                # 10명의 작업자에게 15개 종목을 동시에 할당
                futures = {executor.submit(
                    collect_worker, 
                    code, 
                    self.app_key, 
                    self.app_secret, 
                    shared_token, 
                    shared_base_url, 
                    self.market_dict
                ): code for code in batch_codes}
                
                # 데이터가 수집되는 족족 결과물 처리
                for future in as_completed(futures):
                    code = futures[future]
                    processed_count += 1
                    try:
                        rows = future.result()
                        accumulated_rows += rows
                        progress = int((processed_count / total_stocks) * 100)
                        self.send_log(f"💾 [{processed_count}/{total_stocks}] '{code}' 수집 완료 (누적 {accumulated_rows:,}줄)", "INFO")
                        self.db.update_system_status('COLLECTOR', 'DB 적재 중...', progress)
                    except Exception as e:
                        pass
                
                # 🛡️ [완벽한 디도스 차단 방어막]
                # 15개를 다 긁어오는 데 1.05초가 안 걸렸다면? 남은 시간 동안 억지로 대기!
                elapsed_time = time.time() - start_time
                if elapsed_time < 1.05:
                    time.sleep(1.05 - elapsed_time)
        # =====================================================================

        self.db.update_system_status('COLLECTOR', '수집 및 DB 적재 완료!', 100)
        self.send_log(f"💎 총 {accumulated_rows:,}줄 적재 완료!", "SUCCESS")
        return "SUCCESS"
    
# =====================================================================
# 테스트 실행부
# =====================================================================
if __name__ == "__main__":
    db = JubbyDB_Manager()
    
    # 🔥 DB에서 세팅값 가져오기 (없을 시 기존 하드코딩 값으로 DB에 자동 등록됨)
    APP_KEY = db.get_shared_setting("KIS_API", "APP_KEY", "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy")
    APP_SECRET = db.get_shared_setting("KIS_API", "APP_SECRET", "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8=")
    
    if SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
        ACCOUNT = db.get_shared_setting("KIS_API", "FUTURES_ACCOUNT", "60039684")
    else:
        ACCOUNT = db.get_shared_setting("KIS_API", "STOCK_ACCOUNT", "50172151")

    try:
        # DB에서 현재 감시 대상(target_stocks) 리스트를 긁어옵니다.
        query = f"SELECT symbol FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
        stock_list_df = pd.read_sql(query, db.engine)
        stock_list = stock_list_df['symbol'].astype(str).tolist()
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            stock_list = [str(s).zfill(6) for s in stock_list] # 국내 코드는 6자리 0 채우기
    except:
        stock_list = ['005930', '000660'] # 삼성전자, SK하이닉스 (DB 연결 실패 시 기본값)

    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    collector.run_collection(stock_list)