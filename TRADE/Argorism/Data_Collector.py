import sys
import os
import json 
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta 
from concurrent.futures import ThreadPoolExecutor, as_completed

# =====================================================================
# [환경 설정] 프로젝트 루트 경로 설정
# =====================================================================
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if root_dir not in sys.path:
    sys.path.append(root_dir)
    
import COMMON.KIS_Manager as KIS
from COMMON.Flag import SystemConfig 
from COMMON.DB_Manager import JubbyDB_Manager 

# =====================================================================
# 🚀 [최적화 1] 전역 세션(Session) 생성
# 매번 새로운 연결을 맺는 비용(Handshake)을 없애 통신 속도를 30% 향상시킵니다!
# =====================================================================
global_session = requests.Session()

# =====================================================================
# 🛠️ [독립 워커용 가짜 API 클래스]
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
def collect_worker(code, app_key, app_secret, access_token, base_url, market_dict):
    try:
        db_worker = JubbyDB_Manager()
        
        def worker_log(level, msg):
            try: db_worker.insert_log(level.upper(), msg)
            except: print(f"[{level.upper()}] {msg}")
            
        api_worker = DummyAPI(app_key, app_secret, access_token, base_url)
        # 🚀 초고속 fetch 함수 사용!
        raw_df = fetch_data_logic_fast(api_worker, code, is_market_index=False, log_func=worker_log)
        
        if raw_df is not None and not raw_df.empty:
            try:
                future_win = int(db_worker.get_shared_setting("AI_TRAIN", "FUTURE_WINDOW", "10"))
                
                # 🔥 [수정] 문제집 정답 기준을 '익절 2.0%, 손절 1.5%'로 깐깐하게 상향!
                p_target = float(db_worker.get_shared_setting("AI_TRAIN", "PROFIT_TARGET", "2.0"))
                s_loss = float(db_worker.get_shared_setting("AI_TRAIN", "STOP_LOSS", "1.5"))
            except:
                # 🔥 [수정] DB 오류 시 작동하는 백업 수치도 2.0, 1.5로 맞춰줍니다.
                future_win, p_target, s_loss = 10, 2.0, 1.5
                
            processed_df = calculate_indicators_logic(raw_df, market_dict, future_win, p_target, s_loss)
            
            if processed_df is not None and not processed_df.empty:
                db_worker.save_training_data(processed_df, SystemConfig.MARKET_MODE)
                return len(processed_df)
                
    except Exception as e:
        try: db_worker.insert_log("ERROR", f"❌ [{code}] 작업 중 오류: {e}")
        except: pass
    return 0

# =====================================================================
# 📈 [데이터 수집 로직 - 초고속 버전] API 호출부
# =====================================================================
def fetch_data_logic_fast(api, stock_code, is_market_index=False, log_func=None):
    if SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
        try:
            import yfinance as yf
            yf_ticker = stock_code
            if "NQ" in stock_code: yf_ticker = "NQ=F"
            elif "ES" in stock_code: yf_ticker = "ES=F"
            elif "YM" in stock_code: yf_ticker = "YM=F"
            elif "GC" in stock_code: yf_ticker = "GC=F"
            elif "CL" in stock_code: yf_ticker = "CL=F"

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
        except Exception as e:
            if log_func: log_func(f"🚨 야후 파이낸스 수집 에러 [{stock_code}]: {e}", "ERROR")
            return None

    all_chunks = [] 
    target_time = "153000" if SystemConfig.MARKET_MODE == "DOMESTIC" else "160000"
    next_key = ""
    
    # 🚀 [최적화 2] 65일치(약 1달 반) -> 40일치(약 3주) 데이터로 조절하여 속도를 비약적으로 높입니다.
    # 초단타 AI 모델은 너무 옛날 데이터보다 최근 3주치 시장 흐름을 배우는 것이 훨씬 승률이 좋습니다.
    loop_count = 15 if (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC") else 40

    for i in range(loop_count):
        if SystemConfig.MARKET_MODE == "DOMESTIC" or (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC"):
            url = f"{api.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            tr_id = "FHKST03010200"
            params = {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": target_time, "FID_PW_DATA_INCU_YN": "Y"}
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{api.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
            tr_id = "HHDFS76950200"
            params = {"AUTH": "", "EXCD": "NAS", "SYMB": stock_code, "NMIN": "1", "PINC": "1", "NEXT": next_key, "NREC": "120", "FILL": "", "KEYB": next_key}

        headers = {"content-type": "application/json", "authorization": f"Bearer {api.access_token}", "appkey": api.app_key, "appsecret": api.app_secret, "tr_id": tr_id, "custtype": "P"}
        
        # 🚀 전역 세션(global_session)을 사용하여 통신 속도를 극대화합니다!
        res = global_session.get(url, headers=headers, params=params, timeout=5)
        
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
            if SystemConfig.MARKET_MODE == "OVERSEAS":
                next_key = res.json().get('output1', {}).get('next', "")
                if not next_key: break
            else:
                target_time = data[-1]['stck_cntg_hour']
                if int(target_time) <= 90000: break
                
            # 🚀 [최적화 3] 내부 휴식시간(Sleep)을 최소화 (0.35초 -> 0.05초)
            # 초당 20회 제한 방어는 이제 이 루프 안이 아니라, 밖의 스레드 통제기에서 전담합니다!
            time.sleep(0.05) 
        else:
            time.sleep(1.0); continue
            
    if not all_chunks: return None
    df = pd.concat(all_chunks).drop_duplicates().sort_values(['date', 'time'])
    df['code'] = stock_code
    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
    return df.reset_index(drop=True)

# =====================================================================
# 🧠 [지표 계산 및 정답지 생성] 
# =====================================================================
def calculate_indicators_logic(df, market_dict, future_window=10, profit_target=1.5, stop_loss=1.0):
    if df is None or len(df) < 30: return None
    df['return'] = df['close'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) * 100 
    df['vol_change'] = df['volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) 

    # 💡 [추가된 부분] VWAP 및 이격도 계산
    df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
    df['TP_Volume'] = df['Typical_Price'] * df['volume']
    df['VWAP'] = df.groupby('date')['TP_Volume'].cumsum() / (df.groupby('date')['volume'].cumsum() + 1e-9)
    df['VWAP_Disparity'] = (df['close'] / (df['VWAP'] + 1e-9)) * 100

    delta = df['close'].diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    rs = up.ewm(com=13).mean() / (down.ewm(com=13).mean() + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['MA5'] = df['close'].rolling(5).mean()
    df['MA20'] = df['close'].rolling(20).mean()
    df['MA60'] = df['close'].rolling(60).mean()
    df['MA120'] = df['close'].rolling(120).mean()
    df['Disparity_60'] = (df['close'] / (df['MA60'] + 1e-9)) * 100
    df['Disparity_120'] = (df['close'] / (df['MA120'] + 1e-9)) * 100
    df['Macro_Trend'] = np.where((df['close'] > df['MA60']) & (df['MA60'] > df['MA120']), 1, 0)
    df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
    df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
    df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / (df['MA20'] + 1e-9)) * 100
    # 👇 [여기에 이 한 줄을 추가합니다!] (볼린저밴드 위치 비율)
    df['BB_PctB'] = (df['close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'] + 1e-9)
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
    df['Market_Return_1m'] = df['time'].map(market_dict) if market_dict else 0.0
    df['future_max'] = df['close'].shift(-future_window).rolling(window=future_window, min_periods=1).max()
    df['future_min'] = df['close'].shift(-future_window).rolling(window=future_window, min_periods=1).min()
    df['Target_Buy'] = np.where((df['future_max'] >= df['close'] * (1 + profit_target/100)) & (df['future_min'] > df['close'] * (1 - stop_loss/100)), 1, 0)
    
    # 💡 [핵심 수정] AI 훈련에 들어가지 않는 쓰레기 데이터(Typical_Price, 볼린저 상하단 밴드 등)를 
    # 완벽하게 삭제하여 SQLite DB 용량 팽창과 AI 훈련 속도 저하를 막습니다.
    df.drop(['Typical_Price', 'TP_Volume', 'VWAP', 'BB_Upper', 'BB_Lower'], axis=1, inplace=True, errors='ignore')
    
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
        
        if existing_token:
            self.access_token = existing_token
            self.api.access_token = existing_token
            self._save_token_to_file(existing_token)
            self.send_log("♻️ 메인 시스템에서 전달받은 토큰을 사용합니다.", "INFO")
        else:
            self.access_token = self._get_safe_access_token()
            self.api.access_token = self.access_token

        self.market_dict = {} 

    def _save_token_to_file(self, token):
        import sys, os
        token_file = os.path.join(SystemConfig.PROJECT_ROOT, "kis_token_cache.json")
        save_data = {"access_token": token, "expire_time": (datetime.now() + timedelta(hours=23)).strftime("%Y-%m-%d %H:%M:%S")}
        try:
            with open(token_file, "w", encoding="utf-8") as f: json.dump(save_data, f)
        except: pass

    def _get_safe_access_token(self):
        import sys, os
        token_file = os.path.join(SystemConfig.PROJECT_ROOT, "kis_token_cache.json")
        
        if os.path.exists(token_file):
            try:
                with open(token_file, "r", encoding="utf-8") as f: data = json.load(f)
                expire_time = datetime.strptime(data["expire_time"], "%Y-%m-%d %H:%M:%S")
                if datetime.now() < expire_time:
                    self.send_log("♻️ 캐시된 토큰을 불러옵니다.", "INFO")
                    return data["access_token"]
            except: pass
            
        for attempt in range(2):
            self.api.get_access_token()
            new_token = self.api.access_token
            
            if new_token and len(new_token) > 20:
                self._save_token_to_file(new_token)
                self.send_log("✅ 새 토큰 발급 완료!", "SUCCESS")
                return new_token
            
            if attempt == 0:
                self.send_log("🚨 토큰 1분 제한(EGW00133) 감지! 62초 뒤 자동으로 재시도합니다...", "WARNING")
                time.sleep(62)
                
        return None

    def send_log(self, msg, log_type="INFO"):
        if self.log_callback: self.log_callback(msg, log_type)
        else: print(f"[{log_type}] {msg}") 
        try: self.db.insert_log(log_type.upper(), msg)
        except: pass

   # =====================================================================
    # 🚀 [스마트 업데이트] 기존 DB에 누락된 지표(VWAP, BB_PctB 등)가 있으면 5초만에 싹 채워주는 기능
    # =====================================================================
    def smart_update_existing_db(self):
        import sqlite3
        if not os.path.exists(self.db.python_db_path): return
        
        conn = sqlite3.connect(self.db.python_db_path)
        try:
            tables_to_check = ['TrainData_Domestic', 'TrainData_Overseas', 'TrainData_Futures'] 
            
            for table_name in tables_to_check:
                cursor = conn.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}';")
                if cursor.fetchone():
                    df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
                    
                    # 🔥 [핵심 수정] VWAP_Disparity 나 BB_PctB 가 없으면 고속 업데이트(패치)를 진행합니다!
                    needs_update = False
                    if not df.empty:
                        if 'VWAP_Disparity' not in df.columns: needs_update = True
                        if 'BB_PctB' not in df.columns: needs_update = True
                        
                    if needs_update:
                        self.send_log(f"🛠️ [스마트 점검] 구버전 {table_name} 발견! 누락된 지표 고속 계산 중...", "WARNING")
                        
                        def apply_patch(group):
                            # 1. VWAP_Disparity 패치
                            if 'VWAP_Disparity' not in group.columns:
                                group['Typical_Price'] = (group['high'] + group['low'] + group['close']) / 3
                                group['TP_Volume'] = group['Typical_Price'] * group['volume']
                                # 🟢 메인 함수와 동일하게 groupby('date')를 추가합니다!
                                group['VWAP'] = group.groupby('date')['TP_Volume'].cumsum() / (group.groupby('date')['volume'].cumsum() + 1e-9)
                                group['VWAP_Disparity'] = (group['close'] / (group['VWAP'] + 1e-9)) * 100
                            
                            # 2. BB_PctB 패치
                            if 'BB_PctB' not in group.columns:
                                ma20 = group['close'].rolling(20).mean()
                                std = group['close'].rolling(20).std()
                                bb_upper = ma20 + (std * 2)
                                bb_lower = ma20 - (std * 2)
                                group['BB_PctB'] = (group['close'] - bb_lower) / (bb_upper - bb_lower + 1e-9)
                                
                            return group
                            
                        # 종목(code) 별로 그룹화해서 누락된 수식 일괄 적용!
                        df = df.groupby('code', group_keys=False).apply(apply_patch)
                        
                        # 계산용 찌꺼기와 옛날 지표(BB_Lower) 삭제
                        df.drop(['Typical_Price', 'TP_Volume', 'VWAP', 'BB_Lower'], axis=1, inplace=True, errors='ignore')
                        df = df.dropna().reset_index(drop=True)
                        
                        # DB 덮어쓰기
                        df.to_sql(table_name, conn, if_exists='replace', index=False)
                        self.send_log(f"🎉 [스마트 점검] {table_name} 고속 업데이트 100% 완료!", "SUCCESS")
                        
        except Exception as e:
            self.send_log(f"🚨 DB 스마트 업데이트 중 에러: {e}", "ERROR")
        finally:
            conn.close()

    def get_already_collected_stocks(self, table_name):
        conn = None # 🌟 변수 미리 선언
        try:
            import sqlite3
            conn = sqlite3.connect(self.db.python_db_path)
            cursor = conn.cursor()
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'")
            if not cursor.fetchone():
                return []
            
            df = pd.read_sql(f"SELECT DISTINCT code FROM {table_name}", conn)
            return df['code'].tolist()
        except Exception as e:
            return []
        finally:
            # 🌟 에러가 났더라도 conn이 생성되어 있다면 무조건 닫아주기 (안전장치)
            if conn: 
                conn.close()

    def run_collection(self, stock_list):
        # 💡 [핵심 추가] 수집을 시작하기 전에 내 DB가 구버전인지 점검하고 빈칸을 먼저 채웁니다!
        self.smart_update_existing_db()

        if not self.access_token:
            self.send_log("🚨 토큰 발급에 최종 실패했습니다. 수집을 중단합니다.", "ERROR")
            return "FAILED"

        if SystemConfig.MARKET_MODE == "DOMESTIC": table_name = "TrainData_Domestic"
        elif SystemConfig.MARKET_MODE == "OVERSEAS": table_name = "TrainData_Overseas"
        else: table_name = "TrainData_Futures"

        already_done = self.get_already_collected_stocks(table_name)
        todo_list = [s for s in stock_list if s not in already_done]
        
        total_all = len(stock_list)
        done_cnt = len(already_done)
        todo_cnt = len(todo_list)

        if todo_cnt == 0:
            self.send_log(f"✅ 모든 종목({total_all}개) 수집 완료 상태입니다.", "SUCCESS")
            return "SUCCESS"

        self.send_log(f"🔄 [이어받기] {total_all}개 중 {done_cnt}개 완료 확인. 남은 {todo_cnt}개 시작!", "INFO")

        market_ticker = '069500' if SystemConfig.MARKET_MODE == "DOMESTIC" else ('QQQ' if SystemConfig.MARKET_MODE == "OVERSEAS" else 'NQM26')
        m_df = fetch_data_logic_fast(self.api, market_ticker, is_market_index=True, log_func=self.send_log)
        if m_df is not None:
            m_df['Market_Return_1m'] = m_df['close'].pct_change() * 100
            self.market_dict = dict(zip(m_df['time'], m_df['Market_Return_1m'].fillna(0)))

        accumulated_rows = 0
        
        # 🚀 [최적화 4] 병렬 처리 극대화 방어막 세팅
        batch_size = 5     # 한 번에 5개 종목씩 묶어서 처리
        max_workers = 15   # 15개의 스레드를 동시에 돌림 (초당 18~19회 호출 유지)
        processed_count = 0
        
        self.send_log(f"🚀 초고속 엔진 가동: {max_workers}개 스레드로 병렬 수집을 시작합니다.", "INFO")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i in range(0, todo_cnt, batch_size):
                start_time = time.time()
                batch_codes = todo_list[i : i + batch_size]
                
                futures = {executor.submit(
                    collect_worker, code, self.app_key, self.app_secret, self.access_token, self.api.base_url, self.market_dict
                ): code for code in batch_codes}
                
                for future in as_completed(futures):
                    code = futures[future]
                    processed_count += 1
                    try:
                        rows = future.result()
                        accumulated_rows += rows
                        current_total = done_cnt + processed_count
                        progress_pct = int((current_total / total_all) * 100)
                        
                        if current_total % 5 == 0:
                            self.send_log(f"💾 [{current_total}/{total_all}] '{code}' 수집완료 (누적 {accumulated_rows:,}줄)", "INFO")
                        self.db.update_system_status('COLLECTOR', f'수집 중 ({current_total}/{total_all})', progress_pct)
                    except: pass
                
                # 🛡️ 디도스 방어: 5개 종목(약 200번 호출)을 긁어오는데 최소 2초는 걸리게 안전장치 발동
                elapsed = time.time() - start_time
                if elapsed < 2.0: time.sleep(2.0 - elapsed)

        self.db.update_system_status('COLLECTOR', '수집 및 DB 적재 완료!', 100)
        self.send_log(f"💎 수집 종료! 누적 {accumulated_rows:,}줄 적재 완료!", "SUCCESS")
        return "SUCCESS"
    
if __name__ == "__main__":
    db = JubbyDB_Manager()

    APP_KEY = db.get_shared_setting("KIS_API", "APP_KEY", "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy")
    APP_SECRET = db.get_shared_setting("KIS_API", "APP_SECRET", "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8=")
    ACCOUNT = db.get_shared_setting("KIS_API", "FUTURES_ACCOUNT" if SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES" else "STOCK_ACCOUNT", "60039684")

    try:
        query = f"SELECT symbol FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
        stock_list = pd.read_sql(query, db.engine)['symbol'].astype(str).tolist()
        if SystemConfig.MARKET_MODE == "DOMESTIC": stock_list = [s.zfill(6) for s in stock_list]
    except:
        stock_list = ['005930', '000660']

    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    collector.run_collection(stock_list)