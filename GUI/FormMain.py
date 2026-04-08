# =====================================================================
# 📦 [1단계] 마법의 도구 상자 열기 (필요한 부품들을 가져옵니다)
# =====================================================================
import sys
import os                  
# 🔥 [핵심 설정] AI 라이브러리(머신러닝)와 화면(PyQt5)이 동시에 작업을 처리하려다 
# 메모리 락(Lock)이 걸려 컴퓨터가 뻗어버리는(팅기는) 현상을 억지로 막아주는 마법의 설정입니다.
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True' 

import time                
import random              
import joblib              
import pandas as pd        
import numpy as np         
import requests # 카카오톡으로 주삐의 알림을 보내기 위한 외부 통신 도구
from datetime import datetime 
from PyQt5 import QtWidgets, uic, QtCore, QtGui  
from PyQt5.QtCore import Qt, QThread, pyqtSignal 

from COMMON.Flag import TradeData            
from COMMON.KIS_Manager import KIS_Manager   

# 💡 [구조 변경 완료] 기존 TCP 소켓 통신을 삭제하고, 
# 이제 모든 데이터는 DB(SQLite)를 통해 C# UI와 빠르고 안전하게 공유합니다.
from COMMON.Flag import SystemConfig
from COMMON.DB_Manager import JubbyDB_Manager

# 🛠️ AI 뇌를 활용해 언제 사고 팔지 판단하는 핵심 전략 엔진을 불러옵니다.
from TRADE.Argorism.Strategy import JubbyStrategy 
from GUI.FormTicker import FormTicker

import warnings
warnings.filterwarnings("ignore", category=UserWarning) 

# =====================================================================
# 📂 [경로 탐색기] 실행 파일(exe)로 만들었을 때도 파일을 잘 찾도록 도와주는 함수들
# =====================================================================
def get_smart_path(filename):
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
        return os.path.join(base_path, filename)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, filename)

def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# =====================================================================
# 🖥️ [로그 가로채기] 파이썬 에러 폭주 시 튕김 방지 처리 추가
# =====================================================================
class OutputLogger(QtCore.QObject):
    emit_log = QtCore.pyqtSignal(str) 
    def write(self, text):
        try: # 🔥 강제 종료 시 에러 텍스트를 그리려다 튕기는 것을 막아줍니다.
            if text.strip(): self.emit_log.emit(text.strip())
        except: pass
    def flush(self): pass


# =====================================================================
# 📡 [일꾼 1호] 종목 수집기
# =====================================================================
class DataCollectorWorker(QThread):
    sig_log = pyqtSignal(str, str) 
    
    def __init__(self, app_key, app_secret, account_no, is_mock):
        super().__init__()
        self.real_app_key = app_key
        self.real_app_secret = app_secret
        self.account_no = account_no
        self.is_mock = is_mock

    def run(self):
        print("\n▶️ [수집기] DataCollectorWorker 수사 시작!", flush=True)
        import traceback
        try:
            try: from TRADE.Argorism.Data_Collector import UltraDataCollector
            except: from TRADE.Argorism.Data_Collector import UltraDataCollector
            import FinanceDataReader as fdr
            
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            stock_list = []; name_list = []
            
            if SystemConfig.MARKET_MODE == "DOMESTIC":
                self.emit_log("📡 한국 거래소(KRX) 전체 정상 종목 탐색 중...", "info")
                df_market = fdr.StockListing('KRX')

                if df_market is None or df_market.empty:
                    df_market = pd.concat([fdr.StockListing('KOSPI'), fdr.StockListing('KOSDAQ')], ignore_index=True)

                for col in ['Close', 'Amount', 'Volume']:
                    if col in df_market.columns:
                        df_market[col] = pd.to_numeric(df_market[col].astype(str).str.replace(r'[^0-9.]', '', regex=True), errors='coerce').fillna(0)

                top_df = df_market[(df_market['Close'] >= 1000) & (df_market['Amount'] > 0)]

                code_col = 'Code' if 'Code' in top_df.columns else 'Symbol'
                stock_list = top_df[code_col].astype(str).str.zfill(6).tolist()
                name_list = top_df['Name'].tolist()

            elif SystemConfig.MARKET_MODE == "OVERSEAS":
                self.emit_log("📡 미국 나스닥(NASDAQ) 정상 종목 전체 추출 중...", "info")
                df_market = fdr.StockListing('NASDAQ')
                top_df = df_market.head(3000) 
                stock_list = top_df['Symbol'].astype(str).tolist()
                name_list = top_df['Name'].tolist()
                
            elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
                self.emit_log("📡 해외선물(CME) 종목 설정 중...", "info")
                futures_list = [
                    {"Code": "NQM26", "Name": "나스닥 100 미니"}, 
                    {"Code": "ESM26", "Name": "S&P 500 미니"},
                    {"Code": "CLM26", "Name": "크루드 오일"}
                ]
                top_df = pd.DataFrame(futures_list)
                stock_list = top_df['Code'].tolist()
                name_list = top_df['Name'].tolist()

            if stock_list:
                db_worker = JubbyDB_Manager()
                df_db = pd.DataFrame({'symbol': stock_list, 'symbol_name': name_list, 'market_mode': SystemConfig.MARKET_MODE})
                conn = db_worker._get_connection(db_worker.shared_db_path)
                try:
                    conn.execute(f"DELETE FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'")
                    # 🌟 똑같은 conn 변수를 재사용하여 테이블이 잠기는(Lock) 현상을 완벽 차단!
                    df_db.to_sql('target_stocks', con=conn, if_exists='append', index=False)
                    conn.commit()
                    self.sig_log.emit(f"▶️ [수집기] DB에 {len(stock_list)}개 명단 저장 완료!", "info")
                except Exception as e:
                    self.sig_log.emit(f"🔥 [수집기] DB 저장 에러: {e}", "error")
                finally:
                    # 🌟 아무리 에러가 나더라도 사용이 끝난 DB 통로는 반드시 닫아줍니다 (메모리 누수 차단)
                    conn.close()
                    
                self.emit_log(f"✅ AI 학습용 빅데이터 타겟 {len(stock_list)}개 확정!", "success")
            else: return

            collector = UltraDataCollector(self.real_app_key, self.real_app_secret, self.account_no, self.is_mock, log_callback=self.emit_log)
            collector.run_collection(stock_list)
            self.emit_log("📡 [수집기] 모든 데이터 수집 및 분석이 완료되었습니다.", "success")
            
        except Exception as e: 
            traceback.print_exc()
            self.emit_log(f"🚨 수집기 치명적 에러: {e}", "error")
            
    def emit_log(self, msg, level="info"): self.sig_log.emit(msg, level)


# =====================================================================
# 🧠 [일꾼 2호] AI 학습기
# =====================================================================
class AITrainerWorker(QThread):
    sig_log = pyqtSignal(str, str)
    def run(self):
        self.emit_log("🛡️ [시스템] 프로그램 팅김 방지를 위해 안전한 스레드에서 AI 학습을 시작합니다...", "info")
        try:
            from TRADE.Argorism.Jubby_AI_Trainer import train_jubby_brain
            train_jubby_brain(log_callback=self.emit_log)
            self.emit_log("✅ AI 뇌(Model) 학습 및 저장이 완벽하게 끝났습니다! 자동매매를 시작하셔도 좋습니다.", "success")
        except Exception as e: 
            self.emit_log(f"🚨 AI 학습 프로세스 생성 오류: {e}", "error")
            
    def emit_log(self, msg, level="info"): self.sig_log.emit(msg, level)

# =====================================================================
# 🕵️‍♂️ [전담반] 주삐 탐정 스레드 (5초마다 미체결 강제 동기화)
# =====================================================================
class DetectiveWorker(QThread):
    sig_log = pyqtSignal(str, str)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.is_running = True

    def run(self):
        self.sig_log.emit("🕵️‍♂️ [주삐 탐정] 24시간 미체결 감시 전담반 가동 시작!", "info")
        while self.is_running:
            time.sleep(5.0) # 5초마다 끈질기게 감시
            try: self.cross_check_logic()
            except Exception: pass

    def cross_check_logic(self):
        unfilled_orders = []
        # 🌟 [병목 해결] SELECT 작업 후 0.1초 만에 즉시 연결 끊기 (락 원천 차단)
        try:
            conn = self.mw.db._get_connection(self.mw.db.shared_db_path)
            cursor = conn.execute("SELECT order_no, symbol, type, quantity, price, time FROM TradeHistory WHERE Status = '미체결'")
            unfilled_orders = cursor.fetchall()
        except: return
        finally:
            if 'conn' in locals() and conn: conn.close()

        if not unfilled_orders: return
        
        try: real_holdings = self.mw.api_manager.get_real_holdings()
        except: real_holdings = {}

        for order_no, symbol, o_type, qty, price, order_time_str in unfilled_orders:
            stock_name = self.mw.DYNAMIC_STOCK_DICT.get(symbol, symbol)
            
            # ⏰ 30초 취소 로직
            try:
                order_time = datetime.strptime(order_time_str, '%Y-%m-%d %H:%M:%S')
                elapsed_seconds = (datetime.now() - order_time).total_seconds()
                
                if elapsed_seconds > 30:
                    self.sig_log.emit(f"⏳ [주문 취소] {stock_name} 주문 후 30초 경과. 악성 미체결 취소!", "warning")
                    
                    if hasattr(self.mw.api_manager, 'cancel_order'):
                        try: self.mw.api_manager.cancel_order(order_no)
                        except: pass
                    
                    # 🌟 2. 취소 상태 DB 안전하게 덮어쓰기
                    up_conn = None
                    try:
                        up_conn = self.mw.db._get_connection(self.mw.db.shared_db_path)
                        up_conn.execute("UPDATE TradeHistory SET Status = '주문취소' WHERE order_no = ?", (order_no,))
                        up_conn.commit()
                    except: pass
                    finally:
                        if up_conn: up_conn.close()
                    
                    exec_data = {"주문번호": str(order_no), "종목코드": symbol, "체결수량": 0, "체결가": 0, "is_cancel": True}
                    if hasattr(self.mw, 'ticker_window'):
                        self.mw.ticker_window.ws_worker.sig_real_execution.emit(exec_data)
                    
                    continue 
            except Exception: pass

            # 🕵️‍♂️ (기존) 탐정 동기화 로직
            is_filled = False
            if o_type == "BUY" and symbol in real_holdings: 
                is_filled = True
            elif "매도" in o_type or o_type == "SELL":
                if symbol not in real_holdings or real_holdings.get(symbol, {}).get('qty', 0) == 0: 
                    is_filled = True

            if is_filled:
                self.sig_log.emit(f"🕵️‍♂️ [주삐 탐정] 한투 알림 누락 감지! [{stock_name}] 강제 체결 동기화 진행", "success")
                
                up_conn2 = None
                try:
                    up_conn2 = self.mw.db._get_connection(self.mw.db.shared_db_path)
                    up_conn2.execute("UPDATE TradeHistory SET Status = '체결완료' WHERE order_no = ?", (order_no,))
                    up_conn2.commit() 
                except: pass
                finally:
                    if up_conn2: up_conn2.close() 
                
                exec_data = {"주문번호": str(order_no), "종목코드": symbol, "체결수량": int(qty), "체결가": float(price), "is_detective": True}
                if hasattr(self.mw, 'ticker_window'):
                    self.mw.ticker_window.ws_worker.sig_real_execution.emit(exec_data)

# =====================================================================
# 🤖 [일꾼 3호] 매매 관리자 (🔥 스마트 지정가 + 10분 쿨타임 + API 교통정리 적용)
# =====================================================================
class AutoTradeWorker(QThread):
    sig_log = pyqtSignal(str, str); sig_account_df = pyqtSignal(object)        
    sig_strategy_df = pyqtSignal(object); sig_market_df = pyqtSignal(object)         
    sig_sync_cs = pyqtSignal(); sig_order_append = pyqtSignal(dict)        
    sig_panic_done = pyqtSignal()

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window; self.is_running = False
        
        try: 
            db_temp = JubbyDB_Manager()
            self.cumulative_realized_profit = float(db_temp.get_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", "0.0"))
        except: self.cumulative_realized_profit = 0.0
            
        self.panic_mode = False; self.closing_mode_notified = False; self.imminent_notified = False
        self.was_crash_mode = False; self.loss_streak_cnt = 0 
        
        # 🔥 [기능 2] 매도한 종목을 기억하는 10분 쿨타임 수첩 생성
        self.cooldown_dict = {}

    def run(self):
        self.is_running = True
        try: JubbyDB_Manager().update_system_status('TRADER', '감시망 가동 중 🟢', 100)
        except: pass
        
        last_crosscheck_time = time.time() # 🚀 [추가] 크로스체크 타이머
        
        while self.is_running:
            try: 
                self.process_trading()
            except Exception as e: 
                self.sig_log.emit(f"🚨 매매 분석 중 일시적 오류 발생: {e}", "error")
                
            try: cycle_wait_count = int(JubbyDB_Manager().get_shared_setting("TRADE", "CYCLE_WAIT_COUNT", "100"))
            except: cycle_wait_count = 100
            
            for _ in range(cycle_wait_count):
                if not self.is_running: break 
                time.sleep(0.1)
                
        time.sleep(0.2)

    def execute_guaranteed_sell(self, code, qty, current_price):
        """ [실전 최적화] 무조건 시장가(01)로 즉각 탈출하며, 성공 시 주문번호(ODNO)를 반환합니다. """
        stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
        db_temp = JubbyDB_Manager()
        
        try: max_retries = int(db_temp.get_shared_setting("API", "SELL_MAX_RETRY", "10"))
        except: max_retries = 10
        try: retry_delay = float(db_temp.get_shared_setting("API", "SELL_RETRY_DELAY", "1.0"))
        except: retry_delay = 1.0
        
        # ❌ 지정가(sell_limit_order) 관련 로직은 초단타 익/손절에 불리하므로 완전히 삭제했습니다.

        for i in range(max_retries):
            # 🚀 [청소 완료] 무조건 KIS_Manager의 sell 함수 하나로 꽂습니다! (시장가)
            res_odno = self.mw.api_manager.sell(code, qty)
            
            if res_odno: # 주문 성공 (주문번호를 정상적으로 받음)
                if i > 0: self.sig_log.emit(f"✅ [{stock_name}] {i}번의 끈질긴 재시도 끝에 매도 접수 완료!", "success")
                
                # 🔥 매도 완료 시 수첩에 현재 시간 기록! (10분 쿨타임용)
                self.cooldown_dict[code] = datetime.now()
                
                # 🚀 핵심: True가 아니라 주문번호(ODNO)를 반환합니다!
                return res_odno 
                
            # 🚨 [방어 로직 1] KIS API에서 받은 에러 메시지를 꺼내옵니다.
            error_msg = getattr(self.mw.api_manager.api, 'last_error_msg', '')
            
            # 🚨 [방어 로직 2] 잔고가 없다고 명확히 뜨면, 10번 재시도하지 않고 바로 포기!
            if "잔고" in error_msg or "잔고내역" in error_msg:
                self.sig_log.emit(f"🚨 [{stock_name}] 실제 잔고가 없습니다! 억지 매도를 멈추고 보유목록에서 삭제합니다.", "error")
                # 문자열을 반환하여 FormMain.py가 참(True)으로 인식해 장바구니에서 치우게 만듭니다.
                return "ALREADY_SOLD" 
                
            self.sig_log.emit(f"⚠️ [{stock_name}] 매도 실패! 즉시 재시도합니다... ({i+1}/{max_retries}) 사유: {error_msg}", "warning")
            
            # 🚨 [방어 로직 3] API 초당 호출 수 제한(디도스 방어)에 걸리면 트래픽 진정을 위해 좀 더 오래 대기
            if "초과" in error_msg or "초당" in error_msg:
                time.sleep(1.5) # 1.5초 휴식
            else:
                time.sleep(retry_delay) 
                
            if not self.is_running and not getattr(self, 'panic_mode', False): break
            
        if self.is_running or getattr(self, 'panic_mode', False):
            self.sig_log.emit(f"🚨 [{stock_name}] 매도 {max_retries}회 연속 실패!", "error")
            
        return None # 🚀 모든 재시도 실패 시 False 대신 None 반환

    def execute_guaranteed_buy(self, code, qty, current_price):
        stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
        db_temp = JubbyDB_Manager()

        try: max_retries = int(db_temp.get_shared_setting("API", "SELL_MAX_RETRY", "10"))
        except: max_retries = 10
        try: retry_delay = float(db_temp.get_shared_setting("API", "SELL_RETRY_DELAY", "1.0"))
        except: retry_delay = 1.0

        # 🔥 [A전략 적용] 스마트 지정가 설정 무시! 100% 시장가(01)로 즉시 긁어버립니다.
        odno = self.mw.api_manager.buy_market_price(code, qty)

        if odno: return odno # 성공 시 0.1초만에 리턴
            
        self.sig_log.emit(f"⚠️ [{stock_name}] 1차 매수 실패! 재판단 후 재시도...", "warning")
        time.sleep(retry_delay) 
        
        for i in range(1, max_retries):
            if not self.is_running or getattr(self, 'panic_mode', False): return None
            try: prob, new_price, df_feat = self.mw.get_ai_probability(code)
            except: return None
            if prob == -1.0 or df_feat is None or df_feat.empty: return None
            if self.mw.strategy_engine.check_trade_signal(df_feat, code) != "BUY": return None
            
            # 🔥 재시도할 때도 무조건 시장가로 돌진!
            res_odno = self.mw.api_manager.buy_market_price(code, qty)
            if res_odno: return res_odno
            
            time.sleep(retry_delay)
        return None

    def get_realtime_hot_stocks(self): 
        import requests, random, json
        pool = list(self.mw.DYNAMIC_STOCK_DICT.keys())
        hot_list = []
        db_temp = JubbyDB_Manager()
        
        # 🔥 [기능 3] API 딜레이 불러오기
        try: global_api_delay = float(db_temp.get_shared_setting("API", "GLOBAL_API_DELAY", "0.06"))
        except: global_api_delay = 0.06
        
        try: target_limit = int(db_temp.get_shared_setting("TRADE", "HOT_STOCK_LIMIT", "300"))
        except: target_limit = 300

        try: max_per_condition = int(db_temp.get_shared_setting("TRADE", "MAX_PER_CONDITION", "30"))
        except: max_per_condition = 30

        if SystemConfig.MARKET_MODE == "DOMESTIC":
            try:
                default_conditions_json = '''[
                    ["J", "1000", "10000"], ["Q", "1000", "10000"],
                    ["J", "10000", "50000"], ["Q", "10000", "50000"],
                    ["J", "50000", "100000"], ["Q", "50000", "100000"],
                    ["J", "100000", "200000"], ["Q", "100000", "200000"],
                    ["J", "200000", "400000"], ["Q", "200000", "400000"],
                    ["J", "400000", "0"], ["Q", "400000", "0"]
                ]'''
                try: search_conditions = json.loads(db_temp.get_shared_setting("TRADE", "SEARCH_CONDITIONS", default_conditions_json))
                except: search_conditions = json.loads(default_conditions_json)

                api = self.mw.api_manager.api
                url = f"{api.base_url}/uapi/domestic-stock/v1/quotations/volume-rank"
                headers = {"content-type": "application/json", "authorization": f"Bearer {api.access_token}", "appkey": api.app_key, "appsecret": api.app_secret, "tr_id": "FHPST01710000", "custtype": "P"}

                for mrkt, price1, price2 in search_conditions:
                    if len(hot_list) >= target_limit: break 
                    params = {"FID_COND_MRKT_DIV_CODE": mrkt, "FID_COND_SCR_DIV_CODE": "20171", "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0", "FID_BLNG_CLS_CODE": "0", "FID_TRGT_CLS_CODE": "111111111", "FID_TRGT_EXLS_CLS_CODE": "0000000000", "FID_INPUT_PRICE_1": price1, "FID_INPUT_PRICE_2": price2, "FID_VOL_CNT": "0", "FID_INPUT_DATE_1": ""}
                    
                    time.sleep(global_api_delay) # 교통정리
                    res = requests.get(url, headers=headers, params=params, timeout=3)
                    
                    if res.status_code == 200 and res.json().get('rt_cd') == '0':
                        data = res.json().get('output', [])
                        condition_count = 0 
                        for item in data:
                            if str(item.get('acml_vol', '0')) == '0': continue 
                            code = item.get('mksc_shrn_iscd') or item.get('stck_shrn_iscd')
                            if code and code in pool and code not in hot_list:
                                hot_list.append(code)
                                condition_count += 1
                                if condition_count >= max_per_condition: break
                                if len(hot_list) >= target_limit: break
            except Exception: pass

        if len(hot_list) < 20: 
            self.sig_log.emit("⚠️ 랭킹 API 응답 부족으로 랜덤 스캔 모드 가동 (안전 15개 제한)", "warning")
            remaining_pool = [c for c in pool if c not in hot_list]
            if remaining_pool:
                # 🚀 [비상 브레이크] 한투 서버가 아플 때는 무리하지 않고 최대 30개까지만 채웁니다!
                # 이렇게 하면 1) 화면 응답없음 방지, 2) 웹소켓 40개 초과 방지를 완벽하게 해결합니다.
                emergency_limit = 30 
                fill_list = random.sample(remaining_pool, min(emergency_limit, len(remaining_pool)))
                hot_list.extend(fill_list)

        return hot_list

    def process_trading(self):
        if not self.is_running: return 
        
        now = datetime.now(); now_hm = int(now.strftime("%H%M")) 
        db_temp = JubbyDB_Manager() 

        mode = SystemConfig.MARKET_MODE
        try:
            if mode == "DOMESTIC":
                t_start = int(db_temp.get_shared_setting("TRADE", "TIME_START_DOM", "0900")); t_close = int(db_temp.get_shared_setting("TRADE", "TIME_CLOSE_DOM", "1520")); t_imminent = int(db_temp.get_shared_setting("TRADE", "TIME_IMMINENT_DOM", "1525")); t_end = int(db_temp.get_shared_setting("TRADE", "TIME_END_DOM", "1530"))
            elif mode == "OVERSEAS":
                t_start = int(db_temp.get_shared_setting("TRADE", "TIME_START_OVS", "2230")); t_close = int(db_temp.get_shared_setting("TRADE", "TIME_CLOSE_OVS", "0430")); t_imminent = int(db_temp.get_shared_setting("TRADE", "TIME_IMMINENT_OVS", "0445")); t_end = int(db_temp.get_shared_setting("TRADE", "TIME_END_OVS", "0500"))
            else:
                t_start = int(db_temp.get_shared_setting("TRADE", "TIME_START_FUT", "0700")); t_close = int(db_temp.get_shared_setting("TRADE", "TIME_CLOSE_FUT", "0530")); t_imminent = int(db_temp.get_shared_setting("TRADE", "TIME_IMMINENT_FUT", "0545")); t_end = int(db_temp.get_shared_setting("TRADE", "TIME_END_FUT", "0600"))
        except:
            t_start = 900; t_close = 1520; t_imminent = 1525; t_end = 1530

        def in_time(val, s, e): return (s <= val <= e) if s <= e else (val >= s or val <= e)

        is_golden_time       = in_time(now_hm, t_start, t_close - 1)       
        is_closing_phase     = in_time(now_hm, t_close, t_end)             
        is_safe_profit_close = in_time(now_hm, t_close, t_imminent - 1)    
        is_imminent_close    = in_time(now_hm, t_imminent, t_end)          

        # 🔥 [기능 3] API 트래픽 제어 딜레이 로드
        try: global_api_delay = float(db_temp.get_shared_setting("API", "GLOBAL_API_DELAY", "0.06"))
        except: global_api_delay = 0.06

        api_cash = self.mw.api_manager.get_balance()
        my_cash = api_cash if api_cash is not None else getattr(self.mw, 'last_known_cash', 0)
        self.mw.last_known_cash = my_cash; cash_str = f"{my_cash:,}" 

        account_rows = []; market_rows = []; strategy_rows = [] 
        total_invested = 0; total_current_val = 0  

        if is_imminent_close and not getattr(self, 'imminent_notified', False):
            self.sig_log.emit(f"⚠️ [마감 임박] 모든 종목 강제 청산!", "error"); self.imminent_notified = True
        elif not is_closing_phase: self.imminent_notified = False

        if is_closing_phase and not is_imminent_close and not getattr(self, 'closing_mode_notified', False):
            self.sig_log.emit(f"⏰ [마감 모드 돌입] 신규 매수 중지 및 안전 익/손절 진행.", "warning"); self.closing_mode_notified = True
        elif not is_closing_phase: self.closing_mode_notified = False

        market_crash_mode = False
        market_ticker = "069500" if SystemConfig.MARKET_MODE == "DOMESTIC" else ("QQQ" if SystemConfig.MARKET_MODE == "OVERSEAS" else "NQM26")
        
        if not self.is_running: return 
        
        time.sleep(global_api_delay) # 교통정리
        market_etf = self.mw.api_manager.fetch_minute_data(market_ticker)
        if market_etf is not None and len(market_etf) > 1:
            etf_now = market_etf.iloc[-1]['close']; etf_prev = market_etf.iloc[-2]['close']
            self.mw.strategy_engine.market_return_1m = ((etf_now - etf_prev) / etf_prev) * 100.0
            etf_drop = ((etf_now - market_etf.iloc[0]['open']) / market_etf.iloc[0]['open']) * 100
            
            try: crash_limit = float(db_temp.get_shared_setting("TRADE", "CRASH_LIMIT", "-1.5"))
            except: crash_limit = -1.5
            
            if etf_drop <= crash_limit: 
                market_crash_mode = True
                if not getattr(self, 'was_crash_mode', False): 
                    warn_msg = f"⚠️ [시장 경고] {market_ticker} 급락({etf_drop:.2f}%). 신규 매수 차단."
                    self.sig_log.emit(warn_msg, "warning"); self.mw.send_kakao_msg(warn_msg)
                    self.was_crash_mode = True 
            else:
                if getattr(self, 'was_crash_mode', False): 
                    safe_msg = f"🌤️ [시장 안정] {market_ticker} 회복({etf_drop:.2f}%). 탐색 재개!"
                    self.sig_log.emit(safe_msg, "success"); self.mw.send_kakao_msg(safe_msg)
                    self.was_crash_mode = False 

        try:
            use_trailing = db_temp.get_shared_setting("TRADE", "USE_TRAILING", "Y") == "Y"
            ts_start = float(db_temp.get_shared_setting("TRADE", "TRAILING_START_YIELD", "1.5"))
            ts_gap = float(db_temp.get_shared_setting("TRADE", "TRAILING_STOP_GAP", "0.8"))
            max_hold_min = int(db_temp.get_shared_setting("TRADE", "MAX_HOLDING_TIME", "20"))
            loss_limit_cnt = int(db_temp.get_shared_setting("TRADE", "LOSS_STREAK_LIMIT", "5")) 
        except: use_trailing, ts_start, ts_gap, max_hold_min, loss_limit_cnt = True, 1.5, 0.8, 20, 5

        stock_details_str = ""
        current_holdings = list(self.mw.my_holdings.items())

        if len(current_holdings) > 0: 
            sold_codes = []
            for code, info in current_holdings: 
                if not self.is_running: 
                    self.sig_log.emit("🛑 보유 종목 검사 중단 (사용자 요청)", "warning")
                    return 

                if code not in self.mw.my_holdings: continue 

                time.sleep(global_api_delay) # 교통정리

                buy_price = info['price']; buy_qty = info['qty']; stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
                high_watermark = info.get('high_watermark', buy_price); buy_time = info.get('buy_time', now); half_sold = info.get('half_sold', False) 

                if isinstance(buy_time, str):
                    try: buy_time = datetime.strptime(buy_time, '%Y-%m-%d %H:%M:%S')
                    except: buy_time = now
                    self.mw.my_holdings[code]['buy_time'] = buy_time 

                # -------------------------------------------------------------
                # 🚀 [하이브리드 엔진 1] 1분 차트 캐싱 + 0초 딜레이 현재가 병합
                # -------------------------------------------------------------
                current_minute = datetime.now().strftime("%H:%M")
                
                # 1. 1분이 지났을 때만 API 통신을 통해 분봉 차트를 갱신합니다.
                if self.mw.last_fetch_time.get(code) != current_minute:
                    df = self.mw.api_manager.fetch_minute_data(code)
                    if df is not None and len(df) >= 26:
                        df = self.mw.strategy_engine.calculate_indicators(df)
                        self.mw.df_cache[code] = df  # 뇌에 저장
                        self.mw.last_fetch_time[code] = current_minute
                else:
                    # 2. 1분이 안 지났다면 통신 없이 뇌(캐시)에서 0초만에 꺼내옵니다.
                    df = self.mw.df_cache.get(code)
                
                if df is None or len(df) < 26: 
                    continue
                
                # 3. 0초 딜레이 DB 실시간 가격 가져와서 종가 덮어치기
                # 🚨 [수정 1] self.db ➔ db_temp 로 변경! (일꾼 내부의 DB 변수 사용)
                realtime_price = db_temp.get_realtime_price(code)
                curr_price = realtime_price if realtime_price > 0 else float(df.iloc[-1]['close'])
                
                df.at[df.index[-1], 'close'] = curr_price 
                # -------------------------------------------------------------
                
                profit_rate = ((curr_price - buy_price) / buy_price) * 100
                
                profit_amt = (curr_price - buy_price) * buy_qty
                
                target_price, stop_price = self.mw.strategy_engine.get_dynamic_exit_prices(df, buy_price)

                # 🚨 [치명적 버그 수정] 받아온 목표가/손절가(원)를 조건문에서 쓸 수 있게 수익률(%)로 변환!
                target_rate = ((target_price - buy_price) / buy_price) * 100
                stop_rate = ((stop_price - buy_price) / buy_price) * 100

                # (기존 코드) 최고점 갱신 로직
                if curr_price > high_watermark:
                    self.mw.my_holdings[code]['high_watermark'] = curr_price
                    high_watermark = curr_price

                # 🌟 [추가할 알고리즘] 본전 방어 (Break-Even Stop)
                max_profit_rate = ((high_watermark - buy_price) / buy_price) * 100 # 내가 찍었던 최고 수익률

                # 한 번이라도 1.5% 이상 올랐던 주식이라면?
                if max_profit_rate >= 1.5:
                    # 세금과 수수료를 커버할 수 있는 본전 라인(+0.3%) 계산
                    break_even_price = buy_price * 1.003 
                    
                    # 주가가 꺾여서 본전 라인까지 위협하면 뒤도 안 돌아보고 전량 익절!
                    if curr_price <= break_even_price:
                        is_sell_all = True
                        self.sig_log.emit(f"🛡️ [{stock_name}] 본전 방어선 작동! (+1.5% 터치 후 하락). 수익 보존을 위해 탈출합니다.", "warning")

                trail_drop_rate = ((high_watermark - curr_price) / high_watermark) * 100 if high_watermark > 0 else 0
                elapsed_mins = (now - buy_time).total_seconds() / 60.0

                total_invested += (buy_price * buy_qty); total_current_val += (curr_price * buy_qty)
                
                curr_open = float(df.iloc[-1]['open']); curr_high = float(df.iloc[-1]['high']); curr_low = float(df.iloc[-1]['low']); curr_vol = float(df.iloc[-1]['volume']) 
                curr_macd = float(df.iloc[-1].get('MACD', 0.0)); curr_signal = float(df.iloc[-1].get('Signal_Line', 0.0))
                ret_1m = float(df.iloc[-1].get('return', 0.0)); trade_amt = float(df.iloc[-1].get('Trade_Amount', (curr_price * curr_vol) / 1000000))
                curr_vol_energy = float(df.iloc[-1].get('Vol_Energy', 1.0)); curr_disp = float(df.iloc[-1].get('Disparity_20', 100.0))

                # 🚀 [버그 수정 1] 시장, 잔고, 전략 3개의 표 모두에 '시간' 데이터를 넣어주어 nan 깜빡임 완벽 차단!
                now_time_str = datetime.now().strftime('%H:%M:%S')

                market_rows.append({'시간': now_time_str, '종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.2f}", '시가': f"{curr_open:,.2f}", '고가': f"{curr_high:,.2f}", '저가': f"{curr_low:,.2f}", '1분등락률': f"{ret_1m:.2f}", '거래대금': f"{trade_amt:,.1f}", '거래량에너지': f"{curr_vol_energy:.2f}", '이격도': f"{curr_disp:.2f}", '거래량': f"{curr_vol:,.0f}"})

                is_sell_all = False; is_sell_half = False; status_msg = ""; sell_qty = buy_qty
                strat_signal = self.mw.strategy_engine.check_trade_signal(df, code)

                try: safe_profit_rate = float(db_temp.get_shared_setting("TRADE", "SAFE_PROFIT_RATE", "0.3"))
                except: safe_profit_rate = 0.3
                try: strat_profit_preserve = float(db_temp.get_shared_setting("TRADE", "STRAT_PROFIT_PRESERVE", "0.5"))
                except: strat_profit_preserve = 0.5
                try: deadcross_escape_rate = float(db_temp.get_shared_setting("TRADE", "DEADCROSS_ESCAPE_RATE", "1.5"))
                except: deadcross_escape_rate = 1.5

                if getattr(self, 'panic_mode', False): is_sell_all = True; status_msg = "🚨 긴급 전체 청산"
                elif is_imminent_close: is_sell_all = True; status_msg = "마감 임박 시장가 청산"
                elif is_safe_profit_close:
                    if profit_rate >= safe_profit_rate: is_sell_all = True; status_msg = "방어 마감 익절" 
                    elif profit_rate > 0.0 and curr_macd < curr_signal: is_sell_all = True; status_msg = "추세꺾임 탈출"
                    elif profit_rate <= stop_rate: is_sell_all = True; status_msg = "기계적 손절"
                else:
                    if use_trailing and profit_rate >= ts_start and trail_drop_rate >= ts_gap: is_sell_all = True; status_msg = f"트레일링 스탑 ({ts_gap}% 하락)"
                    elif elapsed_mins >= max_hold_min: is_sell_all = True; status_msg = f"시간 제한 ({max_hold_min}분)"
                    elif strat_signal == "SELL" and profit_rate > strat_profit_preserve: is_sell_all = True; status_msg = "매도 신호 (수익 보존)" 
                    elif strat_signal == "SELL" and profit_rate <= stop_rate: is_sell_all = True; status_msg = "매도 신호 (손절)"
                    elif profit_rate >= target_rate and not half_sold: is_sell_half = True; sell_qty = max(1, int(buy_qty // 2)); status_msg = f"목표가({target_rate:.1f}%) 1차 익절"
                    elif profit_rate <= stop_rate: is_sell_all = True; status_msg = f"손절라인({stop_rate:.1f}%) 이탈"
                    elif profit_rate >= deadcross_escape_rate and curr_macd < curr_signal: is_sell_all = True; status_msg = "데드크로스 탈출" 

                if is_sell_half or is_sell_all:
                    res_odno = self.execute_guaranteed_sell(code, sell_qty, curr_price)
                    if res_odno: 
                        if res_odno == "ALREADY_SOLD": res_odno = "00000000" 
                        if profit_rate < 0 and is_sell_all: self.loss_streak_cnt += 1
                        elif profit_rate > 0: self.loss_streak_cnt = 0 
                        
                        # 🌟 [수정 1] 실현 손익(원금 기준)을 먼저 계산하여 누적시킵니다.
                        realized_profit = (curr_price - buy_price) * sell_qty
                        self.cumulative_realized_profit += realized_profit
                        try: db_temp.set_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", str(self.cumulative_realized_profit))
                        except: pass
                        
                        # 🌟 [수정 2] 현재 내 총 자산(현금 + 투자된 주식 금액)을 구합니다.
                        current_total_asset = my_cash + total_invested
                        
                        # 🌟 [수정 3] 총 자산 대비 누적 손익률(%)을 정확하게 계산합니다! (엉터리 단순 덧셈 제거)
                        if current_total_asset > 0:
                            asset_pnl_pct = (self.cumulative_realized_profit / current_total_asset) * 100
                        else:
                            asset_pnl_pct = 0.0
                            
                        self.mw.daily_total_pnl_pct = asset_pnl_pct # 수동 매도 연동용 업데이트
                        
                        # DB에서 연패 횟수와 일일 손실 제한(%) 설정값 불러오기
                        try: max_loss_cnt = int(db_temp.get_shared_setting("RISK", "MAX_CONSECUTIVE_LOSS", "5"))
                        except: max_loss_cnt = 5
                        try: limit_pnl = float(db_temp.get_shared_setting("RISK", "DAILY_STOP_LOSS_PCT", "-10.0"))
                        except: limit_pnl = -10.0

                        # 🌟 [수정 4] 계산된 총 자산 대비 수익률(asset_pnl_pct)로 셧다운 발동 검사
                        if self.loss_streak_cnt >= max_loss_cnt or asset_pnl_pct <= limit_pnl:
                            db_temp.set_shared_setting("RISK", "IS_LOCKED", "Y")
                            self.sig_log.emit(f"🚨 [긴급 셧다운] {self.loss_streak_cnt}연패 또는 총 자산 대비 누적손실({asset_pnl_pct:.2f}%) 도달! 뇌동매매 방지를 위해 주삐 매수를 잠급니다.", "error")
                            
                        if is_sell_all: sold_codes.append(code)
                        else:
                            self.mw.my_holdings[code]['qty'] -= sell_qty
                            self.mw.my_holdings[code]['half_sold'] = True
                        
                        # (실현 손익 계산식은 위로 올라갔으므로 여기서는 제외됨)
                        
                        my_cash += (curr_price * sell_qty); self.mw.last_known_cash = my_cash  
                        total_invested -= (buy_price * sell_qty); total_current_val -= (curr_price * sell_qty)

                        log_icon, log_color = ("🟢", "success") if profit_rate > 0 else ("🔴", "sell")
                        sell_type_str = "1차 익절(절반)" if is_sell_half else "전량 청산"
                        sell_msg = (f"{log_icon} [{sell_type_str}] {stock_name} | {curr_price:,.2f}원 | 매도수량: {sell_qty}주 | 손익: {int(realized_profit):,}원 ({profit_rate:.2f}%)")
                        self.sig_log.emit(sell_msg, log_color) 
                        self.mw.send_kakao_msg(f"🔔 [주삐 매도]\n종목: {stock_name}\n수익률: {profit_rate:.2f}%\n손익: {int(realized_profit):,}원\n사유: {status_msg}") 
                        sell_type_str = '익절' if profit_rate > 0 else '손절'
                        
                        self.sig_order_append.emit({'주문번호': res_odno,'종목코드': code, '종목명': stock_name, '주문종류': sell_type_str, '주문가격': f"{curr_price:,.2f}", '주문수량': sell_qty, '체결수량': 0, '주문시간': now.strftime("%Y-%m-%d %H:%M:%S"), '상태': '미체결', '수익률': f"{profit_rate:.2f}%"})
                        
                if not is_sell_all:
                    if code not in self.mw.my_holdings: continue 
                    cur_qty = self.mw.my_holdings[code]['qty'] if is_sell_half else buy_qty
                    
                    # 🚀 [버그 수정 1] 잔고 표(Account)에도 '시간' 데이터 추가!
                    account_rows.append({'시간': now_time_str, '종목코드': code, '종목명': stock_name, '보유수량': cur_qty, '평균매입가': f"{buy_price:,.2f}", '현재가': f"{curr_price:,.2f}", '평가손익금': f"{profit_amt:,.0f}", '수익률': f"{profit_rate:.2f}%", '주문가능금액': 0})
                    
                    stock_details_str += f"  🔸 {stock_name}: 매입 {buy_price:,.2f} -> 현재 {curr_price:,.2f} ({profit_rate:+.2f}%)\n"

                ma5_val = float(df.iloc[-1].get('MA5', curr_price)); ma20_val = float(df.iloc[-1].get('MA20', curr_price)); rsi_val = float(df.iloc[-1].get('RSI', 50.0))
                
                # 🚀 [버그 수정 1] 전략 표(Strategy)에도 '시간' 데이터 추가!
                strategy_rows.append({'시간': now_time_str, '종목코드': code, '종목명': stock_name, '상승확률': '-', 'MA_5': f"{ma5_val:.0f}", 'MA_20': f"{ma20_val:.0f}", 'RSI': f"{rsi_val:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': '보유중'})
                try: db_temp.update_realtime(code, curr_price, 0.0, "YES", status_msg)
                except: pass
            
            for code in sold_codes: 
                if code in self.mw.my_holdings: del self.mw.my_holdings[code]

        if not self.is_running: return 

        if getattr(self, 'panic_mode', False):
            if len(self.mw.my_holdings) > 0:
                remain_stocks = [self.mw.DYNAMIC_STOCK_DICT.get(c, c) for c in list(self.mw.my_holdings.keys())]
                panic_msg = f"🚨 잔여 종목: {', '.join(remain_stocks)}"
                self.sig_log.emit(panic_msg, "error"); self.mw.send_kakao_msg(panic_msg) 
        else:
            total_unrealized_profit = total_current_val - total_invested; total_asset = my_cash + total_current_val 
            realized_profit = getattr(self, 'cumulative_realized_profit', 0) 
            try: db_temp.set_shared_setting("ACCOUNT", "TOTAL_ASSET", str(total_asset)); db_temp.set_shared_setting("ACCOUNT", "UNREALIZED_PROFIT", str(total_unrealized_profit))
            except: pass
            
            # 🔥 [수정] '누적수익' -> '누적손익'으로 변경하고, 계산되어 있던 '보유손익(total_unrealized_profit)'을 추가했습니다!
            briefing_msg = f"📊 [주삐 1분 브리핑] {now.strftime('%H:%M')}\n💎 총자산: {int(total_asset):,}원 | 누적손익: {int(realized_profit):+,}원 | 보유손익: {int(total_unrealized_profit):+,}원"
            
            if len(self.mw.my_holdings) > 0: briefing_msg += f"\n[보유 주식]\n{stock_details_str.strip()}"
            else: briefing_msg += "\n[보유 주식] 없음"
            self.sig_log.emit(briefing_msg, "info")

        if not hasattr(self.mw, 'accumulated_account'): self.mw.accumulated_account = {}
        for row in account_rows: self.mw.accumulated_account[row['종목코드']] = row
        
        for ac_code in list(self.mw.accumulated_account.keys()):
            if ac_code not in self.mw.my_holdings:
                self.mw.accumulated_account[ac_code]['보유수량'] = "0 (매도됨)"
                self.mw.accumulated_account[ac_code]['평가손익금'] = "매도완료"
                self.mw.accumulated_account[ac_code]['현재가'] = "-"
                self.mw.accumulated_account[ac_code]['수익률'] = "-"
                
        temp_acc_rows = list(self.mw.accumulated_account.values())
        if temp_acc_rows:
            temp_acc_rows[0]['주문가능금액'] = f"{my_cash:,.0f}" 
            df_acc_temp = pd.DataFrame(temp_acc_rows)
            acc_cols = ['시간', '종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','주문가능금액']
            for c in acc_cols:
                if c not in df_acc_temp.columns: df_acc_temp[c] = ""
            self.sig_account_df.emit(df_acc_temp[acc_cols].copy())
            self.sig_sync_cs.emit()

        current_count = len(self.mw.my_holdings)
        try: max_stocks_setting = int(db_temp.get_shared_setting("TRADE", "MAX_STOCKS", "15"))
        except: max_stocks_setting = 10
        needed_count = max_stocks_setting - current_count 
        
        candidates = []; scanned_log_list = []; scan_targets = []

        if is_closing_phase or market_crash_mode:
            pass 

        elif self.loss_streak_cnt >= loss_limit_cnt:
            if now.minute % 5 == 0 and getattr(self, 'last_loss_log', -1) != now.minute:
                self.sig_log.emit(f"🛑 {loss_limit_cnt}연패 리스크 관리! 신규 종목 탐색을 일시 중단합니다.", "error")
                self.last_loss_log = now.minute 

        elif not is_golden_time:
            current_hm = now.strftime("%H:%M") 
            if getattr(self, 'last_idle_log', '') != current_hm and now.minute % 1 == 0:
                self.sig_log.emit(f"💤 [대기중] 현재는 자동매매 가동 시간이 아닙니다. (현재시간: {current_hm})", "info")
                self.last_idle_log = current_hm 
            pass 

        elif needed_count > 0 and not getattr(self, 'panic_mode', False):
            safe_holdings_values = list(self.mw.my_holdings.values())
            total_asset = my_cash + sum([info['price'] * info['qty'] for info in safe_holdings_values])
            
            try: min_scan_stocks = int(db_temp.get_shared_setting("TRADE", "MIN_SCAN_STOCKS", "60"))
            except: min_scan_stocks = 60
            
            # 🔥 [기능 2] 쿨타임 수치 불러오기
            try: cooldown_min = int(db_temp.get_shared_setting("TRADE", "COOLDOWN_MINUTES", "10"))
            except: cooldown_min = 10
            
            # 🔥 [추가] 셧다운(잠금) 상태면 매수 탐색을 건너뜁니다.
            is_locked = db_temp.get_shared_setting("RISK", "IS_LOCKED", "N")
            # =====================================================================
            # 🛠️ [구조 전면 수정] 셧다운 상태라도 보유 종목은 무조건 감시 및 매도 실행!
            # =====================================================================
            is_locked = db_temp.get_shared_setting("RISK", "IS_LOCKED", "N")
            
            # [1] 셧다운 알림 로직 (매수는 잠겨있다고 알림)
            if is_locked == "Y":
                current_hm = datetime.now().strftime("%H:%M") 
                if getattr(self, 'last_lock_log', '') != current_hm and datetime.now().minute % 1 == 0:
                    self.sig_log.emit("🛑 [셧다운 발동 중] 신규 매수가 잠겨있습니다. (보유 종목 매도는 정상 진행 중)", "error")
                    self.last_lock_log = current_hm
                    
            # [2] 🌟 핵심: 잠겨있든 말든 탐색 대상(scan_targets)은 무조건 가져오되, 
            # 내가 현재 보유 중인 종목들을 '1순위'로 쑤셔넣어 방치되는 것을 막습니다!
            base_targets = self.get_realtime_hot_stocks()
            scan_targets = list(set(list(self.mw.my_holdings.keys()) + base_targets)) # 중복 제거 후 합치기

            for code in scan_targets:
                if not self.is_running: 
                    self.sig_log.emit("🛑 신규 탐색 중단 (사용자 요청)", "warning")
                    return 

                # 🔥 [기능 2 적용] 최근에 팔았던 종목이면 10분 쿨타임 검사 (연속 뺨 맞기 방지!)
                # 단, 현재 '보유 중'인 종목은 쿨타임 무시하고 매도 감시를 위해 통과시킴!
                if code in self.cooldown_dict and code not in self.mw.my_holdings:
                    elapsed_cooldown = (datetime.now() - self.cooldown_dict[code]).total_seconds() / 60.0
                    if elapsed_cooldown < cooldown_min:
                        continue # 10분이 안 지났으므로 과감히 패스!
                    else:
                        del self.cooldown_dict[code] # 쿨타임 지났으니 수첩에서 삭제

                # 🟢 스캔 딜레이 적용
                try: scan_delay = float(db_temp.get_shared_setting("TRADE", "SCAN_DELAY", "0.3"))
                except: scan_delay = 0.3
                time.sleep(scan_delay)

                try: prob, curr_price, df_feat = self.mw.get_ai_probability(code)
                except Exception as e: continue
                if prob == -1.0 or curr_price <= 0 or np.isnan(curr_price): continue 

                is_pyramiding = False; current_invested_in_stock = 0.0; holding_qty = 0; holding_price = 0.0; max_allowed_for_stock = 0.0

                if code in self.mw.my_holdings:
                    holding_info = self.mw.my_holdings[code]; holding_price = holding_info['price']; holding_qty = holding_info['qty']
                    current_yield = (curr_price - holding_price) / holding_price * 100.0; current_invested_in_stock = holding_price * holding_qty
                    
                    try: pyramiding_yield = float(db_temp.get_shared_setting("TRADE", "PYRAMIDING_YIELD", "1.0"))
                    except: pyramiding_yield = 1.0
                    
                    try: max_invest_per_stock_pct = float(db_temp.get_shared_setting("TRADE", "MAX_INVEST_PER_STOCK", "15.0"))
                    except: max_invest_per_stock_pct = 15.0
                    
                    max_allowed_for_stock = total_asset * (max_invest_per_stock_pct / 100.0)

                    if current_yield >= pyramiding_yield and current_invested_in_stock < max_allowed_for_stock:
                        is_pyramiding = True
                        try: ai_limit = float(db_temp.get_shared_setting("AI", "THRESHOLD", "80.0")) / 100.0
                        except: ai_limit = 0.80
                        
                        if prob < ai_limit: continue
                    # 🔥 [핵심 수정] 보유 종목은 불타기 조건이 안 맞더라도 '매도 감시'를 받아야 하므로 continue로 튕겨내면 안 됩니다!
                    # else: continue  <-- 이 부분을 과감하게 삭제했습니다!

                stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code) 
                if code not in self.mw.my_holdings: # 보유 종목이 아닐 때만 로그에 추가
                    scanned_log_list.append({'name': stock_name, 'prob': prob})
                
                try: ai_limit = float(db_temp.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
                except: ai_limit = 0.70
                
                now_time = datetime.now().time()
                lunch_start = datetime.strptime("11:30", "%H:%M").time()
                lunch_end = datetime.strptime("13:30", "%H:%M").time()
                
                is_lunch_time = False 
                if lunch_start <= now_time <= lunch_end:
                    ai_limit = ai_limit + 0.05 
                    is_lunch_time = True 

                # ---------------------------------------------------------------------
                # [1] 전략 엔진(Strategy.py)에 차트 데이터를 보내 AI 판단
                # ---------------------------------------------------------------------
                strat_signal = "WAIT" 
                if df_feat is not None and not df_feat.empty:
                    strat_signal = self.mw.strategy_engine.check_trade_signal(df_feat, code)
                    
                    if 0.5 <= prob < ai_limit:
                        if is_lunch_time:
                            self.sig_log.emit(f"🔎 [{stock_name}] AI 확신도 부족 ({prob * 100:.1f}% < 점심장 상향 커트라인 {ai_limit * 100:.1f}%)", "warning")
                        else:
                            self.sig_log.emit(f"🔎 [{stock_name}] AI 확신도 부족 ({prob * 100:.1f}% < 설정 커트라인 {ai_limit * 100:.1f}%)", "warning")
                        # 🔥 매도 감시를 위해 보유 종목이면 넘어가지 않고 계속 진행
                        if code not in self.mw.my_holdings: 
                            continue
                            
                    if strat_signal == "BUY" and prob < ai_limit: self.sig_log.emit(f"💡 [{stock_name}] 전략엔진 매수 추천이나, AI 미달", "info")

                    curr_open = float(df_feat.iloc[-1]['open']); curr_high = float(df_feat.iloc[-1]['high']); curr_low  = float(df_feat.iloc[-1]['low']); curr_vol  = float(df_feat.iloc[-1]['volume'])
                    ret_1m = float(df_feat.iloc[-1].get('return', 0.0)); trade_amt = float(df_feat.iloc[-1].get('Trade_Amount', (curr_price * curr_vol) / 1000000))
                    curr_vol_energy = float(df_feat.iloc[-1].get('Vol_Energy', 1.0)); curr_disp = float(df_feat.iloc[-1].get('Disparity_20', 100.0)); curr_macd = float(df_feat.iloc[-1].get('MACD', 0.0)); curr_rsi = float(df_feat.iloc[-1].get('RSI', 50.0)); ma5_val = float(df_feat.iloc[-1].get('MA5', curr_price)); ma20_val = float(df_feat.iloc[-1].get('MA20', curr_price)); curr_atr = float(df_feat.iloc[-1].get('ATR', 0.0))
                else: 
                    curr_open = curr_high = curr_low = curr_price; curr_vol = ret_1m = trade_amt = 0.0; curr_disp = 100.0; curr_vol_energy = 1.0; curr_macd = 0.0; curr_rsi = 50.0; ma5_val = curr_price; ma20_val = curr_price; curr_atr = 0.0
                    
                now_time_str = datetime.now().strftime('%H:%M:%S')
                market_rows.append({'시간': now_time_str, '종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.2f}", '시가': f"{curr_open:,.2f}", '고가': f"{curr_high:,.2f}", '저가': f"{curr_low:,.2f}", '1분등락률': f"{ret_1m:.2f}", '거래대금': f"{trade_amt:,.1f}", '거래량에너지': f"{curr_vol_energy:.2f}", '이격도': f"{curr_disp:.2f}", '거래량': f"{curr_vol:,.0f}"})
                
                display_signal = "BUY 🟢" if strat_signal == "BUY" else ("SELL 🔴" if strat_signal == "SELL" else "WAIT 🟡")
                
                if df_feat is not None: 
                    strategy_rows.append({
                        '시간': now_time_str, '종목코드': code, '종목명': stock_name, 
                        '상승확률': f"{prob*100:.1f}%", 'MA_5': f"{ma5_val:.0f}", 
                        'MA_20': f"{ma20_val:.0f}", 'RSI': f"{curr_rsi:.1f}", 
                        'MACD': f"{curr_macd:.2f}", '전략신호': display_signal
                    })
                
                # =====================================================================
                # [2] 🛑 셧다운 방어막 (락이 걸려있으면 여기서 매수만 컷트!)
                # =====================================================================
                if is_locked == "Y" and strat_signal == "BUY":
                    # 락 걸렸는데 매수하려고 하면? 응 안돼~ 하고 다음 종목으로 패스
                    continue 

                # ---------------------------------------------------------------------
                # [3] 실시간 즉시 매수 로직 (락이 안 걸려있어야 여기까지 도달) ⚡
                # ---------------------------------------------------------------------
                if strat_signal == "BUY" and prob >= ai_limit: 
                    try: 
                        use_funds_percent = float(db_temp.get_shared_setting("TRADE", "USE_FUNDS_PERCENT", "100"))
                    except: 
                        use_funds_percent = 100.0

                    allowed_total_budget = total_asset * (use_funds_percent / 100.0)
                    available_trading_budget = allowed_total_budget - total_invested
                    
                    if available_trading_budget > 0:
                        if is_pyramiding:
                            try: pyramiding_rate = float(db_temp.get_shared_setting("TRADE", "PYRAMIDING_RATE", "50.0"))
                            except: pyramiding_rate = 50.0
                            target_budget = current_invested_in_stock * (pyramiding_rate / 100.0)
                            
                            max_remaining_for_stock = max_allowed_for_stock - current_invested_in_stock
                            target_budget = min(target_budget, max_remaining_for_stock)
                        else:
                            try: 
                                weight_high = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_HIGH", "20.0")) / 100.0
                                weight_mid = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_MID", "10.0")) / 100.0
                                weight_low = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_LOW", "5.0")) / 100.0
                            except: 
                                weight_high, weight_mid, weight_low = 0.20, 0.10, 0.05
                            
                            if prob >= 0.85: weight = weight_high    
                            elif prob >= 0.70: weight = weight_mid  
                            else: weight = weight_low               
                            
                            base_target_budget = float(total_asset * weight)
                            
                            try: 
                                atr_high_limit = float(db_temp.get_shared_setting("TRADE", "ATR_HIGH_LIMIT", "5.0"))
                                atr_high_ratio = float(db_temp.get_shared_setting("TRADE", "ATR_HIGH_RATIO", "50.0")) / 100.0
                                atr_mid_limit  = float(db_temp.get_shared_setting("TRADE", "ATR_MID_LIMIT", "2.5"))
                                atr_mid_ratio  = float(db_temp.get_shared_setting("TRADE", "ATR_MID_RATIO", "70.0")) / 100.0
                            except: 
                                atr_high_limit, atr_high_ratio = 5.0, 0.5
                                atr_mid_limit, atr_mid_ratio = 2.5, 0.7
                                
                            volatility_pct = (curr_atr / curr_price) * 100 if curr_price > 0 else 0
                            if volatility_pct >= atr_high_limit: 
                                target_budget = base_target_budget * atr_high_ratio
                                self.sig_log.emit(f"🚨 {stock_name} 변동성 극심({volatility_pct:.1f}%)! 매수 비중 50% 축소", "warning")
                            elif volatility_pct >= atr_mid_limit: 
                                target_budget = base_target_budget * atr_mid_ratio
                                self.sig_log.emit(f"🛡️ {stock_name} 변동성 높음({volatility_pct:.1f}%). 매수 비중 30% 축소", "warning")
                            else: 
                                target_budget = base_target_budget

                        budget = min(target_budget, available_trading_budget)
                        buy_qty = int(budget // curr_price) 
                        
                        if buy_qty * curr_price > my_cash: 
                            buy_qty = int(my_cash // curr_price)
                        
                        if buy_qty > 0:
                            res_odno = self.execute_guaranteed_buy(code, buy_qty, curr_price)
                            
                            if res_odno: 
                                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                
                                if is_pyramiding:
                                    old_qty = holding_qty
                                    old_price = holding_price
                                    new_total_qty = old_qty + buy_qty
                                    new_avg_price = ((old_price * old_qty) + (curr_price * buy_qty)) / new_total_qty
                                    self.mw.my_holdings[code]['price'] = new_avg_price
                                    self.mw.my_holdings[code]['qty'] = new_total_qty
                                    self.mw.my_holdings[code]['high_watermark'] = max(self.mw.my_holdings[code]['high_watermark'], curr_price)
                                    self.sig_log.emit(f"🔥 [불타기 주문] {stock_name} | 추가: {buy_qty}주 | 번호: {res_odno}", "buy") 
                                else:
                                    self.mw.my_holdings[code] = {'price': curr_price, 'qty': buy_qty, 'high_watermark': curr_price, 'buy_time': now_str, 'half_sold': False}
                                    self.sig_log.emit(f"⚡ [즉시 진입] {stock_name} 포착! (AI: {prob*100:.1f}%)", "success")
                                    self.sig_log.emit(f"🔵 [매수 주문] {stock_name} | {curr_price:,.2f}원 | {buy_qty}주 | 번호: {res_odno}", "buy") 

                                my_cash -= (curr_price * buy_qty)
                                total_invested += (curr_price * buy_qty)

                                self.sig_order_append.emit({
                                    '주문번호': res_odno, 
                                    '종목코드': code, 
                                    '종목명': stock_name, 
                                    '주문종류': '매수' if not is_pyramiding else '불타기', 
                                    '주문가격': f"{curr_price:,.2f}", 
                                    '주문수량': buy_qty, 
                                    '체결수량': 0, 
                                    '주문시간': now_str, 
                                    '상태': '미체결', 
                                    '수익률': '0.00%' 
                                })
                                
                                account_rows.append({'시간': now_time_str, '종목코드': code, '종목명': stock_name, '보유수량': new_total_qty if is_pyramiding else buy_qty, '평균매입가': f"{new_avg_price if is_pyramiding else curr_price:,.2f}", '현재가': f"{curr_price:,.2f}", '평가손익금': "0", '수익률': "0.00%", '주문가능금액': 0})
                                if account_rows: account_rows[0]['주문가능금액'] = f"{my_cash:,}" 
                                
                                acc_cols = ['시간', '종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','주문가능금액']
                                temp_df = pd.DataFrame(account_rows)
                                for c in acc_cols:
                                    if c not in temp_df.columns: temp_df[c] = ""
                                self.sig_account_df.emit(temp_df[acc_cols].copy()); self.sig_sync_cs.emit()
                                
                                needed_count -= 1
                                
                                if needed_count <= 0:
                                    break

                try: db_temp.update_realtime(code, curr_price, prob*100, "NO", "탐색 중...")
                except: pass

                if len(scanned_log_list) >= min_scan_stocks: break

            if scanned_log_list:
                scanned_log_list = sorted(scanned_log_list, key=lambda x: x['prob'], reverse=True)
                top_list = scanned_log_list[:3] 
                top_msg = ", ".join([f"{x['name']}({x['prob']*100:.1f}%)" for x in top_list])
                
                actual_scanned_count = len(scanned_log_list)
                # 🔥 [수정] 장바구니 로직이 사라졌으므로, 헷갈리지 않게 그냥 스캔 결과만 깔끔하게 브리핑합니다!
                self.sig_log.emit(f"🔎 1분 스캔 사이클 완료 ({actual_scanned_count}개 탐색). 현재 주도주 TOP 3: {top_msg}", "info")

            # if candidates:
            #     candidates = sorted(candidates, key=lambda x: x['prob'], reverse=True)
            #     for i in range(min(needed_count, len(candidates))):
            #         if not self.is_running: return 

            #         cand = candidates[i]; code = cand['code']; prob = cand['prob']; curr_price = cand['price']; stock_name = cand['stock_name']; is_pyramiding = cand['is_pyramiding']

            #         try: use_funds_percent = float(db_temp.get_shared_setting("TRADE", "USE_FUNDS_PERCENT", "100"))
            #         except: use_funds_percent = 100.0

            #         allowed_total_budget = total_asset * (use_funds_percent / 100.0); available_trading_budget = allowed_total_budget - total_invested
            #         if available_trading_budget <= 0: continue

            #         if is_pyramiding:
            #             try: pyramiding_rate = float(db_temp.get_shared_setting("TRADE", "PYRAMIDING_RATE", "50.0"))
            #             except: pyramiding_rate = 50.0
            #             target_budget = cand['current_invested'] * (pyramiding_rate / 100.0); max_remaining_for_stock = cand['max_allowed'] - cand['current_invested']; target_budget = min(target_budget, max_remaining_for_stock)
            #         else:
            #             try: weight_high = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_HIGH", "20.0")) / 100.0
            #             except: weight_high = 0.20
            #             try: weight_mid = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_MID", "10.0")) / 100.0
            #             except: weight_mid = 0.10
            #             try: weight_low = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_LOW", "5.0")) / 100.0
            #             except: weight_low = 0.05
                        
            #             if prob >= 0.85: weight = weight_high     
            #             elif prob >= 0.70: weight = weight_mid   
            #             else: weight = weight_low                
                        
            #             base_target_budget = float(total_asset * weight)
            #             try: atr_high_limit = float(db_temp.get_shared_setting("TRADE", "ATR_HIGH_LIMIT", "5.0")); atr_high_ratio = float(db_temp.get_shared_setting("TRADE", "ATR_HIGH_RATIO", "50.0")) / 100.0; atr_mid_limit  = float(db_temp.get_shared_setting("TRADE", "ATR_MID_LIMIT", "2.5")); atr_mid_ratio  = float(db_temp.get_shared_setting("TRADE", "ATR_MID_RATIO", "70.0")) / 100.0
            #             except: atr_high_limit, atr_high_ratio = 5.0, 0.5; atr_mid_limit, atr_mid_ratio = 2.5, 0.7
                            
            #             current_atr = cand['atr']; volatility_pct = (current_atr / curr_price) * 100 if curr_price > 0 else 0
            #             if volatility_pct >= atr_high_limit: target_budget = base_target_budget * atr_high_ratio; self.sig_log.emit(f"🚨 {stock_name} 변동성 극심({volatility_pct:.1f}%)! 매수 축소", "warning")
            #             elif volatility_pct >= atr_mid_limit: target_budget = base_target_budget * atr_mid_ratio; self.sig_log.emit(f"🛡️ {stock_name} 변동성 높음({volatility_pct:.1f}%). 매수 축소", "warning")
            #             else: target_budget = base_target_budget

            #         budget = min(target_budget, available_trading_budget); buy_qty = int(budget // curr_price) 
            #         if buy_qty * curr_price > my_cash: buy_qty = int(my_cash // curr_price)
            #         if buy_qty == 0: continue

            #         # 🔥 [기능 1 적용] 매수 실행 함수에 현재가(limit_price) 전달
            #         if buy_qty > 0 and self.execute_guaranteed_buy(code, buy_qty, curr_price):
            #             now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            #             if is_pyramiding:
            #                 old_qty = cand['holding_qty']; old_price = cand['holding_price']; new_total_qty = old_qty + buy_qty; new_avg_price = ((old_price * old_qty) + (curr_price * buy_qty)) / new_total_qty
            #                 self.mw.my_holdings[code]['price'] = new_avg_price; self.mw.my_holdings[code]['qty'] = new_total_qty; self.mw.my_holdings[code]['high_watermark'] = max(self.mw.my_holdings[code]['high_watermark'], curr_price)
            #                 self.sig_log.emit(f"🔥 [불타기 성공] {stock_name} | 추가: {buy_qty}주 | AI: {prob*100:.1f}%", "buy") 
            #             else:
            #                 self.mw.my_holdings[code] = {'price': curr_price, 'qty': buy_qty, 'high_watermark': curr_price, 'buy_time': now, 'half_sold': False}
            #                 self.sig_log.emit(f"🔵 [매수 체결] {stock_name} | {curr_price:,.2f}원 | {buy_qty}주 | AI: {prob*100:.1f}%", "buy") 

            #             my_cash -= (curr_price * buy_qty); total_invested += (curr_price * buy_qty)
            #             self.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': '매수' if not is_pyramiding else '불타기', '주문가격': f"{curr_price:,.2f}", '주문수량': buy_qty, '체결수량': buy_qty, '주문시간': now, '상태': '체결완료', '수익률': '0.00%'})
            #             now_time = datetime.now().strftime('%H:%M:%S')
            #             account_rows.append({'시간': now_time, '종목코드': code, '종목명': stock_name, '보유수량': new_total_qty if is_pyramiding else buy_qty, '평균매입가': f"{new_avg_price if is_pyramiding else curr_price:,.2f}", '현재가': f"{curr_price:,.2f}", '평가손익금': "0", '수익률': "0.00%", '주문가능금액': 0})
            #             if account_rows: account_rows[0]['주문가능금액'] = f"{my_cash:,}" 
                        
            #             acc_cols = ['시간', '종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','주문가능금액']
            #             temp_df = pd.DataFrame(account_rows)
            #             for c in acc_cols:
            #                 if c not in temp_df.columns: temp_df[c] = ""
            #             self.sig_account_df.emit(temp_df[acc_cols].copy()); self.sig_sync_cs.emit()

        if not self.is_running: return 

        if not hasattr(self.mw, 'accumulated_market'): self.mw.accumulated_market = {}
        if not hasattr(self.mw, 'accumulated_strategy'): self.mw.accumulated_strategy = {}
        if not hasattr(self.mw, 'accumulated_account'): self.mw.accumulated_account = {}

        for row in market_rows: self.mw.accumulated_market[row['종목코드']] = row
        for row in strategy_rows: self.mw.accumulated_strategy[row['종목코드']] = row
        for row in account_rows: self.mw.accumulated_account[row['종목코드']] = row

        for code in list(self.mw.accumulated_account.keys()):
            if code not in self.mw.my_holdings:
                # 🚀 [요청 반영] 매도 완료된 종목도 마지막으로 확정된 수익률과 손익금을 예쁘게 남겨둡니다!
                self.mw.accumulated_account[code]['보유수량'] = "0 (매도됨)"
                # 평가손익금, 현재가, 수익률은 '-' 로 지우지 않고 체결 순간의 기록을 영구 보존합니다.

        market_rows = list(self.mw.accumulated_market.values())
        strategy_rows = list(self.mw.accumulated_strategy.values())
        account_rows = list(self.mw.accumulated_account.values())

        for i in range(len(account_rows)): account_rows[i]['주문가능금액'] = ""
        if account_rows: account_rows[0]['주문가능금액'] = f"{my_cash:,.0f}" 
        else: account_rows.append({'시간': '-', '종목코드': '-', '종목명': '보유종목 없음', '보유수량': 0, '평균매입가': '0', '현재가': '0', '평가손익금': '0', '수익률': '0.00%', '주문가능금액': f"{my_cash:,.0f}"})
        
        acc_cols = ['시간', '종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','주문가능금액']
        mkt_cols = ['시간','종목코드','종목명','현재가','시가','고가','저가','1분등락률','거래대금','거래량에너지','이격도','거래량']
        str_cols = ['시간','종목코드','종목명','상승확률','MA_5','MA_20','RSI','MACD','전략신호']

        if account_rows:
            df_acc = pd.DataFrame(account_rows)
            for c in acc_cols:
                if c not in df_acc.columns: df_acc[c] = ""
            self.sig_account_df.emit(df_acc[acc_cols].copy()) 

        if market_rows:  
            df_mkt = pd.DataFrame(market_rows)
            for c in mkt_cols:
                if c not in df_mkt.columns: df_mkt[c] = "0"
            self.sig_market_df.emit(df_mkt[mkt_cols].copy()) 

        if strategy_rows: 
            df_str = pd.DataFrame(strategy_rows)
            for c in str_cols:
                if c not in df_str.columns: df_str[c] = "0"
            self.sig_strategy_df.emit(df_str[str_cols].copy()) 
            
        self.sig_sync_cs.emit() 
        
        if getattr(self, 'panic_mode', False) and len(self.mw.my_holdings) == 0:
            self.sig_log.emit("🛑 긴급 청산 완료", "warning")
            self.panic_mode = False; self.is_running = False; self.sig_panic_done.emit()

# =====================================================================
# 🖥️ 메인 UI 클래스
# =====================================================================
class FormMain(QtWidgets.QMainWindow):
    sig_safe_log = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()

        # 🔥 [핵심 수정] 실수로 삭제되었던 UI 도화지 렌더링 코드를 다시 채워 넣습니다!
        self.initUI()

        self.sig_safe_log.connect(self._safe_append_log_sync)

        self.db = JubbyDB_Manager()
        self.db.cleanup_old_data() 

        self.init_default_settings()

        self.api_manager = KIS_Manager(ui_main=self)
        self.api_manager.start_api() 
        
        # 👇 이 세 줄을 새로 추가하여 Ticker 창을 부활시킵니다!
        self.ticker_window = FormTicker(main_ui=self)
        self.ticker_window.show()
        self.add_log("⚡ 실시간 체결 Ticker 창이 활성화되었습니다.", "info")

        # 🚀 [추가] 켜지자마자 메인폼 옆에 붙여줍니다.
        # 메인폼 UI가 완전히 그려질 시간을 벌기 위해 0.1초 뒤 실행합니다.
        QtCore.QTimer.singleShot(100, self.ticker_window.snap_to_main)

        self.strategy_engine = JubbyStrategy(log_callback=self.add_log)
        
        # -------------------------------------------------------------
        # 📖 [여기서부터 찾으세요!] DB에서 종목 명단 불러오는 구간
        # -------------------------------------------------------------
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            query = f"SELECT symbol, symbol_name FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
            df_dict = pd.read_sql(query, conn)
            conn.close()
            
            # 1. 먼저 딕셔너리를 생성합니다.
            if SystemConfig.MARKET_MODE == "DOMESTIC": 
                self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str).str.zfill(6), df_dict['symbol_name']))
            else: 
                self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str), df_dict['symbol_name']))
            
            # ---------------------------------------------------------
            # 🔥 [여기가 정확한 삽입 위치입니다!]
            # 위에서 만든 '명단(딕셔너리)'을 전략 엔진에게 배달해줍니다.
            # ---------------------------------------------------------
            if hasattr(self, 'strategy_engine'):
                self.strategy_engine.set_stock_dict(self.DYNAMIC_STOCK_DICT)
            # ---------------------------------------------------------

            if not self.DYNAMIC_STOCK_DICT: raise ValueError("DB 명단이 비어 있습니다.")
            self.add_log(f"📖 DB에서 {len(self.DYNAMIC_STOCK_DICT)}개 종목 명단을 불러왔습니다!", "info")

        except Exception as e:
            self.add_log(f"⚠️ DB 명단 로드 실패: {e}", "warning")
            self.DYNAMIC_STOCK_DICT = {"005930": "삼성전자"}
            
            # 실패했을 때도 최소한의 정보를 전달
            if hasattr(self, 'strategy_engine'):
                self.strategy_engine.set_stock_dict(self.DYNAMIC_STOCK_DICT)

        # =========================================================
        # 🔥 [핵심 수정] 전략 엔진이 '생성된 직후'에 명단을 쥐어줍니다!
        self.strategy_engine.set_stock_dict(self.DYNAMIC_STOCK_DICT)
        # =========================================================

        self.my_holdings = {}; self.last_known_cash = 0 
        
        # 🚀 [추가] 1분에 1번만 통신하기 위한 하이브리드 캐시 메모리
        self.df_cache = {}          
        self.last_fetch_time = {}
        
        self.trade_worker = AutoTradeWorker(main_window=self) 
        self.trade_worker.sig_log.connect(self.add_log)                                
        self.trade_worker.sig_account_df.connect(self.update_account_table_slot)        
        self.trade_worker.sig_strategy_df.connect(self.update_strategy_table_slot)     
        self.trade_worker.sig_sync_cs.connect(self.btnDataSendClickEvent)
        self.trade_worker.sig_order_append.connect(self.append_order_table_slot)            
        self.trade_worker.sig_market_df.connect(self.update_market_table_slot)   
        self.trade_worker.sig_panic_done.connect(self.panic_sell_done_slot)
        self.trade_worker.finished.connect(self.check_worker_stopped)

        # =====================================================================
        # 🔥 [탐정 출동] 프로그램 켜지자마자 감시 스레드 가동 (중복 실행 완벽 방지)
        # =====================================================================
        # 1. 이미 활동 중인 탐정이 있다면, 하던 일을 멈추게 하고 퇴근시킵니다.
        if hasattr(self, 'detective_worker') and self.detective_worker is not None:
            try:
                self.detective_worker.is_running = False
                self.detective_worker.quit()
                self.detective_worker.wait(1000)
                # 🌟 [핵심] 기존에 연결해둔 알림선(Signal)을 확실하게 뽑아버립니다.
                self.detective_worker.sig_log.disconnect() 
            except Exception: 
                pass

        # 2. 완전히 깨끗해진 상태에서 새 탐정을 1명만 고용하고 알림선을 연결합니다.
        self.detective_worker = DetectiveWorker(main_window=self)
        self.detective_worker.sig_log.connect(self.add_log)
        self.detective_worker.start()
        
        QtCore.QTimer.singleShot(3000, self.load_real_holdings) 
        self.kakao_timer = QtCore.QTimer(self); self.kakao_timer.timeout.connect(self.auto_status_report); self.kakao_timer.start(1000 * 60 * 60) 
        
        # 🔥 [추가] 리스크 관리용 변수 세팅
        self.daily_total_pnl_pct = 0.0
        
        # 🔥 [추가] 로그창(txtLog) Ctrl+우클릭 이벤트 연결
        self.txtLog.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.txtLog.customContextMenuRequested.connect(self.show_log_context_menu)
        
        # 🔥 [여기에 1줄 추가!] 시작하고 2초 뒤에 과거 미체결 내역을 화면에 띄웁니다.
        QtCore.QTimer.singleShot(2000, self.load_unfilled_orders_to_ui)

    # 🔥 [추가] 로그창 우클릭 시 잠금 해제 메뉴 띄우기 (def send_kakao_msg 함수 바로 위에 넣으시면 됩니다)
    def show_log_context_menu(self, pos):
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if modifiers == QtCore.Qt.ControlModifier: # Ctrl 키를 누른 상태일 때만 작동
            menu = QtWidgets.QMenu()
            menu.setStyleSheet("QMenu { background-color: rgb(30, 40, 60); color: white; font-size: 14px; border: 1px solid Silver; } QMenu::item { padding: 10px 25px; } QMenu::item:selected { background-color: rgb(80, 120, 160); }")
            unlock_action = menu.addAction("🔓 주삐 셧다운(매수 잠금) 강제 해제")
            action = menu.exec_(self.txtLog.mapToGlobal(pos))
            
            if action == unlock_action:
                self.db.set_shared_setting("RISK", "IS_LOCKED", "N")
                self.daily_total_pnl_pct = 0.0 # 전체 누적 손익 완전 초기화
                if hasattr(self, 'trade_worker') and self.trade_worker is not None:
                    self.trade_worker.loss_streak_cnt = 0 # 워커 내부 연패 카운터 초기화
                    self.trade_worker.panic_mode = False  # 패닉 모드 잔재 완전 제거
                self.add_log("🛡️ [시스템] 관리자 권한으로 매수 잠금이 완벽히 해제되었습니다. 다시 탐색을 시작합니다.", "success")

    def send_kakao_msg(self, text):
        REST_API_KEY = self.db.get_shared_setting("KAKAO", "REST_API_KEY", "4cbe02304c893a129a812045d5f200a3")
        try:
            import json, requests, os
            from COMMON.DB_Manager import get_smart_path  
            
            token_path = get_smart_path("kakao_token.json")
            if not os.path.exists(token_path): return False
            with open(token_path, "r") as fp: tokens = json.load(fp)
            
            url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"; headers = {"Authorization": f"Bearer {tokens['access_token']}"}
            template = {"object_type": "text", "text": text, "link": {}}; data = {"template_object": json.dumps(template)}
            res = requests.post(url, headers=headers, data=data, timeout=3)
            
            if res.status_code == 200: return True 
            else:
                refresh_url = "https://kauth.kakao.com/oauth/token"; refresh_data = {"grant_type": "refresh_token", "client_id": REST_API_KEY, "refresh_token": tokens.get("refresh_token")}
                new_token_res = requests.post(refresh_url, data=refresh_data, timeout=3).json()
                if "access_token" not in new_token_res: return False
                tokens["access_token"] = new_token_res["access_token"]
                if "refresh_token" in new_token_res: tokens["refresh_token"] = new_token_res["refresh_token"]
                with open(token_path, "w") as fp: json.dump(tokens, fp)
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}; res2 = requests.post(url, headers=headers, data=data, timeout=3)
                return res2.status_code == 200
        except Exception as e: return False

    def auto_status_report(self): pass 

    @QtCore.pyqtSlot(str)
    def sys_print_to_log(self, text): self.add_log(f"🖥️ {text}", "info")

    @QtCore.pyqtSlot(dict)
    def append_order_table_slot(self, order_info):
        if not order_info: return 
        
        # 1. DB 저장은 기존 로직 그대로 수행
        try:
            order_no = order_info.get('주문번호', '00000000')
            code = order_info.get('종목코드', '')
            # 🔥 [버그 완벽 수정] 한글 '매수'와 '불타기'도 정확히 BUY로 인식하게 수정!
            order_str = str(order_info.get('주문종류', '')).upper()
            o_type = "BUY" if "매수" in order_str or "불타기" in order_str or "BUY" in order_str else "SELL"
            
            price = float(str(order_info.get('주문가격', '0')).replace(',', ''))
            qty = int(order_info.get('주문수량', 0))
            y_rate = float(str(order_info.get('수익률', '0')).replace('%', ''))
            self.db.insert_trade_history(order_no, code, o_type, price, qty, y_rate)
        except Exception: pass

        # 2. 표 컬럼 순서 (Flag.py와 100% 일치)
        ord_cols = ['주문번호', '시간', '종목코드', '종목명', '주문종류', '주문가격', '주문수량', '체결수량', '상태']

        row_idx = self.tbOrder.rowCount()
        self.tbOrder.insertRow(row_idx)
        
        for col_idx, col_name in enumerate(ord_cols):
            # '주문시간' 키값을 '시간' 컬럼에 매핑
            if col_name == '시간':
                val = str(order_info.get('주문시간', datetime.now().strftime("%H:%M:%S")))
            else:
                val = str(order_info.get(col_name, ''))
            
            # 미체결 상태 기본값 세팅
            if col_name == '상태' and not order_info.get('상태'): val = "미체결"

            item = QtWidgets.QTableWidgetItem(val)
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.tbOrder.setItem(row_idx, col_idx, item)
            
        # 🚀 Ticker 작동을 위해 주문번호(0번)는 존재해야 하지만, 사용자 눈엔 숨깁니다.
        self.tbOrder.setColumnHidden(0, True) 
        
        if self.tbOrder.rowCount() > 500: self.tbOrder.removeRow(0)

    @QtCore.pyqtSlot() 
    def btnDataSendClickEvent(self):
        def clean_num(val): 
            v = str(val).replace(",", "").replace("%", "").strip()
            if v.lower() in ["", "nan", "inf", "-inf", "infinity"]: return "0.0"
            if v == "-": return "0.0" 
            try: return str(float(v))
            except ValueError: return "0.0"

        def get_symbol(row):
            sym = str(row.get("종목코드", ""))
            if sym in ["", "0"]: return ""
            if sym == "-": return sym
            return sym.zfill(6) if SystemConfig.MARKET_MODE == "DOMESTIC" else sym

        market_list = []
        if not TradeData.market.df.empty:
            for _, row in TradeData.market.df.iterrows():
                sym = get_symbol(row)
                if not sym: continue
                market_list.append({"symbol": sym, "symbol_name": str(row.get("종목명", "")), "last_price": float(clean_num(row.get("현재가", "0"))), "open_price": float(clean_num(row.get("시가", "0"))), "high_price": float(clean_num(row.get("고가", "0"))), "low_price": float(clean_num(row.get("저가", "0"))), "return_1m": float(clean_num(row.get("1분등락률", "0"))), "trade_amount": float(clean_num(row.get("거래대금", "0"))), "vol_energy": float(clean_num(row.get("거래량에너지", "1"))), "disparity": float(clean_num(row.get("이격도", "100"))), "volume": float(clean_num(row.get("거래량", "0")))})
            try: self.db.update_market_table(market_list)
            except Exception as e: self.add_log(f"🚨 MarketStatus DB 에러: {e}", "error")

        account_list = []
        if not TradeData.account.df.empty:
            for _, row in TradeData.account.df.iterrows():
                sym = get_symbol(row)
                if not sym: continue
                curr_price = float(clean_num(row.get("현재가", "0")))
                account_list.append({"symbol": sym, "symbol_name": str(row.get("종목명", "")), "quantity": int(float(clean_num(row.get("보유수량", "0")))), "avg_price": float(clean_num(row.get("평균매입가", "0"))), "current_price": curr_price, "pnl_amt": float(clean_num(row.get("평가손익금", "0"))), "pnl_rate": float(clean_num(row.get("수익률", "0"))), "available_cash": float(clean_num(row.get("주문가능금액", "0")))})
                if curr_price > 0:
                    try: self.db.insert_price_history(sym, curr_price)
                    except: pass
            try: self.db.update_account_table(account_list)
            except Exception as e: self.add_log(f"🚨 AccountStatus DB 에러: {e}", "error")

        strategy_list = []
        if not TradeData.strategy.df.empty:
            for _, row in TradeData.strategy.df.iterrows():
                sym = get_symbol(row)
                if not sym: continue
                sig = str(row.get("전략신호", "")); sig = "BUY" if "BUY" in sig else ("SELL" if "SELL" in sig else ("WAIT" if "WAIT" in sig else sig))
                
                # 🚀 [수정] DataFrame에서 '상승확률'을 읽어와서 float 숫자로 변환
                ai_prob_str = str(row.get("상승확률", "0")).replace("%", "")
                try: ai_prob = float(ai_prob_str)
                except ValueError: ai_prob = 0.0

                strategy_list.append({
                    "symbol": sym, 
                    "symbol_name": str(row.get("종목명", "")), 
                    "ai_prob": ai_prob,           # 👈 새롭게 추가된 AI 확률 전송!
                    "ma_5": float(clean_num(row.get("MA_5", "0"))), 
                    "ma_20": float(clean_num(row.get("MA_20", "0"))), 
                    "RSI": float(clean_num(row.get("RSI", "0"))), 
                    "macd": float(clean_num(row.get("MACD", "0"))), 
                    "signal": sig,
                    "status_msg": "분석 완료"      # 👈 새롭게 추가된 메시지 전송!
                })
            try: self.db.update_strategy_table(strategy_list)
            except Exception as e: self.add_log(f"🚨 StrategyStatus DB 에러: {e}", "error")

    @QtCore.pyqtSlot(object) 
    def update_market_table_slot(self, df):
        standard_cols = ['종목코드','종목명','현재가','시가','고가','저가','1분등락률','거래대금','거래량에너지','이격도','거래량']
        if df.empty: TradeData.market.df = pd.DataFrame(columns=standard_cols); return
        if '종목코드' not in df.columns and 'Symbol' in df.columns: df = df.rename(columns={'Symbol': '종목코드', 'Name': '종목명', 'Price': '현재가'})
        for col in standard_cols:
            if col not in df.columns: df[col] = "0"
        TradeData.market.df = df[standard_cols]; self.update_table(self.tbMarket, TradeData.market.df)

    def load_real_holdings(self):
        try:
            self.my_holdings = self.api_manager.get_real_holdings()
            if self.my_holdings:
                holdings_str = ", ".join([f"{self.DYNAMIC_STOCK_DICT.get(code, code)}({info['qty']}주)" for code, info in self.my_holdings.items()])
                self.add_log(f"💼 [보유 종목 로드] {len(self.my_holdings)}개 확인", "success")
            else: self.add_log("💼 [보유 종목] 현재 보유 종목 없음", "info")
        except Exception as e: self.add_log(f"🚨 잔고 로드 에러: {e}", "error"); return
            
        my_cash = self.api_manager.get_balance(); my_cash_float = float(my_cash) if my_cash is not None else 0.0
        cash_str = f"{my_cash_float:,.0f}" if my_cash is not None else "0"
        
        account_rows = []; is_first = True; total_invested = 0; total_current_val = 0; stock_details_str = ""
        
        for code, info in list(self.my_holdings.items()):
            # ✅ 여기를 0.2으로 수정하세요! (기존 0.2 또는 0.25)
            time.sleep(0.2)
            buy_price = info['price']; buy_qty = info['qty']; stock_name = self.DYNAMIC_STOCK_DICT.get(code, f"알수없음_{code}")
            self.my_holdings[code]['high_watermark'] = buy_price

            df = self.api_manager.fetch_minute_data(code); pnl_str = "0.00%"; curr_price = buy_price
            if df is not None:
                curr_price = df.iloc[-1]['close']; profit_rate = ((curr_price - buy_price) / buy_price) * 100; pnl_str = f"{profit_rate:.2f}%"
                self.my_holdings[code]['high_watermark'] = max(buy_price, curr_price); self.my_holdings[code]['buy_time'] = datetime.now(); self.my_holdings[code]['half_sold'] = False
                stock_details_str += f"    🔸 {stock_name}: 매입 {buy_price:,.2f} -> {curr_price:,.2f} ({profit_rate:+.2f}%)\n"
            else: stock_details_str += f"    🔸 {stock_name}: 매입 {buy_price:,.2f} -> 통신지연\n"
                
            total_invested += (buy_price * buy_qty); total_current_val += (curr_price * buy_qty)
            now_time = datetime.now().strftime('%H:%M:%S')
            account_rows.append({'시간': now_time, '종목코드': code, '종목명': stock_name, '보유수량': buy_qty, '평균매입가': f"{buy_price:,.0f}", '현재가': f"{curr_price:,.0f}", '평가손익금': pnl_str, '수익률': pnl_str, '주문가능금액': cash_str if is_first else "" })
            is_first = False

        total_unrealized_profit = total_current_val - total_invested; total_asset = my_cash_float + total_current_val
        try: realized_profit = float(self.db.get_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", "0.0"))
        except: realized_profit = 0.0
            
        briefing_msg = f"📊 [수동 잔고조회]\n    💎 자산: {int(total_asset):,}원 | 누적손익: {int(realized_profit):+,}원 | 보유손익: {int(total_unrealized_profit):+,}원"
        if len(self.my_holdings) > 0: briefing_msg += f"\n\n{stock_details_str.rstrip()}"
            
        self.add_log(briefing_msg, "send")
            
        if account_rows: 
            df_acc = pd.DataFrame(account_rows)
            acc_cols = ['시간', '종목코드','종목명','보유수량','평균매입가','현재가','평가손익금', '수익률','주문가능금액']
            for c in acc_cols:
                if c not in df_acc.columns: df_acc[c] = ""
            TradeData.account.df = df_acc[acc_cols]
            QtCore.QTimer.singleShot(500, lambda: self.update_table(self.tbAccount, TradeData.account.df))

        # =====================================================================
        # 🚀 [추가] 스마트폰/HTS 예약매도, 예약매수(미체결) 완벽 동기화!
        # =====================================================================
        try:
            # 1. KIS 서버에서 미체결(예약) 리스트를 싹 다 긁어옵니다.
            # 🔥 [경로 에러 수정] 총괄 매니저가 아니라, 통신 전담반(api)에게 직접 지시하도록 '.api'를 추가했습니다!
            if hasattr(self.api_manager, 'api') and hasattr(self.api_manager.api, 'get_unfilled_orders'):
                unfilled_orders = self.api_manager.api.get_unfilled_orders()
            else:
                unfilled_orders = self.api_manager.get_unfilled_orders()
            
            # 2. 중복 등록을 막기 위해 현재 UI 표에 있는 주문번호를 검사합니다.
            existing_ord_nos = []
            for row in range(self.tbOrder.rowCount()):
                item = self.tbOrder.item(row, 0) # 0번 컬럼 = 주문번호
                if item: existing_ord_nos.append(item.text())

            sync_count = 0
            for order in unfilled_orders:
                ord_no = order['주문번호']
                if ord_no in existing_ord_nos: continue # 이미 UI에 띄워진 내역이면 패스
                
                # 시간 포맷 예쁘게 깎기 (143000 -> 14:30:00)
                raw_t = order['주문시간']
                time_str = f"{raw_t[:2]}:{raw_t[2:4]}:{raw_t[4:]}" if len(raw_t) == 6 else raw_t
                
                # 표와 DB에 집어넣기 위한 주머니(딕셔너리) 세팅
                order_info = {
                    '주문번호': ord_no,
                    '종목코드': order['종목코드'],
                    '종목명': order['종목명'],
                    '주문종류': f"예약{order['주문종류']}", # 예약매수, 예약매도
                    '주문가격': f"{order['주문가격']:,.0f}",
                    '주문수량': order['주문수량'],
                    '체결수량': order['주문수량'] - order['미체결수량'], # 일부만 체결된 수량 반영
                    '주문시간': time_str,
                    '상태': '미체결',
                    '수익률': '0.00%'
                }
                
                # 표에 띄우고 DB에 저장! (이제부터 주삐 탐정이 이 주문도 감시합니다)
                if hasattr(self, 'trade_worker') and self.trade_worker is not None: 
                    self.trade_worker.sig_order_append.emit(order_info)
                else:
                    self.append_order_table_slot(order_info)
                sync_count += 1
                
            if sync_count > 0:
                self.add_log(f"🔄 HTS/스마트폰 예약(미체결) 주문 {sync_count}건 동기화 완료!", "success")
                
        except Exception as e:
            self.add_log(f"🚨 예약 내역 동기화 실패: {e}", "error")

    def initUI(self):
        ui_file_path = resource_path("GUI/Main.ui")
        uic.loadUi(ui_file_path, self)
        
        if hasattr(self, 'btnConnected'): self.btnConnected.hide()
        
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint); self.setGeometry(0, 0, 1920, 1080); self.centralwidget.setStyleSheet("background-color: rgb(5,5,15);") 
        self.tbMarket = QtWidgets.QTableWidget(self.centralwidget); self.tbMarket.setGeometry(5, 50, 1420, 240); self._setup_table(self.tbMarket, list(TradeData.market.df.columns))
        self.tbAccount = QtWidgets.QTableWidget(self.centralwidget); self.tbAccount.setGeometry(5, 295, 1420, 240); self._setup_table(self.tbAccount, list(TradeData.account.df.columns))
        self.tbOrder = QtWidgets.QTableWidget(self.centralwidget); self.tbOrder.setGeometry(5, 540, 1420, 240); self._setup_table(self.tbOrder, list(TradeData.order.df.columns))
        self.tbStrategy = QtWidgets.QTableWidget(self.centralwidget); self.tbStrategy.setGeometry(5, 785, 1420, 240); self._setup_table(self.tbStrategy, list(TradeData.strategy.df.columns))
        self.txtLog = QtWidgets.QPlainTextEdit(self.centralwidget); self.txtLog.setGeometry(1430, 95, 485, 930); self.txtLog.setReadOnly(True); self.txtLog.setStyleSheet("background-color: rgb(20, 30, 45); color: white; font-family: Consolas; font-size: 13px;")
        
        self.btnDataCreatTest = self._create_nav_button("데이터 자동생성 시작", 5)
        self.btnDataSendTest = self._create_nav_button("수동 DB 동기화", 310) 
        self.btnSimulDataTest = self._create_nav_button("계좌 잔고 조회", 615)
        self.btnAutoDataTest = self._create_nav_button("자동 매매 가동 (GO)", 920)
        self.btnDataClearTest = self._create_nav_button("화면 데이터 초기화", 1225)
        self.btnClose = QtWidgets.QPushButton(" X ", self.centralwidget); self.btnClose.setGeometry(1875, 5, 40, 40); self.btnClose.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")
        
        self.btnDataCreatTest.clicked.connect(self.btnDataCreatClickEvent)
        self.btnDataSendTest.clicked.connect(self.btnDataSendClickEvent)
        self.btnSimulDataTest.clicked.connect(self.btnSimulTestClickEvent)
        self.btnAutoDataTest.clicked.connect(self.btnAutoTradingSwitch)
        self.btnDataClearTest.clicked.connect(self.btnDataClearClickEvent)
        self.btnClose.clicked.connect(self.btnCloseClickEvent)
        self.shortcut_sell = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Shift+W"), self); self.shortcut_sell.activated.connect(self.emergency_sell_event)
        self.hide()

    # =====================================================================
    # ⚙️ [핵심 추가] 환경설정 기본값 DB 자동 세팅 및 관리 함수
    # =====================================================================
    def init_default_settings(self):
        """
        프로그램 최초 실행 시, 사용할 모든 알고리즘 및 대기시간 변수를 DB에 
        자동으로 등록해주는 함수입니다. 
        이후 사용자는 DB(SQLite DB Browser 등)를 열어 SharedSettings 테이블의 값만 수정하면 
        프로그램 코드 수정 없이 실시간으로 설정이 반영됩니다.
        """
        # (그룹명, 키값, 기본값, 설명)
        default_settings = [
            # 🕒 [시간 설정] (HHMM 형식) - 장 시작/마감 시간
            ("TRADE", "TIME_START_DOM", "0900", "국내 주식 자동매매 시작 시간"),
            ("TRADE", "TIME_CLOSE_DOM", "1520", "국내 주식 신규매수 차단 및 방어 익절 시작 시간"),
            ("TRADE", "TIME_IMMINENT_DOM", "1525", "국내 주식 마감 임박 (강제 전체 청산 시간)"),
            ("TRADE", "TIME_END_DOM", "1530", "국내 주식 장 종료 시간"),
            ("TRADE", "TIME_START_OVS", "2230", "해외 주식 자동매매 시작 시간"),
            ("TRADE", "TIME_CLOSE_OVS", "0430", "해외 주식 마감 임박 시작 시간"),

            # 🔥 [추가] 리스크 관리 셧다운 설정
            ("RISK", "MAX_CONSECUTIVE_LOSS", "5", "연속 손절 시 매수 셧다운 횟수"),
            ("RISK", "DAILY_STOP_LOSS_PCT", "-10.0", "일일 누적 손실 제한 (%)"),
            ("RISK", "IS_LOCKED", "N", "매수 기능 강제 잠금 여부 (Y/N)"),
            
            # 💸 [리스크 및 컷오프(손/익절) 설정]
            ("TRADE", "CRASH_LIMIT", "-1.5", "시장(ETF) 폭락 감지 기준 (%) - 도달 시 매수 정지"),
            ("TRADE", "LOSS_STREAK_LIMIT", "5", "연속 손절 허용 횟수 - 이 횟수만큼 손절나면 당일 매수 일시 중단"),
            ("TRADE", "USE_TRAILING", "Y", "트레일링 스탑 기능 사용 여부 (Y/N)"),
            ("TRADE", "TRAILING_START_YIELD", "1.5", "트레일링 스탑이 켜지는 최소 수익률 (%)"),
            ("TRADE", "TRAILING_STOP_GAP", "0.8", "최고점 대비 하락 허용 폭 (%) - 이만큼 떨어지면 즉시 익절"),
            ("TRADE", "MAX_HOLDING_TIME", "20", "최대 보유 시간 (분) - 이 시간이 지나면 기계적 청산"),
            
            # 📊 [비중 및 탐색 알고리즘 설정]
            ("AI", "THRESHOLD", "70.0", "AI 매수 추천 최소 확신도 커트라인 (%)"),
            ("TRADE", "SCAN_DELAY", "0.4", "API 호출 딜레이 (초) - 증권사 초당 호출 제한 방어용"),
            ("TRADE", "MAX_STOCKS", "15", "계좌 내 최대 동시 보유 가능 종목 개수"),
            ("TRADE", "MIN_SCAN_STOCKS", "60", "한 사이클(1분)당 스캔할 주도주 개수 (속도 최적화용)"),
            ("TRADE", "USE_FUNDS_PERCENT", "100", "총 자산 중 자동매매에 사용할 금액 비중 (%)"),
            ("TRADE", "PYRAMIDING_YIELD", "3.0", "불타기(추가 매수)를 시도할 최소 수익률 (%)"),
            ("TRADE", "PYRAMIDING_RATE", "50.0", "불타기 시 기존 투자금 대비 추가 진입할 금액 비율 (%)"),
            
            # 📈 [ATR(변동성) 기반 비중 조절 설정]
            ("TRADE", "ATR_HIGH_LIMIT", "5.0", "변동성(ATR) 극심함 판단 기준 (%)"),
            ("TRADE", "ATR_HIGH_RATIO", "50.0", "변동성 극심할 때 매수 비중 축소 비율 (%)"),
            ("TRADE", "ATR_MID_LIMIT", "2.5", "변동성(ATR) 다소 높음 판단 기준 (%)"),
            ("TRADE", "ATR_MID_RATIO", "70.0", "변동성 높을 때 매수 비중 축소 비율 (%)"),

            # 💰 [30종목용 공격적 비중 설정]
            ("TRADE", "BUDGET_WEIGHT_HIGH", "12.0", "AI 확신도 최상일 때 진입 비중 (12%)"),
            ("TRADE", "BUDGET_WEIGHT_MID", "7.0", "AI 확신도 중간일 때 진입 비중 (7%)"),
            ("TRADE", "BUDGET_WEIGHT_LOW", "4.0", "AI 확신도 커트라인 통과 시 기본 비중 (4%)"),
            ("TRADE", "MAX_INVEST_PER_STOCK", "20.0", "한 종목당 최대 투자 한도 (%)"),
            
            # 🔥 [핵심 추가] 실전 3대장 방어막 세팅
            ("TRADE", "COOLDOWN_MINUTES", "10", "매도(청산) 후 재진입 금지 시간 (분) - 복수혈전 방지"),
            ("TRADE", "USE_SMART_LIMIT", "Y", "시장가 대신 스마트 지정가 사용 여부 (Y/N) - 슬리피지 방어"),
            ("API", "GLOBAL_API_DELAY", "0.05", "API 초당 호출 제한 방어용 딜레이 (초) - 트래픽 교통정리"),

            # 💸 [리스크 및 컷오프(손/익절) 설정] (이 부분을 찾아서 아래처럼 덮어쓰거나 추가하세요)
            ("TRADE", "PROFIT_RATE", "2.0", "기본 기계적 익절 라인 (%) - 초단타용"),
            ("TRADE", "STOP_RATE", "1.0", "기본 기계적 손절 라인 (%) - 밀림 방지용 짧은 손절"),
            ("TRADE", "TRAILING_STOP_GAP", "0.5", "최고점 대비 하락 허용 폭 (%) - 0.5%만 꺾여도 즉시 익절"),
            ("TRADE", "STRAT_PROFIT_PRESERVE", "0.3", "전략 매도 시 최소 수익 보존 라인 (%)"),
        ]

        try:
            inserted_count = 0
            # 위에서 정의한 기본값 리스트를 반복하며 DB에 없는 녀석만 밀어 넣습니다.
            for group, key, val, desc in default_settings:
                # DB에서 현재 값을 가져와 봅니다.
                current_val = self.db.get_shared_setting(group, key, default_value=None)
                
                # DB에 세팅값이 등록되어 있지 않다면 (최초 실행)
                if current_val is None:
                    # 기본값을 DB에 써줍니다.
                    self.db.set_shared_setting(group, key, val)
                    inserted_count += 1
                    
            if inserted_count > 0:
                self.add_log(f"⚙️ [초기화] {inserted_count}개의 기본 환경설정이 DB에 등록되었습니다. 이제 DB에서 직접 수정 가능합니다.", "info")
        except Exception as e:
            self.add_log(f"⚠️ [오류] 환경설정 기본값 세팅 중 에러 발생: {e}", "error")

    @QtCore.pyqtSlot()
    def show_python_ui(self):
        self.show() 

    def btnSimulTestClickEvent(self):
        self.load_real_holdings()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton and event.modifiers() == Qt.ControlModifier: 
            self.show_algorithm_menu(event.globalPos())
        elif event.button() == Qt.LeftButton: 
            self._isDragging = True
            self._startPos = event.globalPos() - self.frameGeometry().topLeft()

    def show_algorithm_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet("QMenu { background-color: rgb(30, 40, 60); color: white; font-size: 14px; border: 1px solid Silver; } QMenu::item { padding: 10px 25px; } QMenu::item:selected { background-color: rgb(80, 120, 160); }")
        
        if SystemConfig.MARKET_MODE == "DOMESTIC": current_mode_str = "🇰🇷 국내 주식"
        elif SystemConfig.MARKET_MODE == "OVERSEAS": current_mode_str = "🌐 해외 주식"
        else: current_mode_str = "🚀 해외 선물"
        
        act_toggle_mode = menu.addAction(f"🔄 시장 모드 변경 (현재: {current_mode_str})")
        menu.addSeparator()
        
        act_collect = menu.addAction("📡 Data Collector (1000종목 수집기 실행)")
        act_train = menu.addAction("🧠 Jubby AI Trainer (AI 학습기 실행)")
        
        menu.addSeparator() 
        # ⭐ [추가됨] 셧다운 강제 해제 메뉴 버튼 생성
        act_unlock = menu.addAction("🔓 주삐 셧다운(매수 잠금) 강제 해제")
        
        menu.addSeparator() 
        act_panic = menu.addAction("🛑 긴급 전체 청산 및 자동매매 종료 (Panic Sell)")
        menu.addSeparator() 
        act_save_log = menu.addAction("💾 현재 로그 텍스트로 저장 (Save Log)") 

        action = menu.exec_(pos)
        
        if action == act_toggle_mode: self.toggle_market_mode() 
        elif action == act_collect: self.start_data_collector()
        elif action == act_train: self.start_ai_trainer()
        
        # ⭐ [추가됨] 해제 버튼을 클릭했을 때의 동작 로직
        elif action == act_unlock:
            # 1. DB의 잠금 상태를 'N'(풀림)으로 변경
            self.db.set_shared_setting("RISK", "IS_LOCKED", "N")
            
            # 2. 누적 손실률 초기화 (필요시)
            if hasattr(self, 'daily_total_pnl_pct'):
                self.daily_total_pnl_pct = 0.0 
            
            # 3. 워커(자동매매 일꾼)의 연패 기록도 0으로 초기화
            if hasattr(self, 'trade_worker') and self.trade_worker is not None:
                self.trade_worker.loss_streak_cnt = 0
                
            # 4. 로그에 성공 메세지 출력
            if hasattr(self, 'add_log'):
                self.add_log("🛡️ [시스템] 관리자 권한으로 매수 잠금이 해제되었습니다. 다시 탐색을 시작합니다.", "success")
                
        elif action == act_panic: self.start_panic_sell()
        elif action == act_save_log: self.save_manual_log()

    def toggle_market_mode(self):
        if getattr(self, 'is_stopping', False) or (hasattr(self, 'trade_worker') and self.trade_worker.is_running):
            self.add_log("⚠️ 자동매매 가동 중에는 변경 불가능", "warning")
            return

        if SystemConfig.MARKET_MODE == "DOMESTIC":
            SystemConfig.MARKET_MODE = "OVERSEAS"
            self.add_log("🌐 [모드 변경] 미국 주식 모드 전환", "send")
            self.api_manager.ACCOUNT_NO = "50172151"; self.api_manager.api.account_no = "50172151"
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            SystemConfig.MARKET_MODE = "OVERSEAS_FUTURES"
            self.add_log("🚀 [모드 변경] 해외선물 모드 전환", "send")
            self.api_manager.ACCOUNT_NO = "60039684"; self.api_manager.api.account_no = "60039684"
        else:
            SystemConfig.MARKET_MODE = "DOMESTIC"
            self.add_log("🇰🇷 [모드 변경] 국내 주식 모드 전환", "send")
            self.api_manager.ACCOUNT_NO = "50172151"; self.api_manager.api.account_no = "50172151"

        try: self.db.set_shared_setting("SYSTEM", "MARKET_MODE", SystemConfig.MARKET_MODE)
        except: pass
        
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            query = f"SELECT symbol, symbol_name FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
            df_dict = pd.read_sql(query, conn)
            conn.close()
            
            if SystemConfig.MARKET_MODE == "DOMESTIC": self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str).str.zfill(6), df_dict['symbol_name']))
            else: self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str), df_dict['symbol_name']))
        except Exception: self.DYNAMIC_STOCK_DICT = {}

        if hasattr(self.strategy_engine, 'load_ai_brain'): self.strategy_engine.load_ai_brain()
        self.btnDataClearClickEvent()

    def start_panic_sell(self):
        # 🛡️ [방어막] 파이썬 에러로 인해 프로그램이 팅기는 것을 원천 차단합니다!
        try:
            if not hasattr(self, 'trade_worker') or not self.trade_worker.is_running: return
            if len(self.my_holdings) == 0: self.btnAutoTradingSwitch(); return

            # 🚀 [버그 수정] 딕셔너리를 읽는 도중 크기가 변해서 팅기는 현상(RuntimeError) 완벽 해결!
            stock_names = [self.DYNAMIC_STOCK_DICT.get(c, c) for c in list(self.my_holdings.keys())]
            
            msg = f"🚨 [긴급 전체 청산 발동]\n전체 시장가 매도 진행!\n대상: {', '.join(stock_names)}"
            self.add_log(msg, "error"); self.send_kakao_msg(msg)
            self.trade_worker.panic_mode = True 
            
        except Exception as e:
            self.add_log(f"🚨 긴급 청산 시작 중 에러 발생: {e}", "error")

    @QtCore.pyqtSlot()
    def panic_sell_done_slot(self):
        self.is_stopping = False 
        self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
        self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")

    def btnAutoTradingSwitch(self):
        # 🛡️ [방어막] 버튼 클릭 시 발생하는 모든 에러를 흡수하여 팅김을 방지합니다.
        try:
            if getattr(self, 'is_stopping', False): return
                
            if not self.trade_worker.is_running: 
                try:
                    conn = self.db._get_connection(self.db.shared_db_path)
                    conn.execute("DELETE FROM TradeHistory"); conn.close()
                    # 🚀 [버그 수정] 컬럼 개수를 9개로 정확히 맞춰서 Ticker 오류 방지
                    TradeData.order.df = pd.DataFrame(columns=['주문번호','시간','종목코드','종목명','주문종류','주문가격','주문수량','체결수량','상태'])
                    self.tbOrder.setRowCount(0)
                except Exception: pass

                self.trade_worker.panic_mode = False 
                self.trade_worker.start()
                self.btnAutoDataTest.setText("자동 매매 중단 (STOP)")
                self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
                self.add_log("🚀 [주삐 엔진] 1분 단위 감시망 가동!", "success")
                
            else: 
                self.is_stopping = True 
                self.btnAutoDataTest.setText("감시망 종료 대기중...")
                self.btnAutoDataTest.setStyleSheet("background-color: rgb(40, 40, 40); color: Gray;")
                
                # 🚀 [버그 수정] 매매 스레드뿐만 아니라 탐정 스레드도 안전하게 같이 꺼줍니다!
                if hasattr(self, 'trade_worker'):
                    self.trade_worker.is_running = False 
                if hasattr(self, 'detective_worker'):
                    self.detective_worker.is_running = False

        except Exception as e:
            self.add_log(f"🚨 자동매매 스위치 작동 중 에러: {e}", "error")

    @QtCore.pyqtSlot()
    def check_worker_stopped(self):
        if self.btnAutoDataTest.text() == "감시망 종료 대기중...":
            self.is_stopping = False
            self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("✅ [주삐 엔진] 감시망이 안전하게 종료되었습니다.", "info")
            try: self.db.update_system_status('TRADER', '감시망 중단 🔴', 0)
            except: pass

    def save_manual_log(self):
        try:
            text = self.txtLog.toPlainText()
            os.makedirs("Logs", exist_ok=True)
            filename = f"Logs/Manual_Log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt" 
            with open(filename, "w", encoding="utf-8") as f: f.write(text)
            self.add_log(f"✅ 로그 캡처 완료", "success")
        except Exception: pass

    def start_data_collector(self):
        try:
            if hasattr(self, 'collector_worker') and self.collector_worker.isRunning(): return
            app_key = getattr(self.api_manager, 'APP_KEY', ""); app_secret = getattr(self.api_manager, 'APP_SECRET', ""); account_no = getattr(self.api_manager, 'ACCOUNT_NO', ""); is_mock = getattr(self.api_manager, 'IS_MOCK', True)
            self.collector_worker = DataCollectorWorker(app_key, app_secret, account_no, is_mock); self.collector_worker.sig_log.connect(self.add_log); self.collector_worker.start()
        except Exception: pass

    def start_ai_trainer(self):
        if hasattr(self, 'trade_worker') and self.trade_worker.is_running: return
        if hasattr(self, 'trainer_worker') and self.trainer_worker.isRunning(): return
        self.trainer_worker = AITrainerWorker(); self.trainer_worker.sig_log.connect(self.add_log); self.trainer_worker.start()
        
    def mouseMoveEvent(self, event):
        if hasattr(self, '_isDragging') and self._isDragging:
            # 1. 메인 윈도우를 마우스 따라 이동시킵니다.
            self.move(event.globalPos() - self._startPos)
            
            # 🚀 [추가] 메인 윈도우가 움직일 때 Ticker도 자석처럼 붙어서 움직입니다!
            if hasattr(self, 'ticker_window') and self.ticker_window.isVisible():
                self.ticker_window.snap_to_main()

    def mouseReleaseEvent(self, event): self._isDragging = False

    # =====================================================================
    # ⭐ [핵심 추가] 메인 창 숨김/최소화/복구 시 Ticker 창 완벽 동기화
    # =====================================================================
    def showEvent(self, event):
        """ 메인 창이 화면에 나타날 때 Ticker 창도 강제로 소환합니다. """
        super().showEvent(event)
        if hasattr(self, 'ticker_window') and self.ticker_window:
            self.ticker_window.show()       # 숨어있던 Ticker 보이기
            self.ticker_window.raise_()     # Ticker를 화면 맨 앞으로 끌어올리기
            self.ticker_window.snap_to_main() # 메인 창 옆구리에 예쁘게 다시 붙이기

    def changeEvent(self, event):
        """ 메인 창의 상태(최소화, 전체화면 등)가 변할 때를 감지합니다. """
        if event.type() == QtCore.QEvent.WindowStateChange:
            # 1. 메인 창을 아래로 내렸을 때 (최소화) -> Ticker도 같이 내림
            if self.isMinimized():
                if hasattr(self, 'ticker_window') and self.ticker_window:
                    self.ticker_window.showMinimized()
                    
            # 2. 메인 창을 다시 눌러서 띄웠을 때 (복구) -> Ticker도 같이 복구
            elif self.windowState() == QtCore.Qt.WindowNoState or self.windowState() == QtCore.Qt.WindowMaximized:
                if hasattr(self, 'ticker_window') and self.ticker_window:
                    self.ticker_window.showNormal()
                    self.ticker_window.raise_()
                    self.ticker_window.snap_to_main()
                    
        super().changeEvent(event)
        
    # (이 아래로는 기존에 있던 emergency_sell_event 등 함수들이 이어집니다)
    def emergency_sell_event(self):
        """ [수동 판매 손익 합산 버전] 사용자가 선택한 종목을 즉시 매도하고 수익금을 정산합니다. """
        # 🚀 [방어막 1] 이미 처리 중이면 두 번 눌려도 무시합니다! (팅김 완벽 방지)
        if getattr(self, 'is_emergency_running', False): return
        self.is_emergency_running = True

        try:
            # 1. 사용자가 tbAccount(잔고표)에서 어떤 종목을 선택했는지 확인합니다.
            selected_ranges = self.tbAccount.selectedRanges() 
            if not selected_ranges: return
            
            # 2. 선택한 줄의 1번째 칸(종목코드)에서 코드를 읽어옵니다.
            row = selected_ranges[0].topRow()
            item = self.tbAccount.item(row, 1) # 종목코드가 있는 열 (0번:시간, 1번:코드)
            
            if item is None: return
            code = item.text().strip() 
            if code == "-" or not code: return
            
            # 3. 내 주머니(my_holdings)에 해당 종목이 있는지 확인합니다.
            if code in self.my_holdings:
                info = self.my_holdings[code]
                buy_price = info['price']   # 내가 샀던 가격
                qty = info['qty']           # 들고 있는 수량
                stock_name = self.DYNAMIC_STOCK_DICT.get(code, code)

                # 🚀 [추가] 정산을 위해 현재 가격을 한투 서버에서 가져옵니다.
                df = self.api_manager.fetch_minute_data(code)
                if df is not None:
                    curr_price = float(df.iloc[-1]['close']) # 현재가 확정
                else:
                    # 통신 실패 시 UI 표에 적힌 현재가라도 긁어와서 계산합니다.
                    # 통신 실패 시 UI 표에 적힌 현재가라도 긁어와서 계산합니다.
                    curr_price = buy_price # 최악의 경우 본전으로 가정

                # 4. 한투 서버에 매도 주문을 보냅니다 (시장가 01 사용)
                # 🔥 [트래픽 초과 방어] 서버가 바쁘면 최대 5번까지 1초 간격으로 끈질기게 자동 재시도합니다!
                res_odno = None
                for i in range(5):
                    res_odno = self.api_manager.sell(code, qty)
                    if res_odno: 
                        break # 성공하면 즉시 반복문 탈출!
                    
                    error_msg = getattr(self.api_manager.api, 'last_error_msg', '')
                    if "초과" in error_msg or "초당" in error_msg:
                        self.add_log(f"⏳ [{stock_name}] 서버 트래픽 초과! 1초 대기 후 재시도합니다... ({i+1}/5)", "warning")
                        time.sleep(1.0)
                        QtWidgets.QApplication.processEvents() # 🔥 대기하는 1초 동안 프로그램 화면이 멈추지(렉) 않게 풀어주는 마법!
                    elif "잔고" in error_msg:
                        self.add_log(f"🚨 [{stock_name}] 이미 팔렸거나 매도할 잔고가 없습니다.", "error")
                        break # 잔고가 없으면 재시도 포기
                    else:
                        break # 기타 알 수 없는 에러도 포기

                if res_odno: # 매도 주문 성공 (주문번호를 받음)
                    # 🚀 [추가] 실현 손익 계산 ( (현재가 - 매수가) * 수량 )
                    realized_profit = (curr_price - buy_price) * qty
                    profit_rate = ((curr_price - buy_price) / buy_price) * 100

                    # 🚀 [추가] 자동매매 일꾼(trade_worker)의 누적 수익금 변수에 합산!
                    if hasattr(self, 'trade_worker'):
                        self.trade_worker.cumulative_realized_profit += realized_profit
                        
                        # 누적 수익률 계산을 위해 전역 변수도 업데이트
                        self.daily_total_pnl_pct += profit_rate 
                        
                        # DB에도 실시간으로 저장해서 C# UI가 알 수 있게 합니다.
                        self.db.set_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", 
                                                   str(self.trade_worker.cumulative_realized_profit))

                    # 5. 내부 관리 목록에서 삭제 및 UI 갱신
                    del self.my_holdings[code]
                    self.tbAccount.removeRow(row)
                    
                    # 6. Ticker 창 및 로그에 '수동 판매 완료' 기록
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    msg = f"🚨 [수동 매도 완료] {stock_name} | {curr_price:,.0f}원 | 손익: {int(realized_profit):+,}원 ({profit_rate:.2f}%)"
                    self.add_log(msg, "sell")
                    
                    # 주문 내역 표에도 기록 (Ticker가 체결완료로 바꿀 수 있게 미체결 상태로 보냄)
                    # 🚀 [추가] C# 화면과 동기화를 위해 DB에도 수동 매도 기록을 남깁니다!
                    try:
                        self.db.insert_trade_history(res_odno, code, "SELL", curr_price, qty, profit_rate)
                    except Exception as e:
                        print(f"수동 매도 DB 기록 에러: {e}")

                    # 주문 내역 표에도 기록 (Ticker가 체결완료로 바꿀 수 있게 미체결 상태로 보냄)
                    if hasattr(self, 'trade_worker'): 
                        self.trade_worker.sig_order_append.emit({
                            '주문번호': res_odno,
                            '종목코드': code, 
                            '종목명': stock_name, 
                            '주문종류': '수동매도', 
                            '주문가격': f"{curr_price:,.0f}", 
                            '주문수량': qty, 
                            '체결수량': 0, 
                            '주문시간': now_str, 
                            '상태': '미체결', 
                            '수익률': f"{profit_rate:.2f}%"
                        })
                else:
                    error_msg = getattr(self.api_manager.api, 'last_error_msg', '알 수 없는 오류')
                    self.add_log(f"❌ [{stock_name}] 수동 매도 주문이 최종 거절되었습니다. 사유: {error_msg}", "error")

        except Exception as e:
            self.add_log(f"🚨 수동 매도 처리 중 에러: {e}", "error")
        finally:
            # 🚀 [방어막 해제] 처리가 끝나면 자물쇠를 풀어줍니다.
            self.is_emergency_running = False
            
    def get_ai_probability(self, code):
        # -------------------------------------------------------------
        # 🚀 [하이브리드 엔진 2] AI 매수 탐색 시에도 캐시 메모리 활용
        # -------------------------------------------------------------
        current_minute = datetime.now().strftime("%H:%M")
        
        if self.last_fetch_time.get(code) != current_minute:
            df = self.api_manager.fetch_minute_data(code)
            if df is not None and len(df) >= 26:
                df = self.strategy_engine.calculate_indicators(df)
                self.df_cache[code] = df
                self.last_fetch_time[code] = current_minute
        else:
            df = self.df_cache.get(code)

        if df is None or len(df) < 26: 
            return 0.0, 0, None
        
        # 🚀 0초 딜레이 DB 실시간 가격 가져와서 종가 덮어치기
        realtime_price = self.db.get_realtime_price(code)
        curr_price = realtime_price if realtime_price > 0 else float(df.iloc[-1]['close'])
        
        df.at[df.index[-1], 'close'] = curr_price 
        
        prob = 0.0
        if self.strategy_engine.ai_model is not None:
            features = self.strategy_engine.get_ai_features(df)
            if features is not None: prob = self.strategy_engine.ai_model.predict_proba(features)[0][1]
        return prob, curr_price, df
    
    @QtCore.pyqtSlot(object) 
    def update_account_table_slot(self, df): 
        # 🚀 [수정] 백그라운드 데이터셋을 먼저 갱신해야 DB 동기화가 이루어집니다.
        TradeData.account.df = df 
        self.update_table(self.tbAccount, df)
        
    @QtCore.pyqtSlot(object) 
    def update_strategy_table_slot(self, df): 
        # 🚀 [수정] 백그라운드 데이터셋을 먼저 갱신해야 DB 동기화가 이루어집니다.
        TradeData.strategy.df = df
        self.update_table(self.tbStrategy, df)

    @QtCore.pyqtSlot(str, str) 
    def add_log(self, text, log_type="info"):
        self.sig_safe_log.emit(text, log_type)

    @QtCore.pyqtSlot(str, str)
    def _safe_append_log_sync(self, text, log_type):
        color = {"info": "white", "success": "lime", "warning": "yellow", "error": "red", "send": "cyan", "recv": "orange", "buy": "#4B9CFF", "sell": "#FF4B4B"}.get(log_type, "white")
        formatted_text = text.replace('\n', '<br>&nbsp;&nbsp;&nbsp;&nbsp;')
        html_msg = f'<span style="color:{color}"><b>{datetime.now().strftime("[%H:%M:%S]")}</b> {formatted_text}</span>'
        
        # 🔥 [핵심 추가] txtLog가 아직 생성되기 전에 날아온 초기 로그면 팅기지 않게 방어합니다!
        if not hasattr(self, 'txtLog'):
            print(f"[{log_type.upper()}] {text}") # 화면 대신 까만 터미널 창에만 출력
            return
            
        self.txtLog.appendHtml(html_msg)
        
        # 🔥 [핵심 수정 2] 팅김을 유발하던 스크롤 조작 코드를 가장 튼튼하고 안전한 방식으로 변경했습니다.
        self.txtLog.moveCursor(QtGui.QTextCursor.End)
        
        try:
            if hasattr(self, 'db'): self.db.insert_log(log_type.upper(), text)
        except Exception: pass

    def _setup_table(self, table, columns): table.setColumnCount(len(columns)); table.setHorizontalHeaderLabels(columns); self.style_table(table)
    def style_table(self, table): table.setFont(QtGui.QFont("Noto Sans KR", 12)); table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch); table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows); table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection); table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers); table.setStyleSheet("QTableWidget { background-color: rgb(50,80,110); color: Black; selection-background-color: rgb(80, 120, 160); } QHeaderView::section { background-color: rgb(40,60,90); color: Black; font-weight: bold; }")
    def _create_nav_button(self, text, x_pos): btn = QtWidgets.QPushButton(text, self.centralwidget); btn.setGeometry(x_pos, 5, 300, 40); btn.setStyleSheet("background-color: rgb(5,5,15); color: Silver;"); btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor)); btn.installEventFilter(self); return btn
    
    def eventFilter(self, source, event):
        if not source.isEnabled(): return super().eventFilter(source, event)
        if event.type() == QtCore.QEvent.Enter: source.setStyleSheet("background-color: rgb(5,5,10); color: Lime;")
        elif event.type() == QtCore.QEvent.Leave: source.setStyleSheet("background-color: rgb(5,5,10); color: Silver;")
        return super().eventFilter(source, event)
        
    def btnCloseClickEvent(self): QtWidgets.QApplication.quit()         
    def btnDataCreatClickEvent(self): pass
    def generate_and_send_mock_data(self): pass
    
    def update_table(self, tableWidget, df):
        tableWidget.setUpdatesEnabled(False)
        try:
            if df is None or df.empty:
                tableWidget.setRowCount(0); return

            current_headers = [tableWidget.horizontalHeaderItem(i).text() if tableWidget.horizontalHeaderItem(i) else "" for i in range(tableWidget.columnCount())]
            if tableWidget.columnCount() != len(df.columns) or current_headers != list(df.columns):
                tableWidget.setColumnCount(len(df.columns)); tableWidget.setHorizontalHeaderLabels(list(df.columns))
                
            current_row_count = tableWidget.rowCount(); new_row_count = len(df)                    
            if current_row_count < new_row_count:
                for _ in range(new_row_count - current_row_count): tableWidget.insertRow(tableWidget.rowCount())
            elif current_row_count > new_row_count:
                for _ in range(current_row_count - new_row_count): tableWidget.removeRow(tableWidget.rowCount() - 1)
                    
            for i in range(new_row_count):
                for j, col in enumerate(df.columns):
                    val = str(df.iloc[i, j]); item = tableWidget.item(i, j)     
                    if item is None: 
                        item = QtWidgets.QTableWidgetItem(val); item.setTextAlignment(QtCore.Qt.AlignCenter); tableWidget.setItem(i, j, item)
                    else:
                        if item.text() != val: item.setText(val)
                            
        except Exception: pass
        finally: tableWidget.setUpdatesEnabled(True)
        
    @QtCore.pyqtSlot()
    def refresh_order_table(self):
        """ [신규] 취소 등 상태 변화를 화면에 즉시 반영하기 위해 주문 표 새로고침 """
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            query = "SELECT order_no, time, symbol, symbol_name, type, price, quantity, filled_quantity, Status, order_yield FROM TradeHistory WHERE time >= date('now', 'localtime') ORDER BY time DESC"
            df = pd.read_sql(query, conn)
            conn.close()
            if not df.empty:
                df.columns = ['주문번호', '시간', '종목코드', '종목명', '주문종류', '주문가격', '주문수량', '체결수량', '상태', '수익률']
                self.update_table(self.tbOrder, df) # UI에 그리기
        except: pass

    def load_unfilled_orders_to_ui(self):
        """ [신규] 재시작 시 DB에서 미체결 내역을 읽어와 표에 표시 (탐정이 취소할 수 있게 함) """
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            cursor = conn.execute("SELECT order_no, symbol, symbol_name, type, price, quantity, filled_quantity, time FROM TradeHistory WHERE Status = '미체결'")
            rows = cursor.fetchall()
            conn.close()
            for row in rows:
                self.sig_order_append.emit({'주문번호': str(row[0]), '종목코드': row[1], '종목명': row[2], '주문종류': row[3], '주문가격': f"{row[4]:,.0f}", '주문수량': row[5], '체결수량': row[6], '주문시간': row[7], '상태': '미체결', '수익률': '0.00%'})
        except: pass

    # (이 아래는 기존 코드입니다)
    def btnDataClearClickEvent(self): 
        self.tbAccount.setRowCount(0); self.tbStrategy.setRowCount(0); self.tbOrder.setRowCount(0); self.tbMarket.setRowCount(0)

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    mainWindow = FormMain()
    mainWindow.show()
    sys.exit(app.exec_())