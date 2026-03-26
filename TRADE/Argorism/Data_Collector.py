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
        # 프로세스마다 독립적인 DB 매니저 생성
        db_worker = JubbyDB_Manager()
        
        # 🔥 [수정] print 대신 UI 로그창으로 바로 쏘는 내부 함수 생성
        def worker_log(level, msg):
            try: db_worker.insert_log(level.upper(), msg)
            except: print(f"[{level.upper()}] {msg}")
            
        api_worker = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        api_worker.access_token = access_token
        
        # 1. API 통신으로 데이터 수집 (로그 쏘는 함수도 같이 넘겨줍니다)
        raw_df = fetch_data_logic(api_worker, code, is_market_index=False, log_func=worker_log)
        
        if raw_df is not None and not raw_df.empty:
            processed_df = calculate_indicators_logic(raw_df, market_dict)
            if processed_df is not None and not processed_df.empty:
                db_worker.save_training_data(processed_df, SystemConfig.MARKET_MODE)
                return len(processed_df)
                
    except Exception as e:
        # 에러도 UI 로그창으로 전송
        try: db_worker.insert_log("ERROR", f"❌ [{code}] 작업 중 오류: {e}")
        except: pass
    return 0

# =====================================================================
# 📈 [데이터 수집 로직] API 호출부 (국내 / 해외 / 🚀해외선물 통합)
# =====================================================================
def fetch_data_logic(api, stock_code, is_market_index=False, log_func=None):
    all_chunks = [] 
    target_time = "153000" if SystemConfig.MARKET_MODE == "DOMESTIC" else "160000"
    next_key = ""
    
    loop_count = 15 if (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC") else 65

    for i in range(loop_count):
        if SystemConfig.MARKET_MODE == "DOMESTIC" or (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC"):
            url = f"{api.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            tr_id = "FHKST03010200"
            params = {
                "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", 
                "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": target_time, "FID_PW_DATA_INCU_YN": "Y"
            }
            
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{api.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
            tr_id = "HHDFS76950200"
            params = {
                "AUTH": "", "EXCD": "NAS", "SYMB": stock_code, "NMIN": "1", "PINC": "1", 
                "NEXT": next_key, "NREC": "120", "FILL": "", "KEYB": next_key
            }
            
        elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
            # ⚠️ 해외선물 API 엔드포인트 및 TR_ID (임시 적용값)
            url = f"{api.base_url}/uapi/overseas-futureoption/v1/quotations/inquire-time-itemchartprice"
            tr_id = "HHDFS76950200" 
            params = {
                "SYMB": stock_code, "NMIN": "1", "NREC": "120", 
                "NEXT": next_key, "KEYB": next_key
            }

        headers = {
            "content-type": "application/json", 
            "authorization": f"Bearer {api.access_token}",
            "appkey": api.app_key, "appsecret": api.app_secret, "tr_id": tr_id, "custtype": "P"
        }

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

            if SystemConfig.MARKET_MODE in ["OVERSEAS", "OVERSEAS_FUTURES"]:
                next_key = res.json().get('output1', {}).get('next', "")
                if not next_key: break
            else:
                target_time = data[-1]['stck_cntg_hour'] 
                if int(target_time) <= 90000: break
            
            time.sleep(0.35) 
        else:
            # 🔥 [마법의 코드] HTML 태그의 '<', '>' 기호를 텍스트로 치환하여 UI가 웹페이지로 오해하지 못하게 만듭니다!
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
            
    if not all_chunks: return None
    df = pd.concat(all_chunks).drop_duplicates().sort_values(['date', 'time'])
    df['code'] = stock_code
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
    return df.reset_index(drop=True)

# =====================================================================
# 🧠 [지표 계산 로직] AI 학습용 데이터 생성 (15가지 고급 지표 완벽 복원!)
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
    
    # -----------------------------------------------------
    # 🔥 [복원] 누락되었던 5가지 고급 지표 추가 로직
    # -----------------------------------------------------
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    
    df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
    df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
    
    # 1. 볼린저밴드 폭 (BB_Width)
    df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / df['MA20']) * 100
    
    # 2. 5분 이격도 (Disparity_5)
    df['Disparity_5'] = (df['close'] / df['MA5']) * 100
    df['Disparity_20'] = (df['close'] / df['MA20']) * 100

    # 3. 거래량 에너지 (Vol_Energy: 20분 평균 대비 현재 거래량 폭발 여부)
    df['Vol_Energy'] = df['volume'] / (df['volume'].rolling(20).mean() + 1e-9)

    # 4. OBV 트렌드 (OBV_Trend: 매수/매도 압력 누적치)
    direction = np.where(df['close'] > df['close'].shift(1), 1, -1)
    direction = np.where(df['close'] == df['close'].shift(1), 0, direction)
    obv = (df['volume'] * direction).cumsum()
    df['OBV_Trend'] = obv.pct_change().replace([np.inf, -np.inf], 0).fillna(0)

    # 5. ATR (Average True Range: 캔들의 변동성/길이)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    df['ATR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()
    # -----------------------------------------------------

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
            self.send_log("🚨 토큰 발급 실패! 1분 뒤에 다시 시도하세요.", "ERROR")
            return "FAILED"

        self.db.update_system_status('COLLECTOR', '지수 데이터 준비 중', 0)

        # 🔥 본격적인 수집 전, 낡은 DB 테이블을 깨끗하게 파기합니다!
        self.send_log("🧹 이전 수집된 낡은 데이터를 파기하고 새 노트를 준비합니다...", "INFO")
        if SystemConfig.MARKET_MODE == "DOMESTIC": table_name = "TrainData_Domestic"
        elif SystemConfig.MARKET_MODE == "OVERSEAS": table_name = "TrainData_Overseas"
        else: table_name = "TrainData_Futures"

        conn = self.db._get_connection(self.db.python_db_path)
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            conn.commit()
        except Exception as e:
            pass
        finally:
            conn.close()

        # 📊 [시장 대장주 셋팅] 모드에 따라 지표 종목 분기
        if SystemConfig.MARKET_MODE == "DOMESTIC": market_ticker = '069500' 
        elif SystemConfig.MARKET_MODE == "OVERSEAS": market_ticker = 'QQQ'  
        elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES": market_ticker = 'NQM26' 

        self.send_log(f"📉 기준 시장 지표({market_ticker}) 데이터를 수집합니다...", "INFO")
        
        # 지수 데이터 수집 시에도 로그 함수(self.send_log)를 넘겨줍니다.
        m_df = fetch_data_logic(self.api, market_ticker, is_market_index=True, log_func=self.send_log)
        
        if m_df is not None:
            m_df['Market_Return_1m'] = m_df['close'].pct_change() * 100
            self.market_dict = dict(zip(m_df['time'], m_df['Market_Return_1m'].fillna(0)))
        else:
            self.send_log(f"⚠️ 대장주({market_ticker}) 수집 실패! 개별 종목 수집만 진행합니다.", "WARNING")

        total_stocks = len(stock_list)
        accumulated_rows = 0
        self.send_log(f"🔥 [{SystemConfig.MARKET_MODE}] 총 {total_stocks}개 종목 병렬 사냥 시작!", "INFO")

        shared_token = self.api.access_token

        # 병렬 작업 코어 수 축소 (속도 제한 우회)
        with ProcessPoolExecutor(max_workers=3) as executor:
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
                    
                    if (idx + 1) % 1 == 0 or (idx + 1) == total_stocks: # 1종목마다 로그 띄우기
                        progress = int(((idx + 1) / total_stocks) * 100)
                        self.send_log(f"💾 [{idx+1}/{total_stocks}] '{code}' DB 적재 완료 (누적 {accumulated_rows:,}줄)", "INFO")
                        self.db.update_system_status('COLLECTOR', 'DB 적재 중...', progress)
                except Exception as e:
                    self.send_log(f"⚠️ [{code}] 워커 에러: {e}", "WARNING")

        self.db.update_system_status('COLLECTOR', '수집 및 DB 적재 완료!', 100)
        self.send_log(f"💎 SQL DB에 총 {accumulated_rows:,}줄 적재 완료!", "SUCCESS")
        return "SUCCESS"

if __name__ == "__main__":
    # --- 설정 값 ---
    APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    ACCOUNT = "50172151"

    print("📡 [DB 연동] 데이터베이스에서 종목 리스트를 추출합니다...")
    db = JubbyDB_Manager()
    
    # 🔥 [CSV 걷어내기 2] CSV 파일이나 외부 라이브러리(fdr) 대신 순수하게 SQL에서 명단을 가져옵니다!
    try:
        # DB에 저장된 타겟 종목 테이블을 읽어옵니다. (테이블 이름은 DB_Manager 구조에 맞게 조율)
        query = f"SELECT symbol FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
        stock_list_df = pd.read_sql(query, db.engine)
        stock_list = stock_list_df['symbol'].astype(str).tolist()
        
        # 국내 주식의 경우 종목코드가 6자리여야 하므로 앞의 0을 채워줍니다.
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            stock_list = [str(s).zfill(6) for s in stock_list]
            
        print(f"✅ DB에서 {len(stock_list)}개 종목 명단 로드 완료!")
        
    except Exception as e:
        print(f"⚠️ DB에서 종목 리스트를 불러오지 못했습니다. (사유: {e})")
        # DB 테이블이 비어있거나 아직 생성 전일 때를 대비한 백업 하드코딩 명단
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            stock_list = ['005930', '000660', '035420'] # 삼성, SK하이닉스, 네이버
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            stock_list = ['AAPL', 'MSFT', 'TSLA']
        else: # OVERSEAS_FUTURES
            stock_list = ['NQ', 'ES', 'CL', 'GC']
        print(f"임시 명단으로 진행합니다: {stock_list}")

    # 본격적인 수집 시작
    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    collector.run_collection(stock_list)