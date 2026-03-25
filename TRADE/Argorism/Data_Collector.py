import sys
import os
import pandas as pd
import numpy as np
import requests
import time
import FinanceDataReader as fdr
from concurrent.futures import ProcessPoolExecutor, as_completed

# 프로젝트 루트 경로 설정
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

import COMMON.KIS_Manager as KIS
from COMMON.Flag import SystemConfig 
from COMMON.DB_Manager import JubbyDB_Manager 

# =====================================================================
# 🛠️ [독립 워커 함수] 개별 종목 수집 및 저장
# [수정] 이제 access_token을 인자로 직접 전달받습니다. (중복 발급 방지)
# =====================================================================
def collect_worker(code, app_key, app_secret, account_no, is_mock, access_token, market_dict):
    """
    각 코어에서 실행될 작업 단위입니다.
    """
    try:
        # 프로세스마다 독립적인 DB 매니저 생성
        db_worker = JubbyDB_Manager()
        
        # API 객체 생성 시 토큰 발급 함수(get_access_token)를 절대 호출하지 않습니다.
        api_worker = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        
        # 🔥 [핵심 수정] 메인에서 받아온 토큰을 그대로 꽂아줍니다.
        api_worker.access_token = access_token
        
        # 1. 데이터 수집 (내부에서 api_worker.access_token 사용)
        raw_df = fetch_data_logic(api_worker, code)
        
        if raw_df is not None and not raw_df.empty:
            # 2. 지표 계산
            processed_df = calculate_indicators_logic(raw_df, market_dict)
            
            if processed_df is not None and not processed_df.empty:
                # 3. SQL 저장
                db_worker.save_training_data(processed_df, SystemConfig.MARKET_MODE)
                return len(processed_df)
                
    except Exception as e:
        # 에러 발생 시 로그 출력 (토큰 문제인지 다른 문제인지 파악용)
        print(f"❌ [{code}] 작업 중 오류: {e}")
    return 0

# =====================================================================
# 📈 [데이터 수집 로직] API 호출부
# =====================================================================
def fetch_data_logic(api, stock_code, is_market_index=False):
    all_chunks = [] 
    target_time = "153000" if SystemConfig.MARKET_MODE == "DOMESTIC" else "160000"
    next_key = ""
    
    # 지수는 15회, 일반 종목은 65회 루프
    loop_count = 15 if (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC") else 65

    for i in range(loop_count):
        if SystemConfig.MARKET_MODE == "DOMESTIC" or (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC"):
            url = f"{api.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            tr_id = "FHKST03010200"
            params = {
                "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", 
                "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": target_time, "FID_PW_DATA_INCU_YN": "Y"
            }
        else:
            url = f"{api.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
            tr_id = "HHDFS76950200"
            params = {
                "AUTH": "", "EXCD": "NAS", "SYMB": stock_code, "NMIN": "1", "PINC": "1", 
                "NEXT": next_key, "NREC": "120", "FILL": "", "KEYB": next_key
            }

        headers = {
            "content-type": "application/json", 
            "authorization": f"Bearer {api.access_token}", # 전달받은 토큰 사용
            "appkey": api.app_key, "appsecret": api.app_secret, "tr_id": tr_id, "custtype": "P"
        }

        res = requests.get(url, headers=headers, params=params)
        
        if res.status_code == 200 and res.json().get('rt_cd') == '0':
            data = res.json().get('output2', [])
            if not data: break
            
            df_chunk = pd.DataFrame(data)
            cols = df_chunk.columns.tolist()
            
            # 유연한 컬럼 매핑 (어떤 이름으로 와도 대응)
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

            if SystemConfig.MARKET_MODE == "OVERSEAS":
                next_key = res.json().get('output1', {}).get('next', "")
                if not next_key: break
            else:
                target_time = data[-1]['stck_cntg_hour'] 
                if int(target_time) <= 90000: break
            
            # 💡 [속도 조절] 모의투자 계좌라면 0.2~0.5초 정도로 늘리는 것이 안전합니다.
            time.sleep(0.1) 
        else:
            # 토큰 만료 등의 사유로 401 에러가 나면 즉시 중단
            if res.status_code == 401:
                print("🚨 토큰이 만료되었습니다. 다시 실행하세요.")
            break
            
    if not all_chunks: return None
    df = pd.concat(all_chunks).drop_duplicates().sort_values(['date', 'time'])
    df['code'] = stock_code
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
    return df.reset_index(drop=True)

# =====================================================================
# 🧠 [지표 계산 로직] AI 학습용 데이터 생성
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
    df['MA20'] = df['close'].rolling(20).mean()
    df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
    df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
    df['Disparity_20'] = (df['close'] / df['MA20']) * 100

    df['High_Tail'] = df['high'] - df[['open', 'close']].max(axis=1)
    df['Low_Tail'] = df[['open', 'close']].min(axis=1) - df['low']
    df['Buying_Pressure'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
    
    df['Market_Return_1m'] = df['time'].map(market_dict).fillna(0.0)

    df['future_max_10'] = df['close'].rolling(window=10).max().shift(-10)
    df['Target_Buy'] = np.where(df['future_max_10'] >= df['close'] * 1.01, 1, 0)

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
        
        # 메인 프로세스에서 사용할 API 객체 생성 및 토큰 발급
        self.api = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        self.api.get_access_token()
        self.market_dict = {} 

    def send_log(self, msg, log_type="INFO"):
        if self.log_callback: self.log_callback(msg, log_type)
        else: print(f"[{log_type}] {msg}") 
        try: self.db.insert_log(log_type.upper(), msg)
        except: pass

    def run_collection(self, stock_list):
        # 1. 토큰 정상 발급 확인
        if not self.api.access_token:
            self.send_log("🚨 토큰 발급 실패! 1분 뒤에 다시 시도하세요.", "ERROR")
            return "FAILED"

        self.db.update_system_status('COLLECTOR', '지수 데이터 준비 중', 0)

        # 2. 공통 지수 데이터 수집
        market_ticker = '114800' if SystemConfig.MARKET_MODE == "DOMESTIC" else 'QQQ'
        m_df = fetch_data_logic(self.api, market_ticker, is_market_index=True)
        if m_df is not None:
            m_df['Market_Return_1m'] = m_df['close'].pct_change() * 100
            self.market_dict = dict(zip(m_df['time'], m_df['Market_Return_1m'].fillna(0)))

        # 3. 멀티프로세싱 실행
        total_stocks = len(stock_list)
        accumulated_rows = 0
        self.send_log(f"🔥 병렬 사냥 시작 (토큰 공유 모드 가동)", "INFO")

        # 공유할 토큰 추출
        shared_token = self.api.access_token

        with ProcessPoolExecutor(max_workers=5) as executor:
            # 🔥 [수정] shared_token을 모든 워커에게 전달합니다.
            futures = {
                executor.submit(
                    collect_worker, code, self.app_key, self.app_secret, 
                    self.account_no, self.is_mock, shared_token, self.market_dict
                ): code for code in stock_list
            }

            for idx, future in enumerate(as_completed(futures)):
                code = futures[future]
                try:
                    rows = future.result()
                    accumulated_rows += rows
                    
                    if (idx + 1) % 10 == 0:
                        progress = int(((idx + 1) / total_stocks) * 100)
                        self.send_log(f"💾 [{idx+1}/{total_stocks}] '{code}' 완료 (누적 {accumulated_rows:,}줄)", "INFO")
                        self.db.update_system_status('COLLECTOR', '수집 중...', progress)
                except Exception as e:
                    self.send_log(f"⚠️ [{code}] 워커 에러: {e}", "WARNING")

        self.db.update_system_status('COLLECTOR', '수집 완료!', 100)
        self.send_log(f"💎 총 {accumulated_rows:,}줄 저장 완료!", "SUCCESS")
        return "SUCCESS"

if __name__ == "__main__":
    # --- 설정 값 (유저 정보 유지) ---
    APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    ACCOUNT = "50172151"

    print("📡 종목 리스트 추출 중...")
    df_market = fdr.StockListing('KRX')
    top_df = df_market.sort_values('Marcap', ascending=False).head(1000)
    stock_list = top_df['Code'].astype(str).str.zfill(6).tolist()

    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    collector.run_collection(stock_list)