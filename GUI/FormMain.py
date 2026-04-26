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
from COMMON.TcpJsonClient import TcpJsonClient

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
# 🕵️‍♂️ [전담반] 주삐 탐정 스레드 (부분체결 완벽 계산 및 동기화)
# =====================================================================
class DetectiveWorker(QThread):
    sig_log = pyqtSignal(str, str)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.is_running = True

    def run(self):
        self.sig_log.emit("🕵️‍♂️ [주삐 탐정] 24시간 부분체결 및 미체결 동기화 전담반 가동!", "info")
        while self.is_running:
            time.sleep(5.0) 
            try: self.smart_cross_check_logic()
            except Exception: pass

    def smart_cross_check_logic(self):
        """ [탐정 전담반 V6 - 최종 완전판] 직무유기 버그 소거 및 강제 마감 처리 """
        try:
            conn = self.mw.db._get_connection(self.mw.db.shared_db_path)
            cursor = conn.execute("SELECT order_no, symbol, type, quantity, price, time FROM TradeHistory WHERE Status IN ('미체결', '부분체결')")
            pending_orders = cursor.fetchall()
            conn.close()
        except: return

        if not pending_orders: return

        exec_details = self.mw.api_manager.fetch_execution_details() or {}
        real_holdings = self.mw.api_manager.get_real_holdings() or {}
        now_time = datetime.now()

        for order in pending_orders:
            db_order_no, symbol, o_type, ordered_qty, price, o_time = order
            ordered_qty = int(ordered_qty)
            stock_name = self.mw.DYNAMIC_STOCK_DICT.get(symbol, symbol)
            target_no = str(db_order_no).strip().lstrip('0') 

            actual_filled_qty = 0
            for k, v in exec_details.items():
                if str(k).strip().lstrip('0') == target_no:
                    actual_filled_qty = int(v)
                    break
            
            # 매수(BUY)인데 이미 잔고에 들어와있다면 체결로 간주
            if actual_filled_qty == 0 and o_type == "BUY" and symbol in real_holdings:
                actual_filled_qty = int(real_holdings[symbol]['qty'])
                if actual_filled_qty < ordered_qty: actual_filled_qty = ordered_qty

            # ---------------------------------------------------------
            # 🚀 [상황 1] 체결 완료! (전량 체결 판별)
            # ---------------------------------------------------------
            if actual_filled_qty >= ordered_qty and ordered_qty > 0:
                self.sig_log.emit(f"✅ [{stock_name}] 거래소 체결(전량) 확인 완료! 표에 반영합니다.", "success")
                self._update_status_safely(db_order_no, "체결완료", ordered_qty, float(price))
                QtCore.QMetaObject.invokeMethod(self.mw, "load_real_holdings", QtCore.Qt.QueuedConnection)
                continue

            # ---------------------------------------------------------
            # 🚀 [상황 2] 30초가 지나도 체결이 안 될 때 (강제 취소 및 마감)
            # ---------------------------------------------------------
            try: order_time = datetime.strptime(o_time, '%Y-%m-%d %H:%M:%S')
            except: continue
            elapsed_seconds = (now_time - order_time).total_seconds()

            if elapsed_seconds > 30:
                res = self.mw.api_manager.cancel_order(db_order_no) 
                
                # 🚀 [버그 완벽 수정 2] 탐정의 멍청한 오판을 막고, KIS에서 긁어온 '진짜 체결량(actual_filled_qty)'만 믿습니다!
                error_msg = getattr(self.mw.api_manager.api, 'last_error_msg', '')
                ghost_keywords = ["이미 취소", "해당 주문", "내역이없습니다", "주문번호가 잘못", "취소가능수량"]
                is_ghost_or_already_canceled = any(kw in error_msg for kw in ghost_keywords)

                if res in ["DONE", "ALREADY_FILLED"] or is_ghost_or_already_canceled:
                    # 취소 처리가 끝났거나, 이미 취소된 주문이라면 -> 진짜 체결량을 기준으로 최종 상태를 못 박습니다!
                    if actual_filled_qty >= ordered_qty:
                        self.sig_log.emit(f"✅ [{stock_name}] 전량 체결 완료!", "success")
                        self._update_status_safely(db_order_no, "체결완료", actual_filled_qty, float(price))
                    elif actual_filled_qty > 0:
                        self.sig_log.emit(f"✂️ [{stock_name}] {actual_filled_qty}주 체결 후 잔여 미체결분 취소 완료!", "warning")
                        self._update_status_safely(db_order_no, "부분체결/잔여취소", actual_filled_qty, float(price))
                    else:
                        self.sig_log.emit(f"🗑️ [{stock_name}] 30초 경과 전량 주문취소 완료!", "warning")
                        self._update_status_safely(db_order_no, "주문취소", 0, float(price))
                    
                    QtCore.QMetaObject.invokeMethod(self.mw, "load_real_holdings", QtCore.Qt.QueuedConnection)
                else:
                    if "초과" not in error_msg: 
                        self.sig_log.emit(f"⚠️ [{stock_name}] 취소 지연: {error_msg}", "warning")

    def _apply_to_holdings(self, symbol, o_type, qty, price):
        """ 탐정이 확인한 '진짜 체결 수량'만 잔고(my_holdings)에 더하거나 뺍니다. """
        with self.mw.holdings_lock:
            if o_type == "BUY":
                if symbol in self.mw.my_holdings:
                    # 이미 있는 종목이면 평단가를 계산해서 합칩니다.
                    old_qty = self.mw.my_holdings[symbol]['qty']
                    old_price = self.mw.my_holdings[symbol]['price']
                    new_qty = old_qty + qty
                    new_price = ((old_price * old_qty) + (price * qty)) / new_qty
                    self.mw.my_holdings[symbol] = {'price': new_price, 'qty': new_qty}
                else:
                    # 새로운 종목이면 그대로 넣습니다.
                    self.mw.my_holdings[symbol] = {'price': price, 'qty': qty}
            elif o_type == "SELL":
                # 매도는 팔린 수량만큼 뺍니다.
                if symbol in self.mw.my_holdings:
                    self.mw.my_holdings[symbol]['qty'] -= qty
                    if self.mw.my_holdings[symbol]['qty'] <= 0:
                        del self.mw.my_holdings[symbol] # 다 팔았으면 바구니에서 삭제

    def _update_status_safely(self, order_no, new_status, filled_qty, real_price):
        """ 
        [DB 방어 업데이트] 
        이미 웹소켓이 '체결완료'로 만든 데이터를 '주문취소'로 덮어쓰는 사고를 100% 차단합니다.
        """
        try:
            conn = self.mw.db._get_connection(self.mw.db.shared_db_path)
            
            # 💡 [핵심 수정] 부분체결 상태도 업데이트를 허용합니다.
            query = """
                UPDATE TradeHistory 
                SET Status = ?, filled_quantity = ?, price = ? 
                WHERE order_no = ? AND Status IN ('미체결', '부분체결')
            """
            cursor = conn.execute(query, (new_status, filled_qty, real_price, order_no))
            
            # 실제로 수정이 일어난 경우에만 커밋하고 UI를 강제 갱신합니다.
            if cursor.rowcount > 0:
                conn.commit()
                # 🚀 [추가] UI 표 새로고침과 C# TCP 전송을 동시에 트리거하여 화면을 즉각 바꿉니다!
                QtCore.QMetaObject.invokeMethod(self.mw, "refresh_order_table", QtCore.Qt.QueuedConnection)
                QtCore.QMetaObject.invokeMethod(self.mw, "btnDataSendClickEvent", QtCore.Qt.QueuedConnection)
            
            conn.close()
        except Exception as e:
            print(f"탐정 DB 업데이트 에러: {e}")

    def _update_status_and_ui(self, order_no, symbol, o_type, db_status, ordered_qty=0, filled_qty=0, real_price=0.0):
        """ [부분 체결 수학 계산의 마법사] 잔고와 DB를 완벽하게 동기화합니다. """
        up_conn = None
        exec_data = {} 
        
        # 🚀 [핵심 계산] 샀어야 했는데 허공으로 날아간 취소 수량 (예: 800 - 789 = 11주)
        canceled_qty = ordered_qty - filled_qty 
        if canceled_qty < 0: canceled_qty = 0
        
        try:
            up_conn = self.mw.db._get_connection(self.mw.db.shared_db_path)
            # DB에 0이 아니라 "진짜 체결된 789주"를 기록하여 팩트를 보존합니다.
            up_conn.execute("UPDATE TradeHistory SET Status = ?, filled_quantity = ?, price = ? WHERE order_no = ?", 
                           (db_status, filled_qty, real_price, order_no))
            up_conn.commit()
        except: pass
        finally:
            if up_conn: up_conn.close()

        if db_status == "주문취소":
            with self.mw.holdings_lock:
                if symbol in self.mw.my_holdings:
                    if o_type == "BUY":
                        # 🚀 [치명적 버그 수정] 선반영했던 800주에서 "못 산 11주"만 정확하게 빼줍니다!
                        current_qty = self.mw.my_holdings[symbol].get('qty', 0)
                        new_qty = current_qty - canceled_qty
                        
                        if new_qty <= 0: # 다 취소돼서 남은 게 없으면 방 뺌
                            del self.mw.my_holdings[symbol] 
                        else:
                            self.mw.my_holdings[symbol]['qty'] = new_qty # 789주로 정확히 업데이트!

            if o_type == "BUY" and hasattr(self.mw, 'accumulated_account') and symbol in self.mw.accumulated_account:
                if symbol not in self.mw.my_holdings: # 보유량이 0이 되어 삭제된 경우만 표기
                    self.mw.accumulated_account[symbol]['보유수량'] = "0 (주문취소)"
                    self.mw.accumulated_account[symbol]['평가손익금'] = "0"
            
            # 🔥 표기를 억지로 지우지 않고 DB를 다시 읽어서 표에 '주문취소 (789/800)' 느낌으로 남깁니다.
            QtCore.QMetaObject.invokeMethod(self.mw, "refresh_order_table", QtCore.Qt.QueuedConnection)
            exec_data = {"주문번호": str(order_no), "종목코드": symbol, "체결수량": filled_qty, "체결가": real_price, "is_cancel": True}
        
        elif db_status == "체결완료":
            QtCore.QMetaObject.invokeMethod(self.mw, "refresh_order_table", QtCore.Qt.QueuedConnection)
            exec_data = {"주문번호": str(order_no), "종목코드": symbol, "체결수량": int(filled_qty), "체결가": float(real_price), "is_detective": True}
            
        if hasattr(self.mw, 'ticker_window') and exec_data:
            self.mw.ticker_window.msg_processor.sig_real_execution.emit(exec_data)
            
# =====================================================================
# 🦅 [일꾼 2호] 매도 수호자 (SellGuardianWorker) - 다이어트 완료!
# 역할: 실시간 수익률 감시, 본전 방어, 트레일링 스탑 등 "매도"에만 100% 집중!
# (UI 업데이트 및 1분 브리핑은 3호 일꾼이 전담하므로 모두 삭제됨)
# =====================================================================
from datetime import datetime
import time
import pandas as pd
from PyQt5.QtCore import QThread, pyqtSignal
from COMMON.DB_Manager import JubbyDB_Manager
from COMMON.Flag import SystemConfig

class SellGuardianWorker(QThread):
    # 📺 모니터 전용 시그널(sig_account_df, sig_sync_cs) 제거 완료!
    sig_log = pyqtSignal(str, str)
    sig_order_append = pyqtSignal(dict)
    sig_panic_done = pyqtSignal()

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.is_running = False
        self.closing_mode_notified = False
        self.imminent_notified = False
        
        try:
            self.cumulative_realized_profit = float(JubbyDB_Manager().get_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", "0.0"))
        except:
            self.cumulative_realized_profit = 0.0

    def execute_guaranteed_sell(self, code, qty, current_price):
        stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
        db_temp = JubbyDB_Manager()
        try: 
            max_retries = int(db_temp.get_shared_setting("API", "SELL_MAX_RETRY", "10"))
            retry_delay = float(db_temp.get_shared_setting("API", "SELL_RETRY_DELAY", "1.0"))
        except: 
            max_retries = 10; retry_delay = 1.0

        for i in range(max_retries):
            res_odno = self.mw.api_manager.sell(code, qty)
            if res_odno:
                if i > 0: self.sig_log.emit(f"✅ [{stock_name}] {i}번 재시도 끝에 매도 접수!", "success")
                return res_odno 
                
            error_msg = getattr(self.mw.api_manager.api, 'last_error_msg', '')
            if "잔고" in error_msg:
                self.sig_log.emit(f"🚨 [{stock_name}] 매도할 잔고 없음. 보유목록에서 삭제합니다.", "error")
                return "ALREADY_SOLD" 
            
            if "초과" in error_msg or "초당" in error_msg: time.sleep(0.4) 
            else: time.sleep(retry_delay)
            
            if not self.is_running and not getattr(self.mw, 'panic_mode', False): break
        return None

    def run(self):
        self.is_running = True
        # 🚀 1. 로그를 '모니터 요원'에서 '매도 수호자'로 알맞게 변경
        self.sig_log.emit("🦅 [매도 수호자] 실시간 매도 전담 스레드 가동!", "info")
        loop_count = 0 
        
        while self.is_running:
            try:
                # 🚀 2. [치명적 버그 수정] update_ui_and_log 대신 진짜 매도 함수를 실행합니다!
                self.process_selling()
                
                # 10초마다 찐 계좌 잔고를 긁어와서 동기화
                if loop_count % 10 == 0:
                    try:
                        # self.mw 가 아니라 self.main_ui 일 수도 있으므로 둘 다 확인!
                        target_ui = getattr(self, 'mw', getattr(self, 'main_ui', None))
                        if target_ui:
                            QtCore.QMetaObject.invokeMethod(target_ui, "load_real_holdings", QtCore.Qt.QueuedConnection)
                    except: pass
                    
            except Exception as e:
                # 에러 로그도 매도 수호자로 명확하게 분리
                self.sig_log.emit(f"🚨 [매도 수호자 에러] {e}", "error") 
            
            time.sleep(1.0) 
            loop_count += 1

    def process_selling(self):
        now = datetime.now()
        now_hm = int(now.strftime("%H%M"))
        db_temp = JubbyDB_Manager() 
        mode = SystemConfig.MARKET_MODE
        
        # 1. 시간 설정 로드
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
        is_closing_phase = in_time(now_hm, t_close, t_end); is_safe_profit_close = in_time(now_hm, t_close, t_imminent - 1); is_imminent_close = in_time(now_hm, t_imminent, t_end)          

        if is_imminent_close and not getattr(self, 'imminent_notified', False):
            self.sig_log.emit(f"⚠️ [마감 임박] 모든 종목 강제 청산!", "error"); self.imminent_notified = True
        elif not is_closing_phase: self.imminent_notified = False

        if is_closing_phase and not is_imminent_close and not getattr(self, 'closing_mode_notified', False):
            self.sig_log.emit(f"⏰ [마감 모드] 신규 매수 중지 및 안전 익/손절 진행.", "warning"); self.closing_mode_notified = True
        elif not is_closing_phase: self.closing_mode_notified = False

        # 🔒 안전하게 주머니 복사
        with self.mw.holdings_lock:
            current_holdings = list(self.mw.my_holdings.items())
            my_cash = getattr(self.mw, 'last_known_cash', 0)
        
        # 보유 종목이 없으면 더 이상 무거운 연산 없이 즉시 종료 (CPU 절약)
        if len(current_holdings) == 0:
            if getattr(self.mw, 'panic_mode', False):
                self.sig_log.emit("🛑 긴급 청산 완료", "warning")
                self.mw.panic_mode = False; self.is_running = False; self.sig_panic_done.emit()
            return

        try: 
            use_trailing = db_temp.get_shared_setting("TRADE", "USE_TRAILING", "Y") == "Y"; ts_start = float(db_temp.get_shared_setting("TRADE", "TRAILING_START_YIELD", "1.5")); ts_gap = float(db_temp.get_shared_setting("TRADE", "TRAILING_STOP_GAP", "0.8")); max_hold_min = int(db_temp.get_shared_setting("TRADE", "MAX_HOLDING_TIME", "20"))
        except: 
            use_trailing, ts_start, ts_gap, max_hold_min = True, 1.5, 0.8, 20

        total_invested = 0; total_current_val = 0; sold_codes = []
        
        for code, info in current_holdings: 
            if not self.is_running: return 
            
            buy_price = info['price']; buy_qty = info['qty']; stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
            
            # 유령 주식 삭제
            if buy_qty <= 0:
                with self.mw.holdings_lock:
                    if code in self.mw.my_holdings: del self.mw.my_holdings[code]
                continue
                
            high_watermark = info.get('high_watermark', buy_price); buy_time = info.get('buy_time', now); half_sold = info.get('half_sold', False)
            
            if isinstance(buy_time, str):
                try: buy_time = datetime.strptime(buy_time, '%Y-%m-%d %H:%M:%S')
                except: buy_time = now

            cached_df = self.mw.df_cache.get(code)
            if cached_df is None or len(cached_df) < 26: continue
            df = cached_df.copy() 
            
            curr_price = db_temp.get_realtime_price(code)
            if curr_price <= 0: curr_price = float(df.iloc[-1]['close'])
            df.at[df.index[-1], 'close'] = curr_price 
            
            # 수익률 계산
            fee_rate = 0.0023 if SystemConfig.MARKET_MODE == "DOMESTIC" else 0.001
            invest_amt = buy_price * buy_qty
            eval_amt = curr_price * buy_qty
            estimated_fee = eval_amt * fee_rate
            
            profit_amt = eval_amt - invest_amt - estimated_fee
            profit_rate = (profit_amt / invest_amt) * 100 if invest_amt > 0 else 0.0

            curr_atr = float(df.iloc[-1].get('ATR', 0.0))
            volatility_pct = (curr_atr / curr_price) * 100 if curr_price > 0 else 0
            
            dynamic_ts_gap = ts_gap
            if volatility_pct >= 2.0: dynamic_ts_gap = ts_gap * 2.0 
            elif volatility_pct >= 1.0: dynamic_ts_gap = ts_gap * 1.5

            target_price, stop_price = self.mw.strategy_engine.get_dynamic_exit_prices(df, buy_price)
            target_rate = ((target_price - buy_price) / buy_price) * 100
            stop_rate = ((stop_price - buy_price) / buy_price) * 100

            if curr_price > high_watermark: high_watermark = curr_price
            
            max_profit_rate = ((high_watermark - buy_price) / buy_price) * 100 
            trail_drop_rate = ((high_watermark - curr_price) / high_watermark) * 100 if high_watermark > 0 else 0
            elapsed_mins = (now - buy_time).total_seconds() / 60.0
            total_invested += invest_amt; total_current_val += eval_amt
            
            curr_macd = float(df.iloc[-1].get('MACD', 0.0)); curr_signal = float(df.iloc[-1].get('Signal_Line', 0.0))

            is_sell_all = False; is_sell_half = False; status_msg = ""; sell_qty = buy_qty
            last_sell_attempt = info.get('last_sell_attempt', 0)
            is_cooldown = (time.time() - last_sell_attempt < 3.0) 
            
            if is_cooldown: strat_signal = "WAIT" 
            else: strat_signal = self.mw.strategy_engine.check_trade_signal(df, code, is_sell_mode=True)

            try: 
                safe_profit_rate = float(db_temp.get_shared_setting("TRADE", "SAFE_PROFIT_RATE", "0.3"))
                strat_profit_preserve = float(db_temp.get_shared_setting("TRADE", "STRAT_PROFIT_PRESERVE", "0.5"))
                deadcross_escape_rate = float(db_temp.get_shared_setting("TRADE", "DEADCROSS_ESCAPE_RATE", "1.5"))
            except: 
                safe_profit_rate = 0.3; strat_profit_preserve = 0.5; deadcross_escape_rate = 1.5

            # 🚨 매도 조건 판별
            if getattr(self.mw, 'panic_mode', False): is_sell_all = True; status_msg = "🚨 긴급 전체 청산"
            elif is_imminent_close: is_sell_all = True; status_msg = "마감 임박 시장가 청산"
            elif strat_signal == "EXIT": is_sell_all = True; status_msg = "🚨 긴급 탈출 (VWAP 붕괴)"
            elif is_safe_profit_close:
                if profit_rate >= safe_profit_rate: is_sell_all = True; status_msg = "방어 마감 익절" 
                elif profit_rate > 0.0 and curr_macd < curr_signal: is_sell_all = True; status_msg = "추세꺾임 탈출"
                elif profit_rate <= stop_rate: is_sell_all = True; status_msg = "기계적 손절"
            else:
                if max_profit_rate >= 1.5 and curr_price <= buy_price * 1.003: is_sell_all = True; status_msg = "🛡️ 본전 방어선 작동"
                elif use_trailing and profit_rate >= ts_start and trail_drop_rate >= dynamic_ts_gap: is_sell_all = True; status_msg = f"트레일링 스탑 ({dynamic_ts_gap}% 하락)"
                elif elapsed_mins >= max_hold_min: is_sell_all = True; status_msg = f"시간 제한 ({max_hold_min}분)"
                elif strat_signal == "SELL" and profit_rate > strat_profit_preserve: is_sell_all = True; status_msg = "매도 신호 (수익 보존)" 
                elif strat_signal == "SELL" and profit_rate <= stop_rate: is_sell_all = True; status_msg = "매도 신호 (손절)"
                elif profit_rate >= target_rate and not half_sold: is_sell_half = True; sell_qty = max(1, int(buy_qty // 2)); status_msg = f"목표가({target_rate:.1f}%) 1차 익절"
                elif profit_rate <= stop_rate: is_sell_all = True; status_msg = f"손절라인({stop_rate:.1f}%) 이탈"
                elif profit_rate >= deadcross_escape_rate and curr_macd < curr_signal: is_sell_all = True; status_msg = "데드크로스 탈출" 

            # 🚨 UI 기록용 코드(unified_account_rows) 완벽 삭제! -> 모니터 일꾼이 알아서 합니다.

            # 🚀 실제 매도 주문
            if (is_sell_half or is_sell_all) and not is_cooldown:
                with self.mw.holdings_lock:
                    self.mw.my_holdings[code]['last_sell_attempt'] = time.time()
                    
                res_odno = self.execute_guaranteed_sell(code, sell_qty, curr_price)
                
                if res_odno: 
                    if res_odno == "ALREADY_SOLD": res_odno = "00000000" 
                    
                    realized_profit = (curr_price - buy_price) * sell_qty
                    sold_codes.append((code, is_sell_all, sell_qty, realized_profit, curr_price))
                    
                    if is_sell_all and hasattr(self.mw, 'buy_worker'):
                        if code in self.mw.buy_worker.log_step_memory:
                            del self.mw.buy_worker.log_step_memory[code]

                    log_icon, log_color = ("🟢", "success") if profit_rate > 0 else ("🔴", "sell")
                    sell_type_str = "1차 익절(절반)" if is_sell_half else "전량 청산"
                    
                    sell_msg = f"{log_icon} [{sell_type_str}] {stock_name} | 사유: {status_msg} | 체결가: {curr_price:,.0f}원 | 매도: {sell_qty}주 | 손익: {int(realized_profit):+,}원 ({profit_rate:+.2f}%) | 주문번호: {res_odno}"
                    self.sig_log.emit(sell_msg, log_color) 
                    
                    self.mw.send_kakao_msg(f"🔔 [주삐 매도]\n종목: {stock_name}\n사유: {status_msg}\n수익률: {profit_rate:+.2f}%\n손익금: {int(realized_profit):+,}원") 
                    
                    self.sig_order_append.emit({
                        '주문번호': res_odno, '종목코드': code, '종목명': stock_name, 
                        '주문종류': '익절' if profit_rate > 0 else '손절', '주문가격': f"{curr_price:,.0f}", 
                        '주문수량': sell_qty, '체결수량': 0, '주문시간': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                        '상태': '미체결', '수익률': f"{profit_rate:.2f}%"
                    })
                else:
                    self.sig_log.emit(f"🚨 [{stock_name}] {status_msg} 매도 주문 실패 (서버 무응답).", "error")

        # 🔒 매도 완료 종목 후처리 및 셧다운 방어막 (매우 중요한 핵심 기능이므로 유지)
        if sold_codes:
            with self.mw.holdings_lock:
                for code, is_all, sqty, r_profit, c_price in sold_codes:
                    if code in self.mw.my_holdings:
                        if is_all: del self.mw.my_holdings[code]
                        else: self.mw.my_holdings[code]['qty'] -= sqty; self.mw.my_holdings[code]['half_sold'] = True
                    
                    self.mw.cumulative_realized_profit += r_profit
                    self.mw.last_known_cash += (c_price * sqty)
                    if not hasattr(self.mw, 'cooldown_dict'): self.mw.cooldown_dict = {}
                    self.mw.cooldown_dict[code] = now 
                    
                    loss_cnt = getattr(self.mw, 'loss_streak_cnt', 0)
                    if r_profit < 0 and is_all: self.mw.loss_streak_cnt = loss_cnt + 1
                    elif r_profit > 0: self.mw.loss_streak_cnt = 0
            
            try: db_temp.set_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", str(self.mw.cumulative_realized_profit))
            except: pass
            my_cash = self.mw.last_known_cash
            
        # 셧다운 발동 검사
        current_total_asset = my_cash + total_invested
        asset_pnl_pct = (self.mw.cumulative_realized_profit / current_total_asset) * 100 if current_total_asset > 0 else 0.0
        self.mw.daily_total_pnl_pct = asset_pnl_pct
        
        try: 
            max_loss_cnt = int(db_temp.get_shared_setting("RISK", "MAX_CONSECUTIVE_LOSS", "5"))
            limit_pnl = float(db_temp.get_shared_setting("RISK", "DAILY_STOP_LOSS_PCT", "-10.0"))
        except: 
            max_loss_cnt = 5; limit_pnl = -10.0

        if getattr(self.mw, 'loss_streak_cnt', 0) >= max_loss_cnt or asset_pnl_pct <= limit_pnl:
            db_temp.set_shared_setting("RISK", "IS_LOCKED", "Y")
            self.sig_log.emit(f"🚨 [긴급 셧다운] 연속 손실 또는 일일 손실 한도 도달! 매수를 잠급니다.", "error")

        # 🚨 [여기 있던 과거내역 읽어오기, 1분 브리핑 계산, UI 표 전송 코드는 100% 삭제 완료되었습니다!]

# =========================================================================
# 📺 [Track 3] 모니터링 전담 일꾼 (SystemMonitorWorker)
# 기존 매도 일꾼이 하던 '표 그리기, 자산 계산, 1분 브리핑' 기능을 100% 그대로 가져왔습니다.
# =========================================================================
class SystemMonitorWorker(QThread):
    sig_log = pyqtSignal(str, str)         # UI에 로그를 띄우기 위한 신호
    sig_account_df = pyqtSignal(object)    # 잔고 표(DataFrame)를 갱신하기 위한 신호
    sig_sync_cs = pyqtSignal()             # C# UI로 데이터를 쏘기 위한 신호

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.is_running = False
        self.last_brief_min = -1  # 1분 브리핑 중복 출력을 막기 위한 변수

    def run(self):
        self.is_running = True
        self.sig_log.emit("📺 [모니터 요원] 잔고 감시 및 1분 브리핑 전담 스레드 가동!", "info")
        db_temp = JubbyDB_Manager()
        
        while self.is_running:
            try:
                self.update_ui_and_log(db_temp)
            except Exception as e:
                # 🚀 [방어막 해제] 에러가 났을 때 무시하지 않고 로그에 띄워서 문제를 즉각 파악하게 합니다!
                self.sig_log.emit(f"🚨 [모니터 요원 에러] {e}", "error") 
            time.sleep(1.0) # 1초마다 한 번씩만 여유롭게 UI를 갱신합니다. (CPU 과부하 방지)

    def update_ui_and_log(self, db_temp):
        now = datetime.now()
        unified_account_rows = []
        
        # 1. 메인 주머니(my_holdings) 안전하게 읽어오기
        with self.mw.holdings_lock:
            current_holdings = list(self.mw.my_holdings.items())
            my_cash = getattr(self.mw, 'last_known_cash', 0)
            realized_profit = getattr(self.mw, 'cumulative_realized_profit', 0)

        total_invested = 0
        total_current_val = 0
        is_first_row = True
        stock_details_str = ""

        # 2. 보유 종목 리스트 생성 및 수익금 계산
        for code, info in current_holdings:
            buy_price = info['price']
            buy_qty = info['qty']
            stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
            
            # 🚀 [버그 완벽 수정] 웹소켓이 끊기거나 응답이 없으면, 매수 엔진이 1분마다 갱신하는 최신 캐시(df_cache)에서 가격을 빼옵니다!
            curr_price = db_temp.get_realtime_price(code)
            if curr_price <= 0: 
                cached_df = self.mw.df_cache.get(code)
                if cached_df is not None and not cached_df.empty:
                    curr_price = float(cached_df.iloc[-1]['close'])
                else:
                    curr_price = buy_price # 최후의 수단
            
            # 🚀 [HTS 완벽 동기화] 매도 감시 일꾼과 동일하게 세금/수수료를 계산하여 찐 수익률을 표기합니다.
            fee_rate = 0.0023 if SystemConfig.MARKET_MODE == "DOMESTIC" else 0.001
            invest_amt = buy_price * buy_qty
            eval_amt = curr_price * buy_qty
            estimated_fee = eval_amt * fee_rate 
            
            real_profit_amt = eval_amt - invest_amt - estimated_fee
            real_profit_rate = (real_profit_amt / invest_amt) * 100 if invest_amt > 0 else 0.0

            # 1분 브리핑에 들어갈 종목별 상세 텍스트
            stock_details_str += f"    🔸 {stock_name}: 매입 {buy_price:,.0f} -> 현재 {curr_price:,.0f} ({real_profit_rate:+.2f}%)\n"

            # 화면 표에 들어갈 데이터 조립
            unified_account_rows.append({
                '시간': now.strftime('%H:%M:%S'), '종목코드': code, '종목명': stock_name, 
                '보유수량': str(buy_qty), '평균매입가': f"{buy_price:,.0f}", '현재가': f"{curr_price:,.0f}", 
                '평가손익금': f"{real_profit_amt:,.0f}", '수익률': f"{real_profit_rate:.2f}%", 
                '상태': '보유중', '주문가능금액': f"{my_cash:,.0f}" if is_first_row else ""
            })
            is_first_row = False

        # 3. 과거 매도 내역(TradeHistory) 합치기
        try:
            conn = db_temp._get_connection(db_temp.shared_db_path)
            past_data = conn.execute("SELECT strftime('%H:%M:%S', time), symbol, symbol_name, quantity, price, Status, order_yield, type FROM TradeHistory WHERE (Status = '주문취소' OR (Status = '체결완료' AND type = 'SELL')) AND time >= date('now', 'localtime')").fetchall()
            conn.close()
            
            current_holding_codes = [c for c, _ in current_holdings]
            for r in past_data:
                if r[1] in current_holding_codes: continue
                raw_yield = str(r[6]).replace('%', '').strip() if r[6] else '0.0'
                fixed_yield = float(raw_yield) if raw_yield else 0.0
                display_status = '매도완료' if r[5] == '체결완료' else r[5]
                
                unified_account_rows.append({
                    '시간': r[0], '종목코드': r[1], '종목명': r[2], '보유수량': "0", 
                    '평균매입가': f"{float(r[4]):,.0f}", '현재가': "-", 
                    '평가손익금': f"{(float(r[4])*int(r[3]))*(fixed_yield/100):,.0f}" if display_status=='매도완료' else "0", 
                    '수익률': f"{fixed_yield:.2f}%", '상태': display_status, '주문가능금액': ""
                })
        except: pass

        # 4. 총 자산 상태 DB(SharedSettings) 업데이트
        total_invested = sum([float(r['평균매입가'].replace(',', '')) * int(r['보유수량'].replace(',', '')) for r in unified_account_rows if r['보유수량'] != "0"])
        total_current_val = sum([float(r['현재가'].replace(',', '')) * int(r['보유수량'].replace(',', '')) for r in unified_account_rows if r['보유수량'] != "0"])
        
        total_unrealized_profit = total_current_val - total_invested
        total_asset = my_cash + total_current_val
        try:
            db_temp.set_shared_setting("ACCOUNT", "TOTAL_ASSET", str(int(total_asset)))
            db_temp.set_shared_setting("ACCOUNT", "UNREALIZED_PROFIT", str(int(total_unrealized_profit)))
            db_temp.set_shared_setting("ACCOUNT", "CASH", str(int(my_cash)))
        except: pass

        # 5. ⏰ 1분 브리핑 텍스트 출력
        if now.minute != self.last_brief_min:
            try: 
                d2_cash = self.mw.api_manager.get_d2_deposit()
                d2_cash = int(float(str(d2_cash).replace(',', ''))) # 🚀 쉼표(,) 섞인 문자열이 와도 에러 안나게 수정
            except: 
                d2_cash = 0
            
            msg = f"📊 [주삐 1분 브리핑] {now.strftime('%H:%M')}\n    💎 자산: {int(total_asset):,}원 (D+2 예수금: {d2_cash:,}원)\n    📈 누적손익: {int(realized_profit):+,}원 | 보유손익: {int(total_unrealized_profit):+,}원"
            if stock_details_str: msg += f"\n\n{stock_details_str.rstrip()}"
            else: msg += "\n\n    💼 [보유 종목 없음]"
                
            self.sig_log.emit(msg, "info")
            self.last_brief_min = now.minute

        # 6. 완성된 데이터를 UI 표로 전송
        acc_cols = ['시간', '종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','상태','주문가능금액']
        if unified_account_rows:
            df_acc = pd.DataFrame(unified_account_rows)
            df_acc.fillna("", inplace=True) 
            for c in acc_cols:
                if c not in df_acc.columns: df_acc[c] = ""
            self.sig_account_df.emit(df_acc[acc_cols].copy())
            self.sig_sync_cs.emit()
        else:
            # 🚀 [치명적 버그 수정] 보유 종목도 없고, 과거 내역도 없을 때 빈 껍데기 표를 보내서 화면을 깨끗하게 지워줍니다!
            df_acc = pd.DataFrame(columns=acc_cols)
            self.sig_account_df.emit(df_acc)
            self.sig_sync_cs.emit()

# =====================================================================
# 🚀 [일꾼 2호] 매수 사냥꾼 (BuyHunterWorker) - 전체 코드
# 역할: 시장 스캔, AI 확률 계산, 불타기, ATR 비중 조절, 단계별 도배 방지 로그, 매수 실행
# =====================================================================
class BuyHunterWorker(QThread):
    sig_log = pyqtSignal(str, str); sig_market_df = pyqtSignal(object)
    sig_strategy_df = pyqtSignal(object); sig_sync_cs = pyqtSignal(); sig_order_append = pyqtSignal(dict)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.mw = main_window
        self.is_running = False
        self.was_crash_mode = False
        self.last_loss_log = -1
        self.last_idle_log = ""
        self.last_lock_log = ""
        
        # 🛑 [핵심] 종목별 로그 단계를 기억하는 장부 (도배 방지용)
        # 0: 대기, 1: AI 1차 승인, 2: 패턴 2차 승인, 3: 최종 진입 완료
        self.log_step_memory = {} 

    def run(self):
        self.is_running = True
        db_temp = JubbyDB_Manager()
        try: db_temp.update_system_status('TRADER', '매수 사냥꾼 가동 🚀', 100)
        except: pass
        
        while self.is_running:
            try:
                self.process_buying(db_temp)
            except Exception as e:
                self.sig_log.emit(f"🚨 매수 엔진 내부 오류: {e}", "error")
            
            try: cycle_wait_count = int(db_temp.get_shared_setting("TRADE", "CYCLE_WAIT_COUNT", "100"))
            except: cycle_wait_count = 100
            for _ in range(cycle_wait_count):
                if not self.is_running: break
                time.sleep(0.1)

    def execute_guaranteed_buy(self, code, qty, current_price):
        stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
        db_temp = JubbyDB_Manager()
        try: 
            max_retries = int(db_temp.get_shared_setting("API", "SELL_MAX_RETRY", "10"))
            retry_delay = float(db_temp.get_shared_setting("API", "SELL_RETRY_DELAY", "1.0"))
        except: 
            max_retries = 10; retry_delay = 1.0

        odno = self.mw.api_manager.buy_market_price(code, qty)
        if odno: return odno 
            
        self.sig_log.emit(f"⚠️ [{stock_name}] 1차 매수 실패! 서버 상태 확인 후 재시도 중...", "warning")
        time.sleep(retry_delay) 
        
        for i in range(1, max_retries):
            if not self.is_running or getattr(self.mw, 'panic_mode', False): return None
            
            # 🚨 [치명적 버그 수정] 여기서 AI를 다시 계산하면서 똑같은 로그가 무한 도배되었습니다!
            # 어차피 사기로 결정된 종목이므로, 무거운 AI 재검사 없이 예수금만 재확인하고 API 전송만 시도합니다.
            error_msg = getattr(self.mw.api_manager.api, 'last_error_msg', '')

            # 🚀 [추가] 잔고 부족이거나 아예 살 수 없는 종목(매매불가/증거금100%)이라면 즉시 포기!
            if "잔고" in error_msg or "예수금" in error_msg or "매매불가" in error_msg or "증거금" in error_msg:
                self.sig_log.emit(f"🚨 [{stock_name}] {error_msg} 사유로 매수를 즉시 포기합니다.", "error")
                return None

            # 초당 거래건수 제한에 걸렸다면 트래픽 진정을 위해 더 길게(1.0초) 쉰 다음 쏩니다.
            if "초과" in error_msg or "초당" in error_msg:
                time.sleep(1.0)
            else:
                time.sleep(retry_delay)

            my_cash = getattr(self.mw, 'last_known_cash', 0)
            budget = current_price * qty 
            new_qty = int(budget // current_price) 
            if new_qty * current_price > my_cash: new_qty = int(my_cash // current_price)
            if new_qty <= 0: return None

            res_odno = self.mw.api_manager.buy_market_price(code, new_qty)
            if res_odno: 
                self.sig_log.emit(f"✅ [{stock_name}] {i}번 재시도 끝에 매수 성공!", "success")
                return res_odno
                
        return None

    def get_realtime_hot_stocks(self): 
        import requests, random, json
        pool = list(self.mw.DYNAMIC_STOCK_DICT.keys()); hot_list = []; db_temp = JubbyDB_Manager()
        try: 
            global_api_delay = float(db_temp.get_shared_setting("API", "GLOBAL_API_DELAY", "0.06"))
            target_limit = int(db_temp.get_shared_setting("TRADE", "HOT_STOCK_LIMIT", "300"))
            max_per_condition = int(db_temp.get_shared_setting("TRADE", "MAX_PER_CONDITION", "30"))
        except: global_api_delay = 0.06; target_limit = 300; max_per_condition = 30

        if SystemConfig.MARKET_MODE == "DOMESTIC":
            try:
                default_conditions_json = '[["J","1000","10000"],["Q","1000","10000"],["J","10000","50000"],["Q","10000","50000"]]'
                try: search_conditions = json.loads(db_temp.get_shared_setting("TRADE", "SEARCH_CONDITIONS", default_conditions_json))
                except: search_conditions = json.loads(default_conditions_json)
                api = self.mw.api_manager.api; url = f"{api.base_url}/uapi/domestic-stock/v1/quotations/volume-rank"
                headers = {"content-type": "application/json", "authorization": f"Bearer {api.access_token}", "appkey": api.app_key, "appsecret": api.app_secret, "tr_id": "FHPST01710000", "custtype": "P"}
                for mrkt, price1, price2 in search_conditions:
                    if len(hot_list) >= target_limit: break 
                    params = {"FID_COND_MRKT_DIV_CODE": mrkt, "FID_COND_SCR_DIV_CODE": "20171", "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0", "FID_BLNG_CLS_CODE": "0", "FID_TRGT_CLS_CODE": "111111111", "FID_TRGT_EXLS_CLS_CODE": "0000000000", "FID_INPUT_PRICE_1": price1, "FID_INPUT_PRICE_2": price2, "FID_VOL_CNT": "0", "FID_INPUT_DATE_1": ""}
                    time.sleep(global_api_delay); res = requests.get(url, headers=headers, params=params, timeout=3)
                    if res.status_code == 200 and res.json().get('rt_cd') == '0':
                        data = res.json().get('output', [])
                        condition_count = 0
                        for item in data:
                            if str(item.get('acml_vol', '0')) == '0': continue 
                            code = item.get('mksc_shrn_iscd') or item.get('stck_shrn_iscd')
                            if code and code in pool and code not in hot_list:
                                hot_list.append(code)
                                condition_count += 1
                                if condition_count >= max_per_condition or len(hot_list) >= target_limit: break
            except: pass
        if len(hot_list) < 20: 
            remaining_pool = [c for c in pool if c not in hot_list]
            if remaining_pool: hot_list.extend(random.sample(remaining_pool, min(30, len(remaining_pool))))
        return hot_list

    def process_buying(self, db_temp):
        now = datetime.now(); now_hm = int(now.strftime("%H%M"))
        mode = SystemConfig.MARKET_MODE
        current_minute = now.strftime("%H:%M")

        # 🚀 [복구 완료 1] DB에서 자동매매 시작/종료 시간을 정확히 가져옵니다.
        try:
            if mode == "DOMESTIC":
                t_start = int(db_temp.get_shared_setting("TRADE", "TIME_START_DOM", "0900")); t_close = int(db_temp.get_shared_setting("TRADE", "TIME_CLOSE_DOM", "1520"))
            elif mode == "OVERSEAS":
                t_start = int(db_temp.get_shared_setting("TRADE", "TIME_START_OVS", "2230")); t_close = int(db_temp.get_shared_setting("TRADE", "TIME_CLOSE_OVS", "0430"))
            else:
                t_start = int(db_temp.get_shared_setting("TRADE", "TIME_START_FUT", "0700")); t_close = int(db_temp.get_shared_setting("TRADE", "TIME_CLOSE_FUT", "0530"))
        except: t_start = 900; t_close = 1520
        
        def in_time(val, s, e): return (s <= val <= e) if s <= e else (val >= s or val <= e)
        is_golden_time = in_time(now_hm, t_start, t_close - 1)

        # 2. 각종 설정값 로드
        try: 
            global_api_delay = float(db_temp.get_shared_setting("API", "GLOBAL_API_DELAY", "0.06"))
            max_buys_per_cycle = int(db_temp.get_shared_setting("TRADE", "MAX_BUYS_PER_CYCLE", "6"))
            loss_limit_cnt = int(db_temp.get_shared_setting("TRADE", "LOSS_STREAK_LIMIT", "5"))
            min_scan_stocks = int(db_temp.get_shared_setting("TRADE", "MIN_SCAN_STOCKS", "60"))
            cooldown_min = int(db_temp.get_shared_setting("TRADE", "COOLDOWN_MINUTES", "10"))
            max_stocks_setting = int(db_temp.get_shared_setting("TRADE", "MAX_STOCKS", "15"))
        except: 
            global_api_delay = 0.06; max_buys_per_cycle = 6; loss_limit_cnt = 5; min_scan_stocks = 60; cooldown_min = 10; max_stocks_setting = 15

        # 🚀 [원본 복구] ETF 폭락 감지 알고리즘
        market_ticker = "069500" if mode == "DOMESTIC" else ("QQQ" if mode == "OVERSEAS" else "NQM26")
        
        if self.mw.last_fetch_time.get(market_ticker) != current_minute:
            time.sleep(global_api_delay)
            market_etf = self.mw.api_manager.fetch_minute_data(market_ticker)
            if market_etf is not None and len(market_etf) > 1:
                self.mw.df_cache[market_ticker] = market_etf
                self.mw.last_fetch_time[market_ticker] = current_minute
        else: market_etf = self.mw.df_cache.get(market_ticker)

        if market_etf is not None and len(market_etf) > 1:
            etf_now = market_etf.iloc[-1]['close']; etf_prev = market_etf.iloc[-2]['close']
            self.mw.strategy_engine.market_return_1m = ((etf_now - etf_prev) / etf_prev) * 100.0
            etf_drop = ((etf_now - market_etf.iloc[0]['open']) / market_etf.iloc[0]['open']) * 100
            try: crash_limit = float(db_temp.get_shared_setting("TRADE", "CRASH_LIMIT", "-1.5"))
            except: crash_limit = -1.5
            
            if etf_drop <= crash_limit: 
                self.mw.market_crash_mode = True
                if not self.was_crash_mode: 
                    self.sig_log.emit(f"⚠️ [시장 경고] {market_ticker} 급락({etf_drop:.2f}%). 신규 매수 차단.", "warning")
                    self.was_crash_mode = True 
            else:
                if self.was_crash_mode: 
                    self.sig_log.emit(f"🌤️ [시장 안정] {market_ticker} 회복({etf_drop:.2f}%). 탐색 재개!", "success")
                    self.was_crash_mode = False 
                self.mw.market_crash_mode = False

        if getattr(self.mw, 'panic_mode', False) or getattr(self.mw, 'market_crash_mode', False): return
        is_locked = db_temp.get_shared_setting("RISK", "IS_LOCKED", "N")

        # 🚀 [복구 완료 2] 매매 시간이 아닐 때 먼저 필터링! (5연패 로그 도배 차단)
        if not is_golden_time:
            if self.last_idle_log != current_minute and now.minute % 1 == 0:
                self.sig_log.emit(f"💤 [대기중] 매수 시간이 아닙니다. 매도 감시만 진행 중... ({current_minute})", "info")
                self.last_idle_log = current_minute 
            return

        # 🚀 매매 시간(Golden Time)일 때만 5연패 방어막을 확인합니다.
        if getattr(self.mw, 'loss_streak_cnt', 0) >= loss_limit_cnt:
            if now.minute % 5 == 0 and self.last_loss_log != now.minute:
                self.sig_log.emit(f"🛑 {loss_limit_cnt}연패 방어막 작동! 매수 탐색 일시 중단.", "error")
                self.last_loss_log = now.minute 
            return

        if is_locked == "Y":
            if self.last_lock_log != current_minute and now.minute % 1 == 0:
                self.sig_log.emit("🛑 [셧다운 발동 중] 신규 매수가 잠겨있습니다. (보유 종목 매도는 정상 진행 중)", "error")
                self.last_lock_log = current_minute
            return

        # 3. 자산 잠금 및 데이터 로드
        with self.mw.holdings_lock:
            current_count = len(self.mw.my_holdings)
            my_cash = getattr(self.mw, 'last_known_cash', 0)
            total_invested = sum([info['price'] * info['qty'] for info in self.mw.my_holdings.values()])
            total_asset = my_cash + total_invested
            
        needed_count = max_stocks_setting - current_count 
        # 🚨 [치명적 버그 수정 2: 시장 표(Market) 빈칸 멈춤 해결]
        # 여기서 return 해버리면 스캔 자체가 중단되어 UI의 1번째 시장 표가 업데이트되지 않습니다!
        # return 코드를 과감히 삭제하고, 아래쪽 실제 '매수 로직'에서만 방어막을 칩니다.

        # 4. 종목 스캔 시작
        base_targets = self.get_realtime_hot_stocks()
        scan_targets = list(set(list(self.mw.my_holdings.keys()) + base_targets))
        
        market_rows = []; strategy_rows = []; scanned_log_list = []; current_cycle_buys = 0

        for code in scan_targets:
            if not self.is_running: return 
            
            # 쿨타임 검사 (보유 중이면 패스)
            if code in getattr(self.mw, 'cooldown_dict', {}) and code not in self.mw.my_holdings:
                if (datetime.now() - self.mw.cooldown_dict[code]).total_seconds() / 60.0 < cooldown_min: continue
                else: del self.mw.cooldown_dict[code]

            try: scan_delay = float(db_temp.get_shared_setting("TRADE", "SCAN_DELAY", "0.3"))
            except: scan_delay = 0.3
            time.sleep(scan_delay)

            try: prob, curr_price, df_feat = self.mw.get_ai_probability(code)
            except: continue
            if prob == -1.0 or curr_price <= 0 or np.isnan(curr_price): continue 

            # 🚀 [원본 복구] 불타기(Pyramiding) 허용 알고리즘
            is_pyramiding = False; current_invested_in_stock = 0.0; max_allowed_for_stock = 0.0
            holding_qty = 0; holding_price = 0.0
            
            with self.mw.holdings_lock:
                if code in self.mw.my_holdings:
                    holding_info = self.mw.my_holdings[code]; holding_price = holding_info['price']; holding_qty = holding_info['qty']
                    current_yield = (curr_price - holding_price) / holding_price * 100.0; current_invested_in_stock = holding_price * holding_qty
                    
                    try: 
                        pyramiding_yield = float(db_temp.get_shared_setting("TRADE", "PYRAMIDING_YIELD", "1.0"))
                        max_invest_per_stock_pct = float(db_temp.get_shared_setting("TRADE", "MAX_INVEST_PER_STOCK", "15.0"))
                    except: 
                        pyramiding_yield = 1.0; max_invest_per_stock_pct = 15.0
                        
                    max_allowed_for_stock = total_asset * (max_invest_per_stock_pct / 100.0)
                    if current_yield >= pyramiding_yield and current_invested_in_stock < max_allowed_for_stock:
                        is_pyramiding = True
                        try: ai_limit = float(db_temp.get_shared_setting("AI", "THRESHOLD", "80.0")) / 100.0
                        except: ai_limit = 0.80
                        if prob < ai_limit: continue
                    else:
                        continue # 불타기 조건이 안 맞으면 더 이상 매수 탐색 진행 안함

            stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code) 
            if code not in self.mw.my_holdings: scanned_log_list.append({'name': stock_name, 'prob': prob})
            
            try: ai_limit = float(db_temp.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
            except: ai_limit = 0.70
            
            # 🚀 [원본 복구] 점심장 기준 AI 확률 보수적 조정
            now_time = now.time(); lunch_start = datetime.strptime("11:30", "%H:%M").time(); lunch_end = datetime.strptime("13:30", "%H:%M").time()
            if lunch_start <= now_time <= lunch_end: ai_limit += 0.05 

            strat_signal = "WAIT" 
            if df_feat is not None and not df_feat.empty:
                strat_signal = self.mw.strategy_engine.check_trade_signal(df_feat, code)
                
                # 🚀 [방어막] API 데이터 통신 불량으로 컬럼이 누락되어 있어도, 프로그램이 뻗지 않고 현재가로 대체하도록 .get() 함수를 사용합니다!
                curr_open = float(df_feat.iloc[-1].get('open', curr_price))
                curr_high = float(df_feat.iloc[-1].get('high', curr_price))
                curr_low  = float(df_feat.iloc[-1].get('low', curr_price))
                curr_vol  = float(df_feat.iloc[-1].get('volume', 0.0))
                
                ret_1m = float(df_feat.iloc[-1].get('return', 0.0)); trade_amt = float(df_feat.iloc[-1].get('Trade_Amount', (curr_price * curr_vol) / 1000000)); curr_vol_energy = float(df_feat.iloc[-1].get('Vol_Energy', 1.0)); curr_disp = float(df_feat.iloc[-1].get('Disparity_20', 100.0)); curr_macd = float(df_feat.iloc[-1].get('MACD', 0.0)); curr_rsi = float(df_feat.iloc[-1].get('RSI', 50.0)); ma5_val = float(df_feat.iloc[-1].get('MA5', curr_price)); ma20_val = float(df_feat.iloc[-1].get('MA20', curr_price)); curr_atr = float(df_feat.iloc[-1].get('ATR', 0.0))
            else: 
                curr_open = curr_high = curr_low = ma5_val = ma20_val = curr_price; curr_vol = ret_1m = trade_amt = curr_atr = curr_macd = 0.0; curr_disp = 100.0; curr_vol_energy = 1.0; curr_rsi = 50.0
                
            # 📊 [UI 표 정수화 포맷 적용] 소수점 제거 (:.0f)
            now_time_str = datetime.now().strftime('%H:%M:%S')
            market_rows.append({'시간': now_time_str, '종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.0f}", '시가': f"{curr_open:,.0f}", '고가': f"{curr_high:,.0f}", '저가': f"{curr_low:,.0f}", '1분등락률': f"{ret_1m:.2f}", '거래대금': f"{trade_amt:,.1f}", '거래량에너지': f"{curr_vol_energy:.2f}", '이격도': f"{curr_disp:.2f}", '거래량': f"{curr_vol:,.0f}"})
            
            display_signal = "BUY 🟢" if strat_signal == "BUY" else ("SELL 🔴" if strat_signal == "SELL" else "WAIT 🟡")
            if df_feat is not None: 
                strategy_rows.append({'시간': now_time_str, '종목코드': code, '종목명': stock_name, '상승확률': f"{prob*100:.1f}%", 'MA_5': f"{ma5_val:.0f}", 'MA_20': f"{ma20_val:.0f}", 'RSI': f"{curr_rsi:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': display_signal})

            # =====================================================================
            # 🛑 [핵심 로직] 단계별 승인 로그 출력 및 ATR 비중 조절
            # =====================================================================
            log_step = self.log_step_memory.get(code, 0)

            # ✅ 1단계: AI 확률 커트라인 통과
            if prob >= ai_limit:
                if log_step < 1:
                    # self.sig_log.emit(f"🤖 [AI 1차 승인] {stock_name} 포착! (확률: {prob*100:.1f}%)", "info")
                    self.log_step_memory[code] = 1 # 1단계 성공
                
                # ✅ 2단계: 전략 엔진 패턴 분석 통과
                if strat_signal == "BUY":
                    if self.log_step_memory.get(code, 0) < 2:
                        # self.sig_log.emit(f"✅ [2차 승인] {stock_name} 시계열 패턴 우수", "success")
                        self.log_step_memory[code] = 2 # 2단계 성공
                    
                    # 🚀 [원본 복구] ATR 변동성 비중 조절
                    try: use_funds_percent = float(db_temp.get_shared_setting("TRADE", "USE_FUNDS_PERCENT", "100"))
                    except: use_funds_percent = 100.0
                    
                    allowed_total_budget = total_asset * (use_funds_percent / 100.0)
                    available_trading_budget = allowed_total_budget - total_invested
                    
                    if available_trading_budget > 0:
                        if is_pyramiding:
                            try: pyramiding_rate = float(db_temp.get_shared_setting("TRADE", "PYRAMIDING_RATE", "50.0"))
                            except: pyramiding_rate = 50.0
                            target_budget = min(current_invested_in_stock * (pyramiding_rate / 100.0), max_allowed_for_stock - current_invested_in_stock)
                        else:
                            try: 
                                weight_high = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_HIGH", "20.0")) / 100.0
                                weight_mid = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_MID", "10.0")) / 100.0
                                weight_low = float(db_temp.get_shared_setting("TRADE", "BUDGET_WEIGHT_LOW", "5.0")) / 100.0
                            except: 
                                weight_high, weight_mid, weight_low = 0.20, 0.10, 0.05
                            
                            weight = weight_high if prob >= 0.85 else (weight_mid if prob >= 0.70 else weight_low)
                            base_target_budget = float(total_asset * weight)
                            
                            # ATR 제한
                            try: 
                                atr_high_limit = float(db_temp.get_shared_setting("TRADE", "ATR_HIGH_LIMIT", "5.0"))
                                atr_high_ratio = float(db_temp.get_shared_setting("TRADE", "ATR_HIGH_RATIO", "50.0")) / 100.0
                                atr_mid_limit  = float(db_temp.get_shared_setting("TRADE", "ATR_MID_LIMIT", "2.5"))
                                atr_mid_ratio  = float(db_temp.get_shared_setting("TRADE", "ATR_MID_RATIO", "70.0")) / 100.0
                            except: 
                                atr_high_limit, atr_high_ratio = 5.0, 0.5; atr_mid_limit, atr_mid_ratio = 2.5, 0.7
                                
                            volatility_pct = (curr_atr / curr_price) * 100 if curr_price > 0 else 0
                            if volatility_pct >= atr_high_limit: target_budget = base_target_budget * atr_high_ratio
                            elif volatility_pct >= atr_mid_limit: target_budget = base_target_budget * atr_mid_ratio
                            else: target_budget = base_target_budget

                        # 1. 기존 로직: DB에 설정된 비중(USE_FUNDS_PERCENT 등)에 따라 계산된 1차 예산
                        budget = min(target_budget, available_trading_budget)
                        
                        # 🚀 2. DB에서 시장가 안전마진(버퍼) 비율을 가져옵니다. (기본 98%)
                        try:
                            buffer_pct = float(db_temp.get_shared_setting("TRADE", "MARKET_ORDER_BUFFER", "98.0")) / 100.0
                        except:
                            buffer_pct = 0.98
                        
                        # 🚀 3. 시장가 호가 튐 현상 대비 안전하게 버퍼를 적용한 최종 예산
                        safe_budget = budget * buffer_pct
                        
                        buy_qty = int(safe_budget // curr_price) 
                        
                        # 최종 예수금 한도 체크 시에도 버퍼를 적용하여 안전 장치 가동
                        if buy_qty * curr_price > (my_cash * buffer_pct): 
                            buy_qty = int((my_cash * buffer_pct) // curr_price)
                        
                        # ✅ 3단계: 최종 진입 금액 산정 완료 시 매수 
                        if buy_qty > 0:
                            # 🚀 [방어막 추가] 스캔은 정상적으로 하되, 최대 보유 개수가 꽉 찼고 불타기가 아니라면 매수만 스킵합니다!
                            if needed_count <= 0 and not is_pyramiding:
                                if self.log_step_memory.get(code, 0) < 3:
                                    self.sig_log.emit(f"🔒 [{stock_name}] 3차 승인 통과! BUT 보유 종목이 꽉 차서 신규 매수 스킵.", "warning")
                                    self.log_step_memory[code] = 3
                                continue # 아래 매수 주문(execute_guaranteed_buy)으로 넘어가지 않고 다음 종목으로 패스

                            if self.log_step_memory.get(code, 0) < 3:
                                if is_pyramiding:
                                    self.sig_log.emit(f"🔥 [불타기 승인] {stock_name} 추가 진입 결정!", "send")
                                else:
                                    self.sig_log.emit(f"🚀 [최종 승인] {stock_name} 모든 조건 충족! 강력 매수 진입!", "send")
                                self.log_step_memory[code] = 3 # 3단계 성공

                            # 매수 주문 발송
                            res_odno = self.execute_guaranteed_buy(code, buy_qty, curr_price)
                            
                            if res_odno: 
                                now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                
                                # 🚀 [핵심 수정] 무조건 다 샀다고 뻥치지 않고, 잔고(my_holdings)에 더하지 않습니다!
                                # 오직 주문 표(UI)와 DB에만 '미체결(0주)'로 띄우고 진짜 체결은 탐정이 확인합니다.
                                self.sig_order_append.emit({
                                    '주문번호': res_odno, '종목코드': code, '종목명': stock_name, 
                                    '주문종류': '매수' if not is_pyramiding else '불타기', 
                                    '주문가격': f"{curr_price:,.0f}", '주문수량': buy_qty, 
                                    '체결수량': 0, '주문시간': now_str, '상태': '미체결', '수익률': '0.00%'
                                })
                                
                                self.sig_log.emit(f"🛒 [{stock_name}] 주문 접수 완료 (번호: {res_odno}). 거래소 체결 대기 중...", "info")
                                
                                needed_count -= 1; current_cycle_buys += 1 
                                time.sleep(0.5) 
                                
                                if current_cycle_buys >= max_buys_per_cycle:
                                    self.sig_log.emit(f"🛡️ [안전 장치] 최대 매수 한도({max_buys_per_cycle}회) 도달. 탐색 마감.", "warning")
                                    break
                                if needed_count <= 0: break
                                
                            # 💡 [추가] 매수가 최종 실패했다면 10분 쿨타임을 걸어서 무한 도배를 원천 차단합니다!
                            else:
                                if not hasattr(self.mw, 'cooldown_dict'): self.mw.cooldown_dict = {}
                                self.mw.cooldown_dict[code] = datetime.now()
                                self.sig_log.emit(f"🛑 [{stock_name}] 매수 불가 상태. 10분간 탐색을 보류합니다.", "error")
                                if code in self.log_step_memory:
                                    del self.log_step_memory[code]
                        
                        # 🚀 [버그 완벽 수정 1] 살 돈(예수금)이 0원이라서 못 샀을 때 로그 출력!
                        else:
                            if self.log_step_memory.get(code, 0) < 3:
                                self.sig_log.emit(f"💸 [{stock_name}] 3차 승인 통과! BUT 예수금 부족으로 스킵 (예수금: {my_cash:,.0f}원)", "warning")
                                self.log_step_memory[code] = 3

                    # 🚀 [버그 완벽 수정 2] 예수금은 있지만, 내가 설정한 '최대 투자 비중'이 꽉 차서 스킵될 때!
                    else:
                        if self.log_step_memory.get(code, 0) < 3:
                            self.sig_log.emit(f"🔒 [{stock_name}] 3차 승인 통과! BUT 최대 투자 한도({use_funds_percent}%) 꽉 차서 스킵.", "warning")
                            self.log_step_memory[code] = 3

            else:
                # 확률이 떨어지면 다음 턴에 다시 알림을 받기 위해 장부 리셋
                if code in self.log_step_memory:
                    del self.log_step_memory[code]

            try: db_temp.update_realtime(code, curr_price, prob*100, "NO", "탐색 중...")
            except: pass
            if len(scanned_log_list) >= min_scan_stocks: break

        # 스캔 완료 브리핑 및 UI 표 일괄 갱신
        if scanned_log_list:
            scanned_log_list = sorted(scanned_log_list, key=lambda x: x['prob'], reverse=True)
            top_msg = ", ".join([f"{x['name']}({x['prob']*100:.1f}%)" for x in scanned_log_list[:3]])
            self.sig_log.emit(f"🔎 1분 스캔 완료 ({len(scanned_log_list)}개 탐색). TOP 3: {top_msg}", "info")

        mkt_cols = ['시간','종목코드','종목명','현재가','시가','고가','저가','1분등락률','거래대금','거래량에너지','이격도','거래량']
        str_cols = ['시간','종목코드','종목명','상승확률','MA_5','MA_20','RSI','MACD','전략신호','상태메시지']

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

        # =================================================================
        # 🧹 [여기에 삽입!] 1분 스캔 사이클이 모두 끝난 직후 뇌(캐시) 용량 청소
        # =================================================================
        # 💡 [상세 설명]
        # 장이 끝나거나, 스캔 대상이 계속 바뀌면서 df_cache 데이터가 무한정 쌓이는 것을 막습니다.
        # 현재 내 주머니(my_holdings)에 없고, 방금 스캔한 핫한 종목(scan_targets)에도 없는
        # 쓸모없는 과거 종목 데이터라면 캐시(뇌)에서 삭제하여 메모리(RAM) 터짐을 방지합니다.
        if len(self.mw.df_cache) > 300: # 💡 300개 이상 쌓이면 청소 시작
            keys_to_delete = []
            for k in self.mw.df_cache.keys():
                if k not in self.mw.my_holdings and k not in scan_targets:
                    keys_to_delete.append(k)
            for k in keys_to_delete:
                del self.mw.df_cache[k]

# =====================================================================
# 🖥️ 메인 UI 클래스
# =====================================================================
class FormMain(QtWidgets.QMainWindow):
    sig_safe_log = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()

        # 🔥 [핵심 수정] 실수로 삭제되었던 UI 도화지 렌더링 코드를 다시 채워 넣습니다!
        # 이 코드가 있어야 버튼, 텍스트 박스 등 화면이 정상적으로 그려집니다.
        self.initUI()

        # 스레드에서 안전하게 로그를 찍기 위해 신호(Signal)를 연결합니다.
        self.sig_safe_log.connect(self._safe_append_log_sync)

        # -------------------------------------------------------------
        # 🗄️ DB 매니저 초기화 및 유령 데이터 청소 구간
        # -------------------------------------------------------------
        self.db = JubbyDB_Manager()
        self.db.cleanup_old_data() 

        # 🚀 [버그 완벽 수정 1] 어제 남은 유령 데이터 강제 청소!
        # 프로그램이 비정상 종료되어 DB에 남아있는 과거의 '미체결' 주문들을 찾아내어
        # 증권사 서버에 없는 주문을 취소하려 드는 헛수고를 막기 위해 상태를 '만료'로 강제 변경합니다.
        try:
            conn = self.db._get_connection(self.db.shared_db_path) # 공유 DB에 접근하는 길을 엽니다.
            # 쿼리 설명: 상태가 '미체결'이면서, 시간이 오늘(now, localtime) 이전인 과거 데이터의 상태를 '기간만료(자동정리)'로 바꿉니다.
            conn.execute("UPDATE TradeHistory SET Status = '기간만료(자동정리)' WHERE Status = '미체결' AND time < date('now', 'localtime')")
            conn.commit() # 변경 사항을 DB에 도장 찍어 확정합니다.
            conn.close()  # 볼일이 끝났으니 문을 닫습니다.
        except Exception as e: 
            pass # 혹시 DB가 잠겨있더라도 프로그램이 튕기지 않도록 부드럽게 무시하고 넘어갑니다.

        # 🔥 [추가] C#과 실시간으로 차트 데이터를 주고받을 통신 요원을 9001번 포트에 대기시킵니다.
        self.tcp_client = TcpJsonClient(host="127.0.0.1", port=9001)

        # 기본 설정값(예산, 모드 등)을 불러옵니다.
        self.init_default_settings()

        # 한국투자증권 API 통신 매니저를 깨우고 작동을 시작합니다.
        self.api_manager = KIS_Manager(ui_main=self)
        self.api_manager.start_api() 
        
        # 👇 이 세 줄을 새로 추가하여 화면 우측/하단에 붙을 미니 체결 Ticker 창을 부활시킵니다!
        self.ticker_window = FormTicker(main_ui=self)
        self.ticker_window.show()
        self.add_log("⚡ 실시간 체결 Ticker 창이 활성화되었습니다.", "info")

        # 🚀 [추가] 켜지자마자 메인폼 옆에 자석처럼 찰싹 붙여줍니다.
        # 메인폼 UI가 완전히 그려질 시간을 벌기 위해 0.1초(100ms) 뒤에 이동 명령을 내립니다.
        QtCore.QTimer.singleShot(100, self.ticker_window.snap_to_main)

        # AI 뇌 역할을 할 전략 엔진을 탑재합니다.
        self.strategy_engine = JubbyStrategy(log_callback=self.add_log)

        # 통신 연결 버튼이 있다면 화면에 보여주고 클릭 이벤트를 연결합니다.
        if hasattr(self, 'btnConnected'):
            self.btnConnected.show()  
            self.btnConnected.clicked.connect(self.btnConnectedClickEvent)

        # 🔒 [핵심] 매수/매도 엔진이 동시에 '내 지갑(잔고)'을 건드려서 돈 복사/삭제 버그가 일어나는 것을 막는 튼튼한 자물쇠입니다.
        import threading
        self.holdings_lock = threading.Lock()
        
        # 🚜 실제 주식을 사고 팔 새로운 일꾼들(스레드)이 들어갈 빈 자리를 만들어 둡니다.
        self.buy_worker = None
        self.sell_worker = None
        
        # -------------------------------------------------------------
        # 📖 DB에서 오늘 감시할 관심 종목 명단(target_stocks)을 불러오는 구간
        # -------------------------------------------------------------
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            query = f"SELECT symbol, symbol_name FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
            df_dict = pd.read_sql(query, conn)
            conn.close()
            
            # 1. 불러온 데이터를 전략 엔진이 읽기 편하도록 딕셔너리({종목코드: 종목명}) 형태로 변환합니다.
            if SystemConfig.MARKET_MODE == "DOMESTIC": 
                # 국내 주식은 005930 처럼 앞에 0이 사라지지 않도록 zfill(6)으로 6자리를 강제 보정합니다.
                self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str).str.zfill(6), df_dict['symbol_name']))
            else: 
                # 해외 주식은 티커(TSLA 등) 형태이므로 그대로 사용합니다.
                self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str), df_dict['symbol_name']))
            
            # ---------------------------------------------------------
            # 🔥 위에서 예쁘게 만든 '명단(딕셔너리)'을 전략 엔진에게 배달해줍니다.
            # ---------------------------------------------------------
            if hasattr(self, 'strategy_engine'):
                self.strategy_engine.set_stock_dict(self.DYNAMIC_STOCK_DICT)
            # ---------------------------------------------------------

            if not self.DYNAMIC_STOCK_DICT: raise ValueError("DB 명단이 비어 있습니다.")
            self.add_log(f"📖 DB에서 {len(self.DYNAMIC_STOCK_DICT)}개 종목 명단을 불러왔습니다!", "info")

        except Exception as e:
            # 명단을 불러오는 데 실패하면 시스템이 멈추지 않게 기본값(삼성전자)을 강제로 넣어줍니다.
            self.add_log(f"⚠️ DB 명단 로드 실패: {e}", "warning")
            self.DYNAMIC_STOCK_DICT = {"005930": "삼성전자"}
            
            if hasattr(self, 'strategy_engine'):
                self.strategy_engine.set_stock_dict(self.DYNAMIC_STOCK_DICT)

        # =========================================================
        # 🔥 [핵심 수정] 위 try-except 블록에서 혹시라도 누락되었을 경우를 대비해
        # 전략 엔진에게 명단을 한 번 더 확실하게 쥐어주고 쐐기를 박습니다.
        self.strategy_engine.set_stock_dict(self.DYNAMIC_STOCK_DICT)
        # =========================================================

        # 내 보유 종목(my_holdings)과 내 잔고(last_known_cash)를 저장할 바구니 초기화
        self.my_holdings = {}; self.last_known_cash = 0 

        # 🚀 [추가] 표 데이터 유실 및 UI 깜빡임 방지를 위한 누적 기록용 수첩 
        # (웹소켓 데이터가 너무 빨리 들어올 때 생기는 렌더링 충돌을 막아줍니다)
        self.accumulated_market = {}   # 시장 시세 데이터 기록용
        self.accumulated_strategy = {} # AI 전략 데이터 기록용
        self.accumulated_account = {}  # 잔고/매도 내역 기록용
        
        # 🚀 [추가] 1분에 1번만 증권사 서버와 통신하기 위한 하이브리드 캐시 메모리 
        # (과도한 API 호출로 인한 정지(Rate Limit)를 막아줍니다)
        self.df_cache = {}          
        self.last_fetch_time = {}

        # -------------------------------------------------------------
        # 🔒 2-Track(매수/매도 분리) 스레드 공유 변수 및 상태 세팅
        # -------------------------------------------------------------
        # 🔥 [버그 수정 1] 프로그램 켤 때 누적 실현 손익이 0원으로 초기화되는 것을 막고 DB에서 가져옵니다!
        try:
            self.cumulative_realized_profit = float(self.db.get_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", "0.0"))
        except:
            self.cumulative_realized_profit = 0.0
            
        self.loss_streak_cnt = 0              # 연속으로 손절한 횟수를 세는 카운터 (연패 관리)
        self.panic_mode = False               # 긴급 전량 매도(패닉 셀) 작동 상태
        self.market_crash_mode = False        # 시장 전체가 폭락 중인지 판단하는 플래그
        self.cooldown_dict = {}               # 한 번 팔았던 종목에 10분간 다시 들어가지 못하게 막는 쿨타임 수첩
        
        # 🚜 매수(BuyHunter) 전담반과 매도(SellGuardian) 전담반을 각각 채용합니다.
        self.buy_worker = BuyHunterWorker(main_window=self)
        self.sell_worker = SellGuardianWorker(main_window=self)
        
        # 일꾼들이 보내는 메시지를 UI 로그창에 띄우기 위해 통신선(Signal)을 연결합니다.
        self.buy_worker.sig_log.connect(self.add_log)
        self.sell_worker.sig_log.connect(self.add_log)
        
        # 일꾼들이 가져온 데이터를 화면의 '전략 표'와 '시장 표'에 업데이트 하도록 연결합니다.
        self.buy_worker.sig_strategy_df.connect(self.update_strategy_table_slot)
        self.buy_worker.sig_market_df.connect(self.update_market_table_slot)
        
        # 매수/매도 주문이 나갔을 때 '주문 내역 표'에 한 줄씩 추가하도록 연결합니다.
        self.buy_worker.sig_order_append.connect(self.append_order_table_slot)
        self.sell_worker.sig_order_append.connect(self.append_order_table_slot)
        
        # 매수가 끝나면 C# 차트에 데이터를 동기화하라고 신호를 보냅니다.
        self.buy_worker.sig_sync_cs.connect(self.btnDataSendClickEvent)
        
        # 패닉 셀이 끝났거나 스레드가 종료되었을 때의 뒤처리 신호를 연결합니다.
        self.sell_worker.sig_panic_done.connect(self.panic_sell_done_slot)
        self.sell_worker.finished.connect(self.check_worker_stopped)
        # -------------------------------------------------------------

        # =====================================================================
        # 🔥 [탐정 출동] 프로그램 켜지자마자 감시 스레드 가동 (중복 실행 완벽 방지)
        # =====================================================================
        # 1. 혹시라도 이미 순찰을 돌고 있는 탐정이 있다면, 하던 일을 강제로 멈추게 하고 퇴근시킵니다.
        if hasattr(self, 'detective_worker') and self.detective_worker is not None:
            try:
                self.detective_worker.is_running = False
                self.detective_worker.quit()
                self.detective_worker.wait(1000)
                # 🌟 [핵심] 기존에 연결해둔 알림선(Signal)을 확실하게 뽑아버려 메시지가 두 번 뜨는 것을 막습니다.
                self.detective_worker.sig_log.disconnect() 
            except Exception: 
                pass

        # 2. 완전히 깨끗해진 상태에서 새 탐정을 1명만 고용하고 알림선을 새롭게 연결한 뒤 순찰을 보냅니다.
        self.detective_worker = DetectiveWorker(main_window=self)
        self.detective_worker.sig_log.connect(self.add_log)
        self.detective_worker.start()

        # 🔥 [추가] 켜지자마자 1초 뒤에 유령 주문을 싹 정리하는 명령을 내립니다.
        QtCore.QTimer.singleShot(1000, self.detective_worker.smart_cross_check_logic)
        
        # 3초 뒤에 증권사 서버에 물어봐서 진짜 내 잔고와 주식 보유량을 가져옵니다.
        QtCore.QTimer.singleShot(3000, self.load_real_holdings) 
        
        # 1시간(1000 * 60 * 60 ms)마다 카카오톡으로 주삐의 계좌 상태를 보고하는 타이머를 켭니다.
        self.kakao_timer = QtCore.QTimer(self)
        self.kakao_timer.timeout.connect(self.auto_status_report)
        self.kakao_timer.start(1000 * 60 * 60) 
        
        # 🔥 [추가] 당일 전체 누적 수익률을 계산하기 위한 변수 세팅
        self.daily_total_pnl_pct = 0.0
        
        # 🔥 [추가] 로그창(txtLog)에서 마우스 오른쪽 버튼을 누르면 메뉴(복사/지우기 등)가 뜨게 연결합니다.
        self.txtLog.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.txtLog.customContextMenuRequested.connect(self.show_log_context_menu)
        
        # 🔥 [추가] 프로그램 시작 후 2초 뒤에 DB에 남아있는 과거 주문 기록을 표(UI)에 예쁘게 불러옵니다.
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
                # 🚀 [완벽 복구] trade_worker는 이제 없으므로, 메인(self)에 있는 변수를 직접 초기화합니다!
                self.loss_streak_cnt = 0 
                self.panic_mode = False  
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
        """ [완벽 수정] UI를 직접 만지지 않고, 오직 DB만 갱신한 뒤 깔끔하게 새로고침합니다! """
        if not order_info: return 
        
        order_no = order_info.get('주문번호', '00000000')

        if not order_info.get('is_restore', False):
            try:
                code = order_info.get('종목코드', '')
                s_name = order_info.get('종목명', '') 
                order_str = str(order_info.get('주문종류', '')).upper()
                o_type = "BUY" if "매수" in order_str or "불타기" in order_str or "BUY" in order_str else "SELL"
                
                price = float(str(order_info.get('주문가격', '0')).replace(',', ''))
                qty = int(order_info.get('주문수량', 0))
                raw_y_rate = str(order_info.get('수익률', '0')).replace('%', '').replace(',', '').strip()
                y_rate = float(raw_y_rate) if raw_y_rate else 0.0
                
                conn = self.db._get_connection(self.db.shared_db_path)
                
                # 🚀 [방어막] 웹소켓이 '초고속 체결'로 껍데기를 먼저 만들어 둔 게 있는지 검사합니다.
                cursor = conn.execute("SELECT COUNT(*) FROM TradeHistory WHERE order_no = ?", (order_no,))
                
                if cursor.fetchone()[0] == 0:
                    # 1. 일반적인 상황: DB에 아무것도 없으니 평범하게 '미체결'로 Insert
                    self.db.insert_trade_history(order_no, code, o_type, price, qty, y_rate)
                    conn.execute("UPDATE TradeHistory SET symbol_name = ? WHERE order_no = ?", (s_name, order_no))
                else:
                    # 2. 꼬인 상황: 웹소켓이 '체결완료'로 먼저 만들어 둠! 
                    # ➔ 절대 Status(체결완료)는 건드리지 말고, 누락되었던 종목명, 종류 등 알맹이만 덮어씌웁니다!
                    conn.execute("""
                        UPDATE TradeHistory 
                        SET symbol_name = ?, type = ?, quantity = ?, order_price = ?, order_yield = ? 
                        WHERE order_no = ?
                    """, (s_name, o_type, qty, price, f"{y_rate}%", order_no))
                    
                conn.commit()
                conn.close()
            except Exception: pass

        # 🚀 [UI 두 줄 버그 원천 차단] 
        # 억지로 화면에 줄을 끼워 넣지 않고, 무조건 DB에서 깔끔하게 다시 읽어와 화면을 덮어씌웁니다.
        self.refresh_order_table()

    @QtCore.pyqtSlot() 
    def btnDataSendClickEvent(self):
        """ 🚀 [버벅임 완벽 해결 2] 수백 개의 DB 저장 및 TCP 통신 작업을 백그라운드 스레드로 넘겨 화면 렉 원천 차단! """
        
        # 1. 화면(UI 스레드)에서 표 데이터(DataFrame)를 안전하게 복사(Copy)해옵니다.
        # 이렇게 하면 일꾼이 이 데이터를 DB에 쓰는 동안 원본이 바뀌어서 팅기는 사고를 막을 수 있습니다.
        market_df = TradeData.market.df.copy() if not TradeData.market.df.empty else pd.DataFrame()
        account_df = TradeData.account.df.copy() if not TradeData.account.df.empty else pd.DataFrame()
        strategy_df = TradeData.strategy.df.copy() if not TradeData.strategy.df.empty else pd.DataFrame()

        def sync_task():
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

            # [Market DB 동기화]
            market_list = []
            if not market_df.empty:
                for _, row in market_df.iterrows():
                    sym = get_symbol(row)
                    if not sym: continue
                    market_list.append({"symbol": sym, "symbol_name": str(row.get("종목명", "")), "last_price": float(clean_num(row.get("현재가", "0"))), "open_price": float(clean_num(row.get("시가", "0"))), "high_price": float(clean_num(row.get("고가", "0"))), "low_price": float(clean_num(row.get("저가", "0"))), "return_1m": float(clean_num(row.get("1분등락률", "0"))), "trade_amount": float(clean_num(row.get("거래대금", "0"))), "vol_energy": float(clean_num(row.get("거래량에너지", "1"))), "disparity": float(clean_num(row.get("이격도", "100"))), "volume": float(clean_num(row.get("거래량", "0")))})
                try: self.db.update_market_table(market_list)
                except Exception as e: pass

            # [Account DB 동기화]
            account_list = []
            if not account_df.empty:
                for _, row in account_df.iterrows():
                    sym = get_symbol(row)
                    if not sym: continue
                    curr_price = float(clean_num(row.get("현재가", "0")))
                    account_list.append({"symbol": sym, "symbol_name": str(row.get("종목명", "")), "quantity": int(float(clean_num(row.get("보유수량", "0")))), "avg_price": float(clean_num(row.get("평균매입가", "0"))), "current_price": curr_price, "pnl_amt": float(clean_num(row.get("평가손익금", "0"))), "pnl_rate": float(clean_num(row.get("수익률", "0"))), "available_cash": float(clean_num(row.get("주문가능금액", "0")))})
                    if curr_price > 0:
                        try: self.db.insert_price_history(sym, curr_price)
                        except: pass
                try: self.db.update_account_table(account_list)
                except Exception as e: pass

            # [Strategy DB 동기화]
            strategy_list = []
            if not strategy_df.empty:
                for _, row in strategy_df.iterrows():
                    sym = get_symbol(row)
                    if not sym: continue
                    sig = str(row.get("전략신호", "")); sig = "BUY" if "BUY" in sig else ("SELL" if "SELL" in sig else ("WAIT" if "WAIT" in sig else sig))
                    
                    ai_prob_str = str(row.get("상승확률", "0")).replace("%", "")
                    try: ai_prob = float(ai_prob_str)
                    except ValueError: ai_prob = 0.0

                    strategy_list.append({
                        "symbol": sym, "symbol_name": str(row.get("종목명", "")), "ai_prob": ai_prob,
                        "ma_5": float(clean_num(row.get("MA_5", "0"))), "ma_20": float(clean_num(row.get("MA_20", "0"))), 
                        "RSI": float(clean_num(row.get("RSI", "0"))), "macd": float(clean_num(row.get("MACD", "0"))), 
                        "signal": sig, "status_msg": str(row.get("상태메시지", "")) 
                    })
                try: self.db.update_strategy_table(strategy_list)
                except Exception as e: pass

            # [C# 차트 서버(TCP) 발사]
            if hasattr(self, 'tcp_client') and self.tcp_client.is_connected:
                # 🚀 [버그 완벽 수정] 스레드 안에서 과거 데이터를 보내지 않도록, 
                # DB 동기화가 모두 끝난 직후의 가장 최신 TradeData 상태를 다시 한번 읽어서 보냅니다!
                
                # 1. 잔고(Account) 데이터 전송
                latest_account_data = TradeData.account_dict()
                if latest_account_data:
                    self.tcp_client.send_message("Account", latest_account_data)
                else:
                    # 빈 바구니라도 확실하게 보내서 UI를 갱신(초기화) 시킵니다.
                    self.tcp_client.send_message("Account", [])
                    
                # 2. 주문/체결(Order) 데이터도 함께 강제로 전송하여 밑에 있는 표도 새로고침 시킵니다!
                latest_order_data = TradeData.order_dict()
                if latest_order_data:
                    self.tcp_client.send_message("Order", latest_order_data)

        # 🔥 메인 화면은 냅두고, 복사해 둔 데이터를 바탕으로 백그라운드에서 조용히 DB에 씁니다!
        import threading
        threading.Thread(target=sync_task, daemon=True).start()

    @QtCore.pyqtSlot(object) 
    def update_market_table_slot(self, df):
        # 🚀 '시간' 컬럼을 넣어 구조를 100% 맞춰줍니다.
        standard_cols = ['시간','종목코드','종목명','현재가','시가','고가','저가','1분등락률','거래대금','거래량에너지','이격도','거래량']
        if df.empty: 
            TradeData.market.df = pd.DataFrame(columns=standard_cols)
            self.update_table(self.tbMarket, TradeData.market.df)
            return
            
        if '종목코드' not in df.columns and 'Symbol' in df.columns: df = df.rename(columns={'Symbol': '종목코드', 'Name': '종목명', 'Price': '현재가'})
        for col in standard_cols:
            if col not in df.columns: df[col] = "0"
            
        TradeData.market.df = df[standard_cols]
        self.update_table(self.tbMarket, TradeData.market.df)

    def load_real_holdings(self, *args, **kwargs):
        """ 
        🚀 [최종 해결판] 백그라운드 스레드 완전 폐기 & 100% 출력 보장
        (어떤 인자가 넘어오든 에러가 나지 않도록 *args, **kwargs로 방어막을 쳤습니다)
        """
        # 버튼을 눌렀는지, 아니면 인자로 수동 지시가 왔는지 완벽하게 감지
        is_manual = False
        if self.sender() is not None or kwargs.get('is_manual') is True:
            is_manual = True

        # 자물쇠 체크
        if getattr(self, 'is_fetching_account', False):
            if is_manual:
                self.add_log("⏳ 이전 데이터를 가져오는 중입니다. 잠시만 대기해주세요!", "warning")
            return
            
        self.is_fetching_account = True

        # 🚀 [즉각 피드백] 시작하자마자 로그를 띄웁니다.
        if is_manual:
            self.add_log("🔄 증권사 서버에 계좌 조회를 요청했습니다... (최대 1~3초 소요)", "info")
            try:
                # 데이터를 가져오는 동안 프로그램이 '응답 없음'에 빠지지 않게 화면을 강제로 한 번 새로고침합니다!
                from PyQt5.QtWidgets import QApplication
                QApplication.processEvents() 
            except: pass

        # 🚀 [문제 해결] 스레드(threading)를 쓰지 않고 여기서 바로 다이렉트로 실행합니다! (절대 안 팅김)
        try:
            # 1. 실제 잔고 긁어오기
            new_holdings = self.api_manager.get_real_holdings()
            if new_holdings is None: 
                if is_manual:
                    self.add_log("🚨 계좌 정보 조회 실패 (증권사 서버 지연)", "error")
                return

            with self.holdings_lock:
                # 삭제된 종목(매도 완료) 제거
                keys_to_delete = [code for code in self.my_holdings.keys() if code not in new_holdings]
                for code in keys_to_delete:
                    del self.my_holdings[code]
                    
                # 최신 종목 정보 덮어쓰기
                for code, info in new_holdings.items():
                    if code in self.my_holdings:
                        self.my_holdings[code]['qty'] = info['qty']
                        self.my_holdings[code]['price'] = info['price']
                    else:
                        self.my_holdings[code] = info
                    
            # 2. 예수금 업데이트
            d2_cash = 0
            try:
                api_cash = self.api_manager.get_d2_deposit() 
                if api_cash is not None and float(api_cash) > 0:
                    self.last_known_cash = float(api_cash)
                    d2_cash = int(float(str(api_cash).replace(',', '')))
            except Exception: pass

            # 3. 실시간 가격 수신을 위해 웹소켓 구독
            if hasattr(self, 'ticker_window') and hasattr(self.ticker_window, 'ws_worker'):
                for code in self.my_holdings.keys():
                    if code not in self.ticker_window.ws_worker.tracked_symbols:
                        self.ticker_window.ws_worker.subscribe_stock_realtime(code)
                        self.ticker_window.ws_worker.tracked_symbols.add(code)

            # 4. 🚀 수동 클릭 시에만 상세 브리핑 띄우기 (이제 로그창에 100% 꽂힙니다!)
            if is_manual:
                total_invested = 0
                total_current_val = 0
                stock_details_str = ""
                
                if len(self.my_holdings) > 0:
                    with self.holdings_lock:
                        holdings_copy = list(self.my_holdings.items())
                        
                    for code, info in holdings_copy:
                        buy_price = info['price']
                        buy_qty = info['qty']
                        
                        stock_name = getattr(self, 'DYNAMIC_STOCK_DICT', {}).get(code, code)
                        
                        curr_price = buy_price
                        if hasattr(self, 'db'):
                            try:
                                p = self.db.get_realtime_price(code)
                                if p and p > 0: curr_price = p
                            except: pass
                            
                        if curr_price == buy_price and hasattr(self, 'df_cache'):
                            try:
                                cached_df = getattr(self, 'df_cache', {}).get(code)
                                if cached_df is not None and not cached_df.empty:
                                    curr_price = float(cached_df.iloc[-1]['close'])
                            except: pass
                                
                        fee_rate = 0.0023 
                        try:
                            from COMMON.Flag import SystemConfig
                            if getattr(SystemConfig, 'MARKET_MODE', 'DOMESTIC') != "DOMESTIC":
                                fee_rate = 0.001
                        except: pass
                            
                        invest_amt = buy_price * buy_qty
                        eval_amt = curr_price * buy_qty
                        estimated_fee = eval_amt * fee_rate 
                        
                        real_profit_amt = eval_amt - invest_amt - estimated_fee
                        real_profit_rate = (real_profit_amt / invest_amt) * 100 if invest_amt > 0 else 0.0
                        
                        total_invested += invest_amt
                        total_current_val += eval_amt
                        
                        stock_details_str += f"    🔸 {stock_name}: 매입 {buy_price:,.0f} -> 현재 {curr_price:,.0f} ({real_profit_rate:+.2f}%)\n"
                        
                total_unrealized_profit = total_current_val - total_invested
                total_asset = d2_cash + total_current_val
                realized_profit = getattr(self, 'cumulative_realized_profit', 0)
                
                msg = f"💼 [수동 계좌 조회] 총 {len(self.my_holdings)}개 동기화 완료!\n"
                msg += f"    💎 자산: {int(total_asset):,}원 (D+2 예수금: {d2_cash:,}원)\n"
                msg += f"    📈 누적손익: {int(realized_profit):+,}원 | 보유손익: {int(total_unrealized_profit):+,}원\n\n"
                
                if stock_details_str:
                    msg += stock_details_str.rstrip()
                else:
                    msg += "    💼 [보유 종목 없음]"
                    
                # 이제 스레드가 아니기 때문에 무조건 화면에 팍! 하고 찍힙니다.
                self.add_log(msg, "info")

        except Exception as e:
            if is_manual: 
                self.add_log(f"🚨 계좌 조회 에러: {e}", "error")
        finally:
            self.is_fetching_account = False
        
    def initUI(self):
        ui_file_path = resource_path("GUI/Main.ui")
        uic.loadUi(ui_file_path, self)
        
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
        
        # 🚀 [여기에 추가됨!] 통신 연결 버튼 직접 생성 (위치: 1530)
        self.btnConnected = self._create_nav_button("통신 연결 X", 1530)
        self.btnConnected.setFixedWidth(200) # 버튼 크기 조절
        
        self.btnClose = QtWidgets.QPushButton(" X ", self.centralwidget); self.btnClose.setGeometry(1875, 5, 40, 40); self.btnClose.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")
        
        self.btnDataCreatTest.clicked.connect(self.btnDataCreatClickEvent)
        self.btnDataSendTest.clicked.connect(self.btnDataSendClickEvent)
        self.btnSimulDataTest.clicked.connect(self.btnSimulTestClickEvent)
        self.btnAutoDataTest.clicked.connect(self.btnAutoTradingSwitch)
        self.btnDataClearTest.clicked.connect(self.btnDataClearClickEvent)
        
        # 🚀 [여기에 추가됨!] 클릭 시 이벤트 함수로 연결
        # self.btnConnected.clicked.connect(self.btnConnectedClickEvent)
        
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

            # 🚀 [추가] 시장가 매수 슬리피지 방어를 위한 안전마진 비율
            ("TRADE", "MARKET_ORDER_BUFFER", "98.0", "시장가 매수 시 증거금 부족 에러 방지용 안전마진 (%)"),
            
            # 🔥 [핵심 추가] 실전 3대장 방어막 세팅
            ("TRADE", "COOLDOWN_MINUTES", "10", "매도(청산) 후 재진입 금지 시간 (분) - 복수혈전 방지"),
            ("TRADE", "USE_SMART_LIMIT", "Y", "시장가 대신 스마트 지정가 사용 여부 (Y/N) - 슬리피지 방어"),
            ("API", "GLOBAL_API_DELAY", "0.05", "API 초당 호출 제한 방어용 딜레이 (초) - 트래픽 교통정리"),
            ("TRADE", "MIN_VOL_POWER", "105.0", "매수 승인 최소 체결강도 (100 이상이어야 매수세 우위)"),

            # 💸 [리스크 및 컷오프(손/익절) 설정] (이 부분을 찾아서 아래처럼 덮어쓰거나 추가하세요)
            ("TRADE", "PROFIT_RATE", "2.0", "기본 기계적 익절 라인 (%) - 초단타용"),
            ("TRADE", "STOP_RATE", "1.5", "기본 기계적 손절 라인 (%) - 밀림 방지용 짧은 손절"),
            ("TRADE", "TRAILING_STOP_GAP", "0.5", "최고점 대비 하락 허용 폭 (%) - 0.5%만 꺾여도 즉시 익절"),
            ("TRADE", "STRAT_PROFIT_PRESERVE", "1.0", "전략 매도 시 최소 수익 보존 라인 (%)"),
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
            self.db.set_shared_setting("RISK", "IS_LOCKED", "N")
            self.daily_total_pnl_pct = 0.0 
            # 🚀 [완벽 복구] trade_worker 대신 현재 메인 시스템의 변수 초기화
            self.loss_streak_cnt = 0
            self.panic_mode = False
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

    # def start_panic_sell(self):
    #     # 🛡️ [방어막] 파이썬 에러로 인해 프로그램이 팅기는 것을 원천 차단합니다!
    #     try:
    #         if not hasattr(self, 'trade_worker') or not self.trade_worker.is_running: return
    #         if len(self.my_holdings) == 0: self.btnAutoTradingSwitch(); return

    #         # 🚀 [버그 수정] 딕셔너리를 읽는 도중 크기가 변해서 팅기는 현상(RuntimeError) 완벽 해결!
    #         stock_names = [self.DYNAMIC_STOCK_DICT.get(c, c) for c in list(self.my_holdings.keys())]
            
    #         msg = f"🚨 [긴급 전체 청산 발동]\n전체 시장가 매도 진행!\n대상: {', '.join(stock_names)}"
    #         self.add_log(msg, "error"); self.send_kakao_msg(msg)
    #         self.trade_worker.panic_mode = True 
            
    #     except Exception as e:
    #         self.add_log(f"🚨 긴급 청산 시작 중 에러 발생: {e}", "error")

    def start_panic_sell(self):
        try:
            if not self.sell_worker or not self.sell_worker.is_running: return
            if len(self.my_holdings) == 0: self.btnAutoTradingSwitch(); return

            with self.holdings_lock:
                stock_names = [self.DYNAMIC_STOCK_DICT.get(c, c) for c in list(self.my_holdings.keys())]
            
            msg = f"🚨 [긴급 전체 청산 발동]\n전체 시장가 매도 진행!\n대상: {', '.join(stock_names)}"
            self.add_log(msg, "error"); self.send_kakao_msg(msg)
            
            # 🔥 [팅김 방지 3] 매도 일꾼이 청산하는 동안, 매수 일꾼이 안전하게 멈출 때까지 잠시 기다려 충돌을 완벽 차단합니다!
            # 🔥 [수정] 팅김의 주범이었던 wait() 함수를 과감하게 지웁니다! 스위치만 꺼주면 알아서 퇴근합니다.
            if hasattr(self, 'buy_worker') and self.buy_worker:
                self.buy_worker.is_running = False
                # wait(500) 삭제 완료!

            self.panic_mode = True # 🔥 메인 공유 변수 발동!
        except Exception as e:
            self.add_log(f"🚨 긴급 청산 에러: {e}", "error")

    @QtCore.pyqtSlot()
    def panic_sell_done_slot(self):
        self.is_stopping = False 
        self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
        self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")

    def btnAutoTradingSwitch(self):
        try:
            if getattr(self, 'is_stopping', False): return
                
            if not (self.buy_worker and self.buy_worker.is_running): 
                # 🚀 1. 엔진 가동 전 DB에서 누적 수익금 로드 및 표 초기화
                try: 
                    self.cumulative_realized_profit = float(self.db.get_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", "0.0"))
                except: 
                    self.cumulative_realized_profit = 0.0

                try:
                    conn = self.db._get_connection(self.db.shared_db_path)
                    conn.execute("DELETE FROM TradeHistory")
                    conn.execute("DELETE FROM AccountStatus")
                    conn.commit()
                    conn.close()
                    
                    TradeData.order.df = pd.DataFrame(columns=['주문번호','시간','종목코드','종목명','주문종류','주문가격','주문수량','체결수량','상태','수익률'])
                    self.tbOrder.setRowCount(0)
                    
                    TradeData.account.df = pd.DataFrame(columns=['시간', '종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','상태','주문가능금액'])
                    self.tbAccount.setRowCount(0)
                    if hasattr(self, 'accumulated_account'):
                        self.accumulated_account.clear() 
                except Exception: pass

                # =========================================================
                # 🔥 [수정 핵심] 일꾼 3명 배정 및 올바른 통신선 연결
                # =========================================================
                self.buy_worker = BuyHunterWorker(self)
                self.sell_worker = SellGuardianWorker(self)
                self.monitor_worker = SystemMonitorWorker(self) # 📺 일꾼 3호(모니터 요원) 추가!
                
                # 1) 매수 일꾼 선 연결
                self.buy_worker.sig_log.connect(self.add_log)
                self.buy_worker.sig_strategy_df.connect(self.update_strategy_table_slot)
                self.buy_worker.sig_market_df.connect(self.update_market_table_slot)
                self.buy_worker.sig_order_append.connect(self.append_order_table_slot)
                self.buy_worker.sig_sync_cs.connect(self.btnDataSendClickEvent)
                
                # 2) 매도 일꾼 선 연결 (UI 갱신선은 모두 제거됨)
                self.sell_worker.sig_log.connect(self.add_log)
                self.sell_worker.sig_order_append.connect(self.append_order_table_slot)
                self.sell_worker.sig_panic_done.connect(self.panic_sell_done_slot)
                
                # 3) 📺 모니터 요원 선 연결 (표 그리기와 C# 통신 전담)
                self.monitor_worker.sig_log.connect(self.add_log)
                self.monitor_worker.sig_account_df.connect(self.update_account_table_slot)
                self.monitor_worker.sig_sync_cs.connect(self.btnDataSendClickEvent)

                # 4) 안전한 퇴근을 위한 보고망 연결 (3명 모두)
                self.finished_worker_count = 0 
                self.buy_worker.finished.connect(self.check_worker_stopped)
                self.sell_worker.finished.connect(self.check_worker_stopped)
                self.monitor_worker.finished.connect(self.check_worker_stopped) # 📺 추가!

                # =========================================================
                # 🚀 3명 동시 출발!
                # =========================================================
                self.panic_mode = False 
                self.buy_worker.start()
                self.sell_worker.start() 
                self.monitor_worker.start() # 📺 출동!
                
                self.btnAutoDataTest.setText("자동 매매 중단 (STOP)")
                self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
                self.add_log("🚀 [주삐 3-Track 엔진] 매수/매도/모니터 병렬 감시망 가동!", "success")
            else: 
                # [정지 로직]
                self.is_stopping = True 
                self.btnAutoDataTest.setText("감시망 종료 대기중...")
                self.btnAutoDataTest.setStyleSheet("background-color: rgb(40, 40, 40); color: Gray;")
                
                # 퇴근 스위치 3개 모두 내리기
                if hasattr(self, 'buy_worker') and self.buy_worker: self.buy_worker.is_running = False
                if hasattr(self, 'sell_worker') and self.sell_worker: self.sell_worker.is_running = False 
                if hasattr(self, 'monitor_worker') and self.monitor_worker: self.monitor_worker.is_running = False # 📺 추가!
                
        except Exception as e:
            self.add_log(f"🚨 스위치 에러: {e}", "error")

    @QtCore.pyqtSlot()
    def check_worker_stopped(self):
        # 🚀 [수정] 3명이 모두 안전하게 퇴근했는지 확인합니다.
        if not hasattr(self, 'finished_worker_count'): self.finished_worker_count = 0
        self.finished_worker_count += 1

        # 3명 모두 무사히 퇴근 완료했을 때 화면 갱신
        if self.finished_worker_count >= 3:
            if self.btnAutoDataTest.text() == "감시망 종료 대기중...":
                self.is_stopping = False
                self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
                self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
                self.add_log("✅ [주삐 엔진] 3-Track 감시망이 완벽하고 안전하게 종료되었습니다.", "info")
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
                        QtWidgets.QApplication.processEvents() # 🔥 대기하는 1초 동안 렉 방지
                    elif "잔고" in error_msg:
                        # 🚨 [치명적 버그 수정] 이미 매도된 유령 잔고라면, 
                        # 무한 클릭 방지를 위해 주머니(my_holdings)와 UI 표에서 강제로 지워버립니다!
                        self.add_log(f"🚨 [{stock_name}] 이미 팔렸거나 매도할 잔고가 없습니다. 유령 잔고를 청소합니다.", "error")
                        
                        if code in self.my_holdings:
                            del self.my_holdings[code] # 내 주머니에서 삭제
                        self.tbAccount.removeRow(row)  # UI 표에서 해당 줄 삭제
                        
                        break # 잔고가 없으면 더 이상 재시도할 필요가 없으므로 반복문 탈출!
                    else:
                        break # 기타 알 수 없는 에러도 포기

                if res_odno: # 매도 주문 성공 (주문번호를 받음)
                    # 💡 [버그 완벽 해결] 성급하게 수익금을 더하거나 종목을 지우지 않고, 웹소켓(Ticker)에게 체결 확인을 맡깁니다!
                    profit_rate = ((curr_price - buy_price) / buy_price) * 100 if buy_price > 0 else 0.0

                    # 1. Ticker 창 및 로그에 '수동 매도 접수' 기록
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    msg = f"📝 [수동 매도 접수] {stock_name} | 매도 주문이 거래소에 전달되었습니다. (체결 대기 중)"
                    self.add_log(msg, "info")
                    
                    try:
                        # 2. DB에 '미체결' 상태로 기록
                        self.db.insert_trade_history(res_odno, code, "SELL", curr_price, qty, profit_rate, status="미체결", filled_qty=0)
                        conn = self.db._get_connection(self.db.shared_db_path)
                        conn.execute("UPDATE TradeHistory SET symbol_name = ? WHERE order_no = ?", (stock_name, res_odno))
                        conn.commit()
                        conn.close()
                    except Exception as e:
                        pass

                    # 3. 주문 내역 표(tbOrder)에 '미체결'로 띄우기
                    self.append_order_table_slot({
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
                    error_msg = getattr(self.api_manager.api, 'last_error_msg', '서버 응답 없음')
                    self.add_log(f"❌ [{stock_name}] 수동 매도 거절! 사유: {error_msg}", "error")

        except Exception as e:
            self.add_log(f"🚨 수동 매도 처리 중 에러: {e}", "error")
        finally:
            # 🚀 [방어막 해제] 처리가 끝나면 자물쇠를 풀어줍니다.
            self.is_emergency_running = False
            
    def get_ai_probability(self, code):
        current_minute = datetime.now().strftime("%H:%M")
        
        if self.last_fetch_time.get(code) != current_minute:
            temp_df = self.api_manager.fetch_minute_data(code)
            if temp_df is not None and not temp_df.empty:
                # 🚀 [버그 완벽 수정 2] 데이터가 26분어치가 안 쌓였더라도 일단 표에 띄울 수 있게 무조건 저장!
                if len(temp_df) >= 26:
                    temp_df = self.strategy_engine.calculate_indicators(temp_df)
                self.df_cache[code] = temp_df
                self.last_fetch_time[code] = current_minute

        cached_df = self.df_cache.get(code)

        if cached_df is None or cached_df.empty: 
            return 0.0, 0, None
            
        df = cached_df.copy()
        
        realtime_price = self.db.get_realtime_price(code)
        curr_price = realtime_price if realtime_price > 0 else float(df.iloc[-1]['close'])
        df.at[df.index[-1], 'close'] = curr_price 
        
        prob = 0.0
        # 🚀 26분어치 데이터가 차올랐을 때만 AI 엔진을 돌려 에러를 방지
        if len(df) >= 26 and self.strategy_engine.ai_model is not None:
            features = self.strategy_engine.get_ai_features(df)
            if features is not None: 
                try: prob = self.strategy_engine.ai_model.predict_proba(features)[0][1]
                except: pass
                
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
        
    def btnCloseClickEvent(self): 
        QtWidgets.QApplication.quit() 
        os._exit(0)        
    def btnDataCreatClickEvent(self): pass
    def generate_and_send_mock_data(self): pass
    
    def update_table(self, tableWidget, df):
        tableWidget.setUpdatesEnabled(False)
        try:
            # 🚀 1. 데이터가 아예 없더라도 빈 껍데기(DataFrame)를 만들어 강제로 헤더를 그립니다.
            if df is None:
                df = pd.DataFrame()

            current_headers = [tableWidget.horizontalHeaderItem(i).text() if tableWidget.horizontalHeaderItem(i) else "" for i in range(tableWidget.columnCount())]
            if tableWidget.columnCount() != len(df.columns) or current_headers != list(df.columns):
                tableWidget.setColumnCount(len(df.columns))
                tableWidget.setHorizontalHeaderLabels(list(df.columns))

            # 🚀 2. 데이터가 0개면 빈칸으로 만들고 종료 (헤더는 이미 업데이트됨)
            if df.empty:
                tableWidget.setRowCount(0)
                return

            current_row_count = tableWidget.rowCount()
            new_row_count = len(df)                    
            if current_row_count < new_row_count:
                for _ in range(new_row_count - current_row_count): tableWidget.insertRow(tableWidget.rowCount())
            elif current_row_count > new_row_count:
                for _ in range(current_row_count - new_row_count): tableWidget.removeRow(tableWidget.rowCount() - 1)
                    
            for i in range(new_row_count):
                for j, col in enumerate(df.columns):
                    val = str(df.iloc[i, j]); item = tableWidget.item(i, j)     
                    if item is None: 
                        item = QtWidgets.QTableWidgetItem(val)
                        item.setTextAlignment(QtCore.Qt.AlignCenter)
                        tableWidget.setItem(i, j, item)
                    else:
                        if item.text() != val: item.setText(val)
                    
                    # 🎨 텍스트 색상 입히기
                    if val == '체결완료': item.setForeground(QtGui.QColor("lime"))
                    elif val == '미체결': item.setForeground(QtGui.QColor("yellow"))
                    elif '주문취소' in val: item.setForeground(QtGui.QColor("red"))
                    elif '매도완료' in val: item.setForeground(QtGui.QColor("skyblue"))
                    else: item.setForeground(QtGui.QColor("white"))
                    
        except Exception: pass
        finally: tableWidget.setUpdatesEnabled(True)
        
    @QtCore.pyqtSlot()
    def refresh_order_table(self):
        """ [신규] 취소 등 상태 변화를 화면에 즉시 반영하기 위해 주문 표 새로고침 """
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            # 🔥 [시간 잘림 수정] 시간을 년/월/일 빼고 시:분:초만 가져옵니다!
            query = "SELECT order_no, strftime('%H:%M:%S', time) AS time, symbol, symbol_name, type, price, quantity, filled_quantity, Status, order_yield FROM TradeHistory WHERE time >= date('now', 'localtime') ORDER BY time DESC"
            df = pd.read_sql(query, conn)
            conn.close()
            if not df.empty:
                df.columns = ['주문번호', '시간', '종목코드', '종목명', '주문종류', '주문가격', '주문수량', '체결수량', '상태', '수익률']
                self.update_table(self.tbOrder, df) # UI에 그리기
        except: pass

    def load_unfilled_orders_to_ui(self):
        """ [완벽 수정] 재시작 시 DB 내역을 바탕으로 표를 동기화합니다. """
        # 이제 억지로 줄을 추가할 필요가 없습니다. 
        # DB에 저장된 내역을 그대로 읽어오도록 새로고침만 실행합니다.
        self.refresh_order_table()
    def btnDataClearClickEvent(self): 
        self.tbAccount.setRowCount(0); self.tbStrategy.setRowCount(0); self.tbOrder.setRowCount(0); self.tbMarket.setRowCount(0)

    @QtCore.pyqtSlot()
    def btnConnectedClickEvent(self):
        try:
            if hasattr(self, 'tcp_client'):
                if self.tcp_client.is_connected:
                    self.add_log("✅ C# UI 차트 서버와 정상적으로 통신이 연결되어 있습니다.", "success")
                    self.btnConnected.setText("통신 연결 O")
                    self.btnConnected.setStyleSheet("background-color: rgb(5,5,15); color: Lime;")
                else:
                    self.add_log("🔄 C# UI와 통신 연결이 끊어졌습니다. 재연결을 시도합니다...", "warning")
                    self.btnConnected.setText("통신 연결 중...")
                    self.btnConnected.setStyleSheet("background-color: rgb(5,5,15); color: Yellow;")
                    
                    # 소켓을 닫아버리면 TcpJsonClient가 알아서 1초 뒤에 다시 연결을 시도합니다.
                    if self.tcp_client.sock:
                        try: self.tcp_client.sock.close()
                        except: pass
                        self.tcp_client.sock = None
            else:
                self.add_log("🚨 통신 클라이언트(TcpJsonClient)가 존재하지 않습니다.", "error")
        except Exception as e:
            self.add_log(f"🚨 통신 버튼 에러: {e}", "error")

    @QtCore.pyqtSlot(str)
    def remove_order_by_no(self, order_no):
        """ 🔥 [팅김 방지 2] 탐정이 취소 명령만 보내면, 안전하게 메인 스레드에서 직접 행을 찾아 지웁니다. """
        try:
            for row in range(self.tbOrder.rowCount()):
                item = self.tbOrder.item(row, 0)
                if item and item.text() == order_no:
                    self.tbOrder.removeRow(row)
                    break
        except Exception:
            pass

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    mainWindow = FormMain()
    mainWindow.show()
    sys.exit(app.exec_())