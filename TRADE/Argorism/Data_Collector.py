import sys
import os
import pandas as pd
import numpy as np
import requests
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

# 프로젝트 루트 경로 설정
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

import COMMON.KIS_Manager as KIS
from COMMON.Flag import SystemConfig 
from COMMON.DB_Manager import JubbyDB_Manager 

# =====================================================================
# 🛠️ [독립 워커 함수] 개별 종목 수집 및 DB 저장
# =====================================================================
def collect_worker(code, app_key, app_secret, account_no, is_mock, access_token, market_dict):
    try:
        db_worker = JubbyDB_Manager()
        
        def worker_log(level, msg):
            try: db_worker.insert_log(level.upper(), msg)
            except: print(f"[{level.upper()}] {msg}")
            
        api_worker = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        api_worker.access_token = access_token
        
        raw_df = fetch_data_logic(api_worker, code, is_market_index=False, log_func=worker_log)
        
        if raw_df is not None and not raw_df.empty:
            processed_df = calculate_indicators_logic(raw_df, market_dict)
            if processed_df is not None and not processed_df.empty:
                db_worker.save_training_data(processed_df, SystemConfig.MARKET_MODE)
                return len(processed_df)
                
    except Exception as e:
        try: db_worker.insert_log("ERROR", f"❌ [{code}] 작업 중 오류: {e}")
        except: pass
    return 0

# =====================================================================
# 📈 [데이터 수집 로직] API 호출부 (국내 / 해외 / 🚀해외선물 통합)
# =====================================================================
def fetch_data_logic(api, stock_code, is_market_index=False, log_func=None):
<<<<<<< HEAD
=======
    
    # 🚀 [플랜 B 발동!] 해외선물이면 한투 API를 버리고 야후 파이낸스에서 직수입합니다!
>>>>>>> 57cac1a06d103c97f6afd69617e371a86e07758f
    if SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
        try:
            import yfinance as yf
        except ImportError:
<<<<<<< HEAD
            if log_func: log_func("🚨 yfinance 라이브러리가 설치되지 않았습니다.", "ERROR")
=======
            if log_func: log_func("🚨 yfinance 라이브러리가 설치되지 않았습니다. 터미널에 'pip install yfinance'를 입력하세요.", "ERROR")
>>>>>>> 57cac1a06d103c97f6afd69617e371a86e07758f
            return None

        yf_ticker = stock_code
        if "NQ" in stock_code: yf_ticker = "NQ=F"
        elif "ES" in stock_code: yf_ticker = "ES=F"
        elif "YM" in stock_code: yf_ticker = "YM=F"
        elif "GC" in stock_code: yf_ticker = "GC=F"
        elif "CL" in stock_code: yf_ticker = "CL=F"

<<<<<<< HEAD
        try:
            df_yf = yf.download(yf_ticker, period="7d", interval="1m", progress=False)
            if df_yf.empty: return None
            if isinstance(df_yf.columns, pd.MultiIndex): df_yf.columns = df_yf.columns.get_level_values(0)
            
            df_yf = df_yf.reset_index()
            dt_col = 'Datetime' if 'Datetime' in df_yf.columns else 'Date'
            df_yf['date'] = df_yf[dt_col].dt.strftime('%Y%m%d')
            df_yf['time'] = df_yf[dt_col].dt.strftime('%H%M%S')
            df_yf.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
            df_res = df_yf[['date', 'time', 'open', 'high', 'low', 'close', 'volume']].copy()
            df_res['code'] = stock_code
            df_res[['open', 'high', 'low', 'close', 'volume']] = df_res[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
            return df_res.dropna().reset_index(drop=True)
=======
        if log_func: log_func(f"🌐 [야후 파이낸스] '{yf_ticker}' 과거 1분봉 무료 싹쓸이 중...", "INFO")
        try:
            df_yf = yf.download(yf_ticker, period="7d", interval="1m", progress=False)
            if df_yf.empty:
                if log_func: log_func(f"🚨 {yf_ticker} 야후 데이터를 찾을 수 없습니다.", "ERROR")
                return None
            
            if isinstance(df_yf.columns, pd.MultiIndex):
                df_yf.columns = df_yf.columns.get_level_values(0)
            
            df_yf = df_yf.reset_index()
            dt_col = 'Datetime' if 'Datetime' in df_yf.columns else 'Date'
            
            df_yf['date'] = df_yf[dt_col].dt.strftime('%Y%m%d')
            df_yf['time'] = df_yf[dt_col].dt.strftime('%H%M%S')
            df_yf.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
            
            df_res = df_yf[['date', 'time', 'open', 'high', 'low', 'close', 'volume']].copy()
            df_res['code'] = stock_code
            df_res[['open', 'high', 'low', 'close', 'volume']] = df_res[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
            
            time.sleep(0.5) 
            return df_res.dropna().reset_index(drop=True)
            
>>>>>>> 57cac1a06d103c97f6afd69617e371a86e07758f
        except Exception as e:
            if log_func: log_func(f"🚨 야후 파이낸스 수집 에러: {e}", "ERROR")
            return None

<<<<<<< HEAD
=======
    # 🇰🇷/🌐 주식의 경우 원래대로 한투 API를 이용해 정상 수집합니다.
>>>>>>> 57cac1a06d103c97f6afd69617e371a86e07758f
    all_chunks = [] 
    target_time = "153000" if SystemConfig.MARKET_MODE == "DOMESTIC" else "160000"
    next_key = ""
    loop_count = 15 if (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC") else 65

    for i in range(loop_count):
        if SystemConfig.MARKET_MODE == "DOMESTIC" or (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC"):
            url = f"{api.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            tr_id = "FHKST03010200"
            params = {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": target_time, "FID_PW_DATA_INCU_YN": "Y"}
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{api.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
            tr_id = "HHDFS76950200"
<<<<<<< HEAD
            params = {"AUTH": "", "EXCD": "NAS", "SYMB": stock_code, "NMIN": "1", "PINC": "1", "NEXT": next_key, "NREC": "120", "FILL": "", "KEYB": next_key}
=======
            params = {
                "AUTH": "", "EXCD": "NAS", "SYMB": stock_code, "NMIN": "1", "PINC": "1", 
                "NEXT": next_key, "NREC": "120", "FILL": "", "KEYB": next_key
            }

        headers = {
            "content-type": "application/json", 
            "authorization": f"Bearer {api.access_token}",
            "appkey": api.app_key, "appsecret": api.app_secret, "tr_id": tr_id, "custtype": "P"
        }
>>>>>>> 57cac1a06d103c97f6afd69617e371a86e07758f

        headers = {"content-type": "application/json", "authorization": f"Bearer {api.access_token}", "appkey": api.app_key, "appsecret": api.app_secret, "tr_id": tr_id, "custtype": "P"}
        res = requests.get(url, headers=headers, params=params)
        
        if res.status_code == 200 and res.json().get('rt_cd') == '0':
            data = res.json().get('output2', [])
            if not data: break
            df_chunk = pd.DataFrame(data)
            cols = df_chunk.columns.tolist()
            c_date = next((c for c in ['stck_bsop_date', 'xymd', 'date'] if c in cols), cols[0])
            c_time = next((c for c in ['stck_cntg_hour', 'xhms', 'xhm', 'time'] if c in cols), cols[1])
            c_open = next((c for c in ['stck_oprc', 'open', 'oprc'] if c in cols), None)
            c_high = next((c for c in ['stck_hgpr', 'high', 'hgpr'] if c in cols), None)
            c_low = next((c for c in ['stck_lwpr', 'low', 'lwpr'] if c in cols), None)
            c_close = next((c for c in ['stck_prpr', 'last', 'close', 'prpr'] if c in cols), None)
            c_vol = next((c for c in ['evol', 'cntg_vol', 'vold', 'vol', 'acml_vol'] if c in cols), None)
            if None in [c_open, c_high, c_low, c_close, c_vol]: break
            df_chunk = df_chunk[[c_date, c_time, c_open, c_high, c_low, c_close, c_vol]]
            df_chunk.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
            all_chunks.append(df_chunk)
<<<<<<< HEAD
=======

>>>>>>> 57cac1a06d103c97f6afd69617e371a86e07758f
            if SystemConfig.MARKET_MODE == "OVERSEAS":
                next_key = res.json().get('output1', {}).get('next', "")
                if not next_key: break
            else:
                target_time = data[-1]['stck_cntg_hour'] 
                if int(target_time) <= 90000: break
            time.sleep(0.35) 
        else:
<<<<<<< HEAD
            time.sleep(1.5); continue
=======
            raw_error = str(res.text).replace('<', '&lt;').replace('>', '&gt;')
            error_msg = f"🚨 [{stock_code}] 한투 API 거절 원문 (상태코드: {res.status_code}): {raw_error}"
            
            if log_func: log_func(error_msg, "ERROR")
            else: print(error_msg)
            
            if "초당 거래건수" in raw_error or "EGW00201" in raw_error:
                if log_func: log_func(f"⏳ [{stock_code}] 속도 제한! 1.5초 대기 후 이어서 수집합니다...", "WARNING")
                time.sleep(1.5)
                continue
                
            if res.status_code == 401:
                if log_func: log_func("🚨 토큰이 만료되었습니다. 프로그램을 재시작하세요.", "ERROR")
            break
>>>>>>> 57cac1a06d103c97f6afd69617e371a86e07758f
            
    if not all_chunks: return None
    df = pd.concat(all_chunks).drop_duplicates().sort_values(['date', 'time'])
    df['code'] = stock_code
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
    return df.reset_index(drop=True)

# =====================================================================
# 🧠 [지표 계산 및 정답지 생성] 🔥 초단타/돌파 매매용으로 고도화
# =====================================================================
def calculate_indicators_logic(df, market_dict):
    if df is None or len(df) < 30: return None
    
    df['return'] = df['close'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) * 100 
    df['vol_change'] = df['volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) 

    delta = df['close'].diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    rs = up.ewm(com=13).mean() / (down.ewm(com=13).mean() + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    
    df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
    df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
    df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / (df['MA20'] + 1e-9)) * 100
    
    df['Disparity_5'] = (df['close'] / (df['MA5'] + 1e-9)) * 100
    df['Disparity_20'] = (df['close'] / (df['MA20'] + 1e-9)) * 100

    df['Vol_Energy'] = df['volume'] / (df['volume'].rolling(20).mean() + 1e-9)

    direction = np.where(df['close'] > df['close'].shift(1), 1, -1)
    direction = np.where(df['close'] == df['close'].shift(1), 0, direction)
    obv = (df['volume'] * direction).cumsum()
    df['OBV_Trend'] = obv.pct_change().replace([np.inf, -np.inf], 0).fillna(0)

    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    df['ATR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

    df['High_Tail'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['Low_Tail'] = df[['open', 'close']].min(axis=1) - df['low']
    df['Buying_Pressure'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
    
    df['Market_Return_1m'] = df['time'].map(market_dict).fillna(0.0)

    # -----------------------------------------------------------------
    # 🔥 [핵심 수정] 초단타/돌파 매매용 AI 정답지(Target) 생성 로직
    # -----------------------------------------------------------------
    # 설명: 매수 후 '10분' 이내에 '1.5%' 이상 오르면 1점(성공), 아니면 0점(실패)
    # 단, 손절선(-1.0%)을 먼저 터치하면 오답으로 처리하여 안전한 타점만 학습시킵니다.
    future_window = 10
    profit_target = 1.5
    stop_loss = 1.0

    # 향후 10분간의 최고가와 최저가를 미리 계산 (shift(-future_window)로 미래 데이터 참조)
    df['future_max'] = df['close'].shift(-future_window).rolling(window=future_window, min_periods=1).max()
    df['future_min'] = df['close'].shift(-future_window).rolling(window=future_window, min_periods=1).min()

    # 정답 조건: 10분 내 최고가가 1.5% 이상 상승 AND 10분 내 최저가가 -1.0%를 깨지 않음
    df['Target_Buy'] = np.where(
        (df['future_max'] >= df['close'] * (1 + profit_target/100)) & 
        (df['future_min'] >= df['close'] * (1 - stop_loss/100)), 
        1, 0
    )
    # -----------------------------------------------------------------

    return df.dropna().reset_index(drop=True)

# =====================================================================
# 🚀 [메인 클래스] UltraDataCollector
# =====================================================================
class UltraDataCollector:
    def __init__(self, app_key, app_secret, account_no, is_mock=True, log_callback=None):
        self.app_key, self.app_secret = app_key, app_secret
        self.account_no, self.is_mock = account_no, is_mock
        self.log_callback = log_callback
        self.db = JubbyDB_Manager() 
        self.api = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        self.api.get_access_token()
        self.market_dict = {} 

    def send_log(self, msg, log_type="INFO"):
        if self.log_callback: self.log_callback(msg, log_type)
        else: print(f"[{log_type}] {msg}") 
        try: self.db.insert_log(log_type.upper(), msg)
        except: pass

    def run_collection(self, stock_list):
        if not self.api.access_token:
            self.send_log("🚨 토큰 발급 실패!", "ERROR")
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
        shared_token = self.api.access_token

        with ProcessPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(collect_worker, code, self.app_key, self.app_secret, self.account_no, self.is_mock, shared_token, self.market_dict): code for code in stock_list}
            for idx, future in enumerate(as_completed(futures)):
                code = futures[future]
                try:
                    rows = future.result()
                    accumulated_rows += rows
                    progress = int(((idx + 1) / total_stocks) * 100)
                    self.send_log(f"💾 [{idx+1}/{total_stocks}] '{code}' 수집 완료 (누적 {accumulated_rows:,}줄)", "INFO")
                    self.db.update_system_status('COLLECTOR', 'DB 적재 중...', progress)
                except: pass

        self.db.update_system_status('COLLECTOR', '수집 및 DB 적재 완료!', 100)
        self.send_log(f"💎 총 {accumulated_rows:,}줄 적재 완료!", "SUCCESS")
        return "SUCCESS"

if __name__ == "__main__":
    APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    ACCOUNT = "50172151"

    db = JubbyDB_Manager()
    try:
        # DB에서 현재 감시 대상(target_stocks) 리스트를 긁어옵니다.
        query = f"SELECT symbol FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
        stock_list_df = pd.read_sql(query, db.engine)
        stock_list = stock_list_df['symbol'].astype(str).tolist()
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            stock_list = [str(s).zfill(6) for s in stock_list]
    except:
        stock_list = ['005930', '000660']

    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    collector.run_collection(stock_list)