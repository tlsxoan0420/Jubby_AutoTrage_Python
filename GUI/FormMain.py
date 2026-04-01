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
                try:
                    db_worker.conn.execute(f"DELETE FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'")
                    df_db.to_sql('target_stocks', con=db_worker.conn, if_exists='append', index=False)
                    db_worker.conn.commit()
                    self.sig_log.emit(f"▶️ [수집기] DB에 {len(stock_list)}개 명단 저장 완료!", "info")
                except Exception as e:
                    self.sig_log.emit(f"🔥 [수집기] DB 저장 에러: {e}", "error")
                    
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
# 🤖 [일꾼 3호] 매매 관리자 (🔥 초고속 1분 사이클 & 팅김 원천 차단)
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

    def run(self):
        self.is_running = True
        try: JubbyDB_Manager().update_system_status('TRADER', '감시망 가동 중 🟢', 100)
        except: pass
        
        while self.is_running:
            try: 
                self.process_trading()
            except Exception as e: 
                self.sig_log.emit(f"🚨 매매 분석 중 일시적 오류 발생: {e}", "error")
                
            # 🔥 다음 탐색까지 쉬는 시간 조절 (100 = 10초, 50 = 5초)
            # 10초만 쉬고 곧바로 다시 주도주를 탐색하러 돌아갑니다!
            for _ in range(150):
                if not self.is_running: break 
                time.sleep(0.1)
                
        # 스레드가 죽기 직전 메모리 충돌을 막기 위한 안전장치
        time.sleep(0.5)

    def execute_guaranteed_sell(self, code, qty, current_price):
        stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
        max_retries = 10 
        for i in range(max_retries):
            if self.mw.api_manager.sell(code, qty):
                if i > 0: self.sig_log.emit(f"✅ [{stock_name}] {i}번의 재시도 끝에 매도 접수 완료!", "success")
                return True
            self.sig_log.emit(f"⚠️ [{stock_name}] 매도 실패! 즉시 재시도합니다... ({i+1}/{max_retries})", "warning")
            time.sleep(1.0) 
            if not self.is_running and not getattr(self, 'panic_mode', False): break
            
        if self.is_running or getattr(self, 'panic_mode', False):
            self.sig_log.emit(f"🚨 [{stock_name}] 매도 {max_retries}회 연속 실패!", "error")
        return False

    def execute_guaranteed_buy(self, code, qty):
        stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
        max_retries = 5 
        if self.mw.api_manager.buy_market_price(code, qty): return True
            
        self.sig_log.emit(f"⚠️ [{stock_name}] 1차 매수 실패! 1초 후 AI 재판단 후 재시도...", "warning")
        time.sleep(1.0) 
        
        for i in range(1, max_retries):
            if not self.is_running or getattr(self, 'panic_mode', False): return False
            try: prob, curr_price, df_feat = self.mw.get_ai_probability(code)
            except: return False
            if prob == -1.0 or df_feat is None or df_feat.empty: return False
            if self.mw.strategy_engine.check_trade_signal(df_feat, code) != "BUY": return False
            
            if self.mw.api_manager.buy_market_price(code, qty): return True
            time.sleep(0.5) 
        return False

    def get_realtime_hot_stocks(self): 
        import requests, random, json
        pool = list(self.mw.DYNAMIC_STOCK_DICT.keys())
        hot_list = []
        db_temp = JubbyDB_Manager()
        
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
                    time.sleep(0.2) 
            except Exception: pass

        if len(hot_list) < 20: 
            self.sig_log.emit("⚠️ 랭킹 API 응답 부족으로 랜덤 스캔 모드 가동", "warning")
            remaining_pool = [c for c in pool if c not in hot_list]
            if remaining_pool:
                fill_list = random.sample(remaining_pool, min(target_limit - len(hot_list), len(remaining_pool)))
                hot_list.extend(fill_list)

        return hot_list

    def process_trading(self):
        # 🔥 [안전장치 1] 중지 버튼을 누르면 이 함수 시작부터 진입을 막습니다.
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
        
        if not self.is_running: return # 🔥 [안전장치 2] 즉시 탈출
        
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
                # 🔥 [안전장치 3] 여기서부터 핵심입니다. '중지' 버튼이 눌리면 루프를 부수고 데이터를 화면에 쏘지 않은 채 완전 퇴근합니다.
                if not self.is_running: 
                    self.sig_log.emit("🛑 보유 종목 검사 중단 (사용자 요청)", "warning")
                    return 

                if code not in self.mw.my_holdings: continue 

                time.sleep(0.2) # 보유 종목 통신 안정화

                buy_price = info['price']; buy_qty = info['qty']; stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
                high_watermark = info.get('high_watermark', buy_price); buy_time = info.get('buy_time', now); half_sold = info.get('half_sold', False) 

                if isinstance(buy_time, str):
                    try: buy_time = datetime.strptime(buy_time, '%Y-%m-%d %H:%M:%S')
                    except: buy_time = now
                    self.mw.my_holdings[code]['buy_time'] = buy_time 

                df = self.mw.api_manager.fetch_minute_data(code)
                if df is None or len(df) < 26: continue
                
                df = self.mw.strategy_engine.calculate_indicators(df)
                curr_price = float(df.iloc[-1]['close']); profit_rate = ((curr_price - buy_price) / buy_price) * 100 
                profit_amt = (curr_price - buy_price) * buy_qty
                
                stock_details_str += f"  🔸 {stock_name}: 매입 {buy_price:,.2f} -> 현재 {curr_price:,.2f} ({profit_rate:+.2f}%)\n"
                
                target_price, stop_price = self.mw.strategy_engine.get_dynamic_exit_prices(df, buy_price)
                target_rate = ((target_price - buy_price) / buy_price) * 100; stop_rate = ((stop_price - buy_price) / buy_price) * 100

                if curr_price > high_watermark:
                    self.mw.my_holdings[code]['high_watermark'] = curr_price
                    high_watermark = curr_price
                trail_drop_rate = ((high_watermark - curr_price) / high_watermark) * 100 if high_watermark > 0 else 0
                elapsed_mins = (now - buy_time).total_seconds() / 60.0

                total_invested += (buy_price * buy_qty); total_current_val += (curr_price * buy_qty)
                
                curr_open = float(df.iloc[-1]['open']); curr_high = float(df.iloc[-1]['high']); curr_low = float(df.iloc[-1]['low']); curr_vol = float(df.iloc[-1]['volume']) 
                curr_macd = float(df.iloc[-1].get('MACD', 0.0)); curr_signal = float(df.iloc[-1].get('Signal_Line', 0.0))
                ret_1m = float(df.iloc[-1].get('return', 0.0)); trade_amt = float(df.iloc[-1].get('Trade_Amount', (curr_price * curr_vol) / 1000000))
                curr_vol_energy = float(df.iloc[-1].get('Vol_Energy', 1.0)); curr_disp = float(df.iloc[-1].get('Disparity_20', 100.0))

                market_rows.append({'종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.2f}", '시가': f"{curr_open:,.2f}", '고가': f"{curr_high:,.2f}", '저가': f"{curr_low:,.2f}", '1분등락률': f"{ret_1m:.2f}", '거래대금': f"{trade_amt:,.1f}", '거래량에너지': f"{curr_vol_energy:.2f}", '이격도': f"{curr_disp:.2f}", '거래량': f"{curr_vol:,.0f}"})

                is_sell_all = False; is_sell_half = False; status_msg = ""; sell_qty = buy_qty
                strat_signal = self.mw.strategy_engine.check_trade_signal(df, code)

                if getattr(self, 'panic_mode', False): is_sell_all = True; status_msg = "🚨 긴급 전체 청산"
                elif is_imminent_close: is_sell_all = True; status_msg = "마감 임박 시장가 청산"
                elif is_safe_profit_close:
                    if profit_rate >= 0.3: is_sell_all = True; status_msg = "방어 마감 익절"
                    elif profit_rate > 0.0 and curr_macd < curr_signal: is_sell_all = True; status_msg = "추세꺾임 탈출"
                    elif profit_rate <= stop_rate: is_sell_all = True; status_msg = "기계적 손절"
                else:
                    if use_trailing and profit_rate >= ts_start and trail_drop_rate >= ts_gap: is_sell_all = True; status_msg = f"트레일링 스탑 ({ts_gap}% 하락)"
                    elif elapsed_mins >= max_hold_min: is_sell_all = True; status_msg = f"시간 제한 ({max_hold_min}분)"
                    elif strat_signal == "SELL" and profit_rate > 0.5: is_sell_all = True; status_msg = "매도 신호 (수익 보존)"
                    elif strat_signal == "SELL" and profit_rate <= stop_rate: is_sell_all = True; status_msg = "매도 신호 (손절)"
                    elif profit_rate >= target_rate and not half_sold: is_sell_half = True; sell_qty = max(1, int(buy_qty // 2)); status_msg = f"목표가({target_rate:.1f}%) 1차 익절"
                    elif profit_rate <= stop_rate: is_sell_all = True; status_msg = f"손절라인({stop_rate:.1f}%) 이탈"
                    elif profit_rate >= 1.5 and curr_macd < curr_signal: is_sell_all = True; status_msg = "데드크로스 탈출"

                if is_sell_half or is_sell_all:
                    if self.execute_guaranteed_sell(code, sell_qty, curr_price): 
                        if profit_rate < 0 and is_sell_all: self.loss_streak_cnt += 1
                        elif profit_rate > 0: self.loss_streak_cnt = 0 
                        
                        if is_sell_all: sold_codes.append(code) 
                        else:
                            self.mw.my_holdings[code]['qty'] -= sell_qty
                            self.mw.my_holdings[code]['half_sold'] = True
                        
                        realized_profit = (curr_price - buy_price) * sell_qty
                        self.cumulative_realized_profit += realized_profit
                        try: db_temp.set_shared_setting("ACCOUNT", "CUMULATIVE_REALIZED_PROFIT", str(self.cumulative_realized_profit))
                        except: pass
                        
                        my_cash += (curr_price * sell_qty); self.mw.last_known_cash = my_cash  
                        total_invested -= (buy_price * sell_qty); total_current_val -= (curr_price * sell_qty)

                        log_icon, log_color = ("🟢", "success") if profit_rate > 0 else ("🔴", "sell")
                        sell_msg = (f"{log_icon} [매도 완료] {stock_name} | {curr_price:,.2f}원 | 손익: {int(realized_profit):,}원 ({profit_rate:.2f}%)")
                        self.sig_log.emit(sell_msg, log_color) 
                        self.mw.send_kakao_msg(f"🔔 [주삐 매도]\n종목: {stock_name}\n수익률: {profit_rate:.2f}%\n손익: {int(realized_profit):,}원\n사유: {status_msg}") 
                        sell_type_str = '익절' if profit_rate > 0 else '손절'
                        self.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': sell_type_str, '주문가격': f"{curr_price:,.2f}", '주문수량': sell_qty, '체결수량': sell_qty, '주문시간': now.strftime("%Y-%m-%d %H:%M:%S"), '상태': '체결완료', '수익률': f"{profit_rate:.2f}%"})

                if not is_sell_all:
                    if code not in self.mw.my_holdings: continue 
                    cur_qty = self.mw.my_holdings[code]['qty'] if is_sell_half else buy_qty
                    account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': cur_qty, '평균매입가': f"{buy_price:,.2f}", '현재가': f"{curr_price:,.2f}", '평가손익금': f"{profit_amt:,.0f}", '수익률': f"{profit_rate:.2f}%", '주문가능금액': 0})
                
                ma5_val = float(df.iloc[-1].get('MA5', curr_price)); ma20_val = float(df.iloc[-1].get('MA20', curr_price)); rsi_val = float(df.iloc[-1].get('RSI', 50.0))
                strategy_rows.append({'종목코드': code, '종목명': stock_name, '상승확률': '-', 'MA_5': f"{ma5_val:.0f}", 'MA_20': f"{ma20_val:.0f}", 'RSI': f"{rsi_val:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': '보유중'})
                try: db_temp.update_realtime(code, curr_price, 0.0, "YES", status_msg)
                except: pass
            
            for code in sold_codes: 
                if code in self.mw.my_holdings: del self.mw.my_holdings[code]

        if not self.is_running: return # 🔥 [안전장치 4] 즉시 탈출

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
            
            briefing_msg = f"📊 [주삐 1분 브리핑] {now.strftime('%H:%M')}\n💎 총자산: {int(total_asset):,}원 | 누적수익: {int(realized_profit):+,}원"
            if len(self.mw.my_holdings) > 0: briefing_msg += f"\n[보유 주식]\n{stock_details_str.strip()}"
            else: briefing_msg += "\n[보유 주식] 없음"
            self.sig_log.emit(briefing_msg, "info")

        current_count = len(self.mw.my_holdings)
        try: max_stocks_setting = int(db_temp.get_shared_setting("TRADE", "MAX_STOCKS", "10"))
        except: max_stocks_setting = 10
        needed_count = max_stocks_setting - current_count 
        
        candidates = []; scanned_log_list = []; scan_targets = []

        if is_closing_phase or market_crash_mode: pass 
        elif self.loss_streak_cnt >= loss_limit_cnt:
            if now.minute % 5 == 0: self.sig_log.emit(f"🛑 {loss_limit_cnt}연패 리스크 관리! 신규 스캔 중단.", "error")
        elif not is_golden_time: pass 
        elif needed_count > 0 and not getattr(self, 'panic_mode', False):
            safe_holdings_values = list(self.mw.my_holdings.values())
            total_asset = my_cash + sum([info['price'] * info['qty'] for info in safe_holdings_values])
            
            # 🔥 [1분 보장 최적화] 대상 개수를 60개로 대폭 줄여서 스캔 속도를 10초 이내로 단축시킵니다!
            try: min_scan_stocks = int(db_temp.get_shared_setting("TRADE", "MIN_SCAN_STOCKS", "60"))
            except: min_scan_stocks = 60
            
            scan_targets = self.get_realtime_hot_stocks()

            for code in scan_targets:
                # 🔥 [안전장치 5] 검색 도중 중지 명령을 받으면 아무 신호도 쏘지 말고 조용히 함수를 빠져나갑니다 (return).
                if not self.is_running: 
                    self.sig_log.emit("🛑 신규 탐색 중단 (사용자 요청)", "warning")
                    return 

                # ✅ 여기를 0.4으로 수정하세요! (DB 설정이 없을 때의 기본값도 0.4으로 변경)
                try: scan_delay = float(db_temp.get_shared_setting("TRADE", "SCAN_DELAY", "0.4"))
                except: scan_delay = 0.4
                time.sleep(scan_delay)

                try: prob, curr_price, df_feat = self.mw.get_ai_probability(code)
                except Exception as e: continue
                if prob == -1.0 or curr_price <= 0 or np.isnan(curr_price): continue 

                is_pyramiding = False; current_invested_in_stock = 0.0; holding_qty = 0; holding_price = 0.0; max_allowed_for_stock = 0.0

                if code in self.mw.my_holdings:
                    holding_info = self.mw.my_holdings[code]; holding_price = holding_info['price']; holding_qty = holding_info['qty']
                    current_yield = (curr_price - holding_price) / holding_price * 100.0; current_invested_in_stock = holding_price * holding_qty
                    try: pyramiding_yield = float(db_temp.get_shared_setting("TRADE", "PYRAMIDING_YIELD", "3.0"))
                    except: pyramiding_yield = 3.0
                    try: max_invest_per_stock_pct = float(db_temp.get_shared_setting("TRADE", "MAX_INVEST_PER_STOCK", "30.0"))
                    except: max_invest_per_stock_pct = 30.0
                    max_allowed_for_stock = total_asset * (max_invest_per_stock_pct / 100.0)

                    if current_yield >= pyramiding_yield and current_invested_in_stock < max_allowed_for_stock:
                        is_pyramiding = True
                        if prob < 0.85: continue
                    else: continue 

                stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code) 
                scanned_log_list.append({'name': stock_name, 'prob': prob})
                
                try: ai_limit = float(db_temp.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
                except: ai_limit = 0.70
                
                if df_feat is not None and not df_feat.empty:
                    strat_signal = self.mw.strategy_engine.check_trade_signal(df_feat, code)
                    if 0.5 <= prob < ai_limit: self.sig_log.emit(f"🔎 [{stock_name}] AI 확신도 부족 ({prob*100:.1f}%)", "warning")
                    if strat_signal == "BUY" and prob < ai_limit: self.sig_log.emit(f"💡 [{stock_name}] 전략엔진 매수 추천이나, AI 미달", "info")

                    curr_open = float(df_feat.iloc[-1]['open']); curr_high = float(df_feat.iloc[-1]['high']); curr_low  = float(df_feat.iloc[-1]['low']); curr_vol  = float(df_feat.iloc[-1]['volume'])
                    ret_1m = float(df_feat.iloc[-1].get('return', 0.0)); trade_amt = float(df_feat.iloc[-1].get('Trade_Amount', (curr_price * curr_vol) / 1000000))
                    curr_vol_energy = float(df_feat.iloc[-1].get('Vol_Energy', 1.0)); curr_disp = float(df_feat.iloc[-1].get('Disparity_20', 100.0)); curr_macd = float(df_feat.iloc[-1].get('MACD', 0.0)); curr_rsi = float(df_feat.iloc[-1].get('RSI', 50.0)); ma5_val = float(df_feat.iloc[-1].get('MA5', curr_price)); ma20_val = float(df_feat.iloc[-1].get('MA20', curr_price)); curr_atr = float(df_feat.iloc[-1].get('ATR', 0.0))
                else: 
                    curr_open = curr_high = curr_low = curr_price; curr_vol = ret_1m = trade_amt = 0.0; curr_disp = 100.0; curr_vol_energy = 1.0; curr_macd = 0.0; curr_rsi = 50.0; ma5_val = curr_price; ma20_val = curr_price; curr_atr = 0.0
                    
                now_time = datetime.now().strftime('%H:%M:%S')
                market_rows.append({'시간': now_time, '종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.2f}", '시가': f"{curr_open:,.2f}", '고가': f"{curr_high:,.2f}", '저가': f"{curr_low:,.2f}", '1분등락률': f"{ret_1m:.2f}", '거래대금': f"{trade_amt:,.1f}", '거래량에너지': f"{curr_vol_energy:.2f}", '이격도': f"{curr_disp:.2f}", '거래량': f"{curr_vol:,.0f}"})
                if df_feat is not None: strategy_rows.append({'시간': now_time, '종목코드': code, '종목명': stock_name, '상승확률': f"{prob*100:.1f}%", 'MA_5': f"{ma5_val:.0f}", 'MA_20': f"{ma20_val:.0f}", 'RSI': f"{curr_rsi:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': "BUY 🟢" if prob >= ai_limit else "WAIT 🟡"})
                
                if prob >= ai_limit: candidates.append({'code': code, 'prob': prob, 'price': curr_price, 'stock_name': stock_name, 'is_pyramiding': is_pyramiding, 'current_invested': current_invested_in_stock, 'holding_qty': holding_qty, 'holding_price': holding_price, 'max_allowed': max_allowed_for_stock, 'atr': curr_atr})
                try: db_temp.update_realtime(code, curr_price, prob*100, "NO", "탐색 중...")
                except: pass

                if len(scanned_log_list) >= min_scan_stocks: break
            
            if not self.is_running: return # 🔥 [안전장치 6] 스캔 직후 체크

            if scanned_log_list:
                scanned_log_list = sorted(scanned_log_list, key=lambda x: x['prob'], reverse=True)
                top_list = scanned_log_list[:3] 
                top_msg = ", ".join([f"{x['name']}({x['prob']*100:.1f}%)" for x in top_list])
                try: ai_limit_display = float(db_temp.get_shared_setting("AI", "THRESHOLD", "70.0"))
                except: ai_limit_display = 70.0
                
                actual_scanned_count = len(scanned_log_list)
                if candidates: self.sig_log.emit(f"🔥 시장 주도주 {actual_scanned_count}개 분석. TOP 3: {top_msg} 👉 기준 통과! 매수 진입", "send")
                else: self.sig_log.emit(f"🔎 시장 주도주 {actual_scanned_count}개 분석. TOP 3: {top_msg} 👉 미달", "warning")

            if candidates:
                candidates = sorted(candidates, key=lambda x: x['prob'], reverse=True)
                for i in range(min(needed_count, len(candidates))):
                    if not self.is_running: return # 🔥 [안전장치 7] 매수 진입 직전 체크

                    cand = candidates[i]; code = cand['code']; prob = cand['prob']; curr_price = cand['price']; stock_name = cand['stock_name']; is_pyramiding = cand['is_pyramiding']

                    try: use_funds_percent = float(db_temp.get_shared_setting("TRADE", "USE_FUNDS_PERCENT", "100"))
                    except: use_funds_percent = 100.0

                    allowed_total_budget = total_asset * (use_funds_percent / 100.0); available_trading_budget = allowed_total_budget - total_invested
                    if available_trading_budget <= 0: continue

                    if is_pyramiding:
                        try: pyramiding_rate = float(db_temp.get_shared_setting("TRADE", "PYRAMIDING_RATE", "50.0"))
                        except: pyramiding_rate = 50.0
                        target_budget = cand['current_invested'] * (pyramiding_rate / 100.0); max_remaining_for_stock = cand['max_allowed'] - cand['current_invested']; target_budget = min(target_budget, max_remaining_for_stock)
                    else:
                        if prob >= 0.85: weight = 0.20     
                        elif prob >= 0.70: weight = 0.10   
                        else: weight = 0.05                
                        base_target_budget = float(total_asset * weight)
                        try: atr_high_limit = float(db_temp.get_shared_setting("TRADE", "ATR_HIGH_LIMIT", "5.0")); atr_high_ratio = float(db_temp.get_shared_setting("TRADE", "ATR_HIGH_RATIO", "50.0")) / 100.0; atr_mid_limit  = float(db_temp.get_shared_setting("TRADE", "ATR_MID_LIMIT", "2.5")); atr_mid_ratio  = float(db_temp.get_shared_setting("TRADE", "ATR_MID_RATIO", "70.0")) / 100.0
                        except: atr_high_limit, atr_high_ratio = 5.0, 0.5; atr_mid_limit, atr_mid_ratio = 2.5, 0.7
                            
                        current_atr = cand['atr']; volatility_pct = (current_atr / curr_price) * 100 if curr_price > 0 else 0
                        if volatility_pct >= atr_high_limit: target_budget = base_target_budget * atr_high_ratio; self.sig_log.emit(f"🚨 {stock_name} 변동성 극심({volatility_pct:.1f}%)! 매수 축소", "warning")
                        elif volatility_pct >= atr_mid_limit: target_budget = base_target_budget * atr_mid_ratio; self.sig_log.emit(f"🛡️ {stock_name} 변동성 높음({volatility_pct:.1f}%). 매수 축소", "warning")
                        else: target_budget = base_target_budget

                    budget = min(target_budget, available_trading_budget); buy_qty = int(budget // curr_price) 
                    if buy_qty * curr_price > my_cash: buy_qty = int(my_cash // curr_price)
                    if buy_qty == 0: continue

                    if buy_qty > 0 and self.execute_guaranteed_buy(code, buy_qty):
                        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        if is_pyramiding:
                            old_qty = cand['holding_qty']; old_price = cand['holding_price']; new_total_qty = old_qty + buy_qty; new_avg_price = ((old_price * old_qty) + (curr_price * buy_qty)) / new_total_qty
                            self.mw.my_holdings[code]['price'] = new_avg_price; self.mw.my_holdings[code]['qty'] = new_total_qty; self.mw.my_holdings[code]['high_watermark'] = max(self.mw.my_holdings[code]['high_watermark'], curr_price)
                            self.sig_log.emit(f"🔥 [불타기 성공] {stock_name} | 추가: {buy_qty}주 | AI: {prob*100:.1f}%", "buy") 
                        else:
                            self.mw.my_holdings[code] = {'price': curr_price, 'qty': buy_qty, 'high_watermark': curr_price, 'buy_time': now, 'half_sold': False}
                            self.sig_log.emit(f"🔵 [매수 체결] {stock_name} | {curr_price:,.2f}원 | {buy_qty}주 | AI: {prob*100:.1f}%", "buy") 

                        my_cash -= (curr_price * buy_qty); total_invested += (curr_price * buy_qty)
                        self.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': '매수' if not is_pyramiding else '불타기', '주문가격': f"{curr_price:,.2f}", '주문수량': buy_qty, '체결수량': buy_qty, '주문시간': now, '상태': '체결완료', '수익률': '0.00%'})
                        now_time = datetime.now().strftime('%H:%M:%S')
                        account_rows.append({'시간': now_time, '종목코드': code, '종목명': stock_name, '보유수량': new_total_qty if is_pyramiding else buy_qty, '평균매입가': f"{new_avg_price if is_pyramiding else curr_price:,.2f}", '현재가': f"{curr_price:,.2f}", '평가손익금': "0", '수익률': "0.00%", '주문가능금액': 0})
                        if account_rows: account_rows[0]['주문가능금액'] = f"{my_cash:,}" 
                        
                        acc_cols = ['시간', '종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','주문가능금액']
                        temp_df = pd.DataFrame(account_rows)
                        for c in acc_cols:
                            if c not in temp_df.columns: temp_df[c] = ""
                        self.sig_account_df.emit(temp_df[acc_cols].copy()); self.sig_sync_cs.emit()

        if not self.is_running: return # 🔥 [안전장치 8] 표를 렌더링하기 전에도 죽었는지 묻습니다.

        # =========================================================================
        # 🔥 실시간 데이터 보존 (마지막까지 살아서 여기까지 온 경우에만 실행됩니다!)
        # =========================================================================
        if not hasattr(self.mw, 'accumulated_market'): self.mw.accumulated_market = {}
        if not hasattr(self.mw, 'accumulated_strategy'): self.mw.accumulated_strategy = {}
        if not hasattr(self.mw, 'accumulated_account'): self.mw.accumulated_account = {}

        for row in market_rows: self.mw.accumulated_market[row['종목코드']] = row
        for row in strategy_rows: self.mw.accumulated_strategy[row['종목코드']] = row
        for row in account_rows: self.mw.accumulated_account[row['종목코드']] = row

        for code in list(self.mw.accumulated_account.keys()):
            if code not in self.mw.my_holdings:
                self.mw.accumulated_account[code]['보유수량'] = "0 (매도됨)"; self.mw.accumulated_account[code]['평가손익금'] = "매도완료"
                self.mw.accumulated_account[code]['현재가'] = "-"; self.mw.accumulated_account[code]['수익률'] = "-"

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
        self.sig_safe_log.connect(self._safe_append_log_sync)

        self.db = JubbyDB_Manager()
        self.db.cleanup_old_data() 
        
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            conn.execute("DELETE FROM MarketStatus"); conn.execute("DELETE FROM AccountStatus")
            conn.execute("DELETE FROM StrategyStatus"); conn.execute("DELETE FROM TradeHistory") 
            conn.commit(); conn.close()
            self.db.insert_log("INFO", "🧹 [시스템] 이전 실시간 DB 데이터를 성공적으로 초기화했습니다.")
        except Exception as e:
            if hasattr(self, 'db'): self.db.insert_log("WARNING", f"⚠️ DB 실시간 데이터 초기화 실패: {e}")
        
        db_mode = self.db.get_shared_setting("SYSTEM", "MARKET_MODE", "DOMESTIC")
        SystemConfig.MARKET_MODE = db_mode
        self.db.insert_log("INFO", f"⚙️ 시스템 초기화 완료 (모드: {db_mode})")

        self.initUI() 
        
        self.output_logger = OutputLogger()
        self.output_logger.emit_log.connect(self.sys_print_to_log)
        sys.stdout = self.output_logger
        sys.stderr = self.output_logger 

        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            query = f"SELECT symbol, symbol_name FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
            df_dict = pd.read_sql(query, conn)
            conn.close()
            
            if SystemConfig.MARKET_MODE == "DOMESTIC": self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str).str.zfill(6), df_dict['symbol_name']))
            else: self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str), df_dict['symbol_name']))
                
            if not self.DYNAMIC_STOCK_DICT: raise ValueError("DB 명단이 비어 있습니다.")
            self.add_log(f"📖 DB에서 {len(self.DYNAMIC_STOCK_DICT)}개 종목 명단을 불러왔습니다!", "info")
        except Exception as e:
            self.add_log(f"⚠️ DB 명단 로드 실패: {e}", "warning")
            self.DYNAMIC_STOCK_DICT = {"005930": "삼성전자"}

        self.api_manager = KIS_Manager(ui_main=self)
        self.api_manager.start_api() 
        self.strategy_engine = JubbyStrategy(log_callback=self.add_log)

        self.my_holdings = {}; self.last_known_cash = 0 
        
        self.trade_worker = AutoTradeWorker(main_window=self) 
        self.trade_worker.sig_log.connect(self.add_log)                                
        self.trade_worker.sig_account_df.connect(self.update_account_table_slot)        
        self.trade_worker.sig_strategy_df.connect(self.update_strategy_table_slot)     
        self.trade_worker.sig_sync_cs.connect(self.btnDataSendClickEvent)
        self.trade_worker.sig_order_append.connect(self.append_order_table_slot)            
        self.trade_worker.sig_market_df.connect(self.update_market_table_slot)   
        self.trade_worker.sig_panic_done.connect(self.panic_sell_done_slot)
        self.trade_worker.finished.connect(self.check_worker_stopped)

        QtCore.QTimer.singleShot(3000, self.load_real_holdings) 
        self.kakao_timer = QtCore.QTimer(self); self.kakao_timer.timeout.connect(self.auto_status_report); self.kakao_timer.start(1000 * 60 * 60) 

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
        try:
            code = order_info.get('종목코드', ''); o_type = "BUY" if "BUY" in str(order_info.get('주문종류', '')).upper() else "SELL"
            price = float(str(order_info.get('주문가격', '0')).replace(',', '')); qty = int(order_info.get('주문수량', 0)); y_rate = float(str(order_info.get('수익률', '0')).replace('%', ''))
            self.db.insert_trade_history(code, o_type, price, qty, y_rate, 0.0)
        except Exception: pass

        ord_cols = ['종목코드','종목명','주문종류','주문가격','주문수량','체결수량','주문시간','상태','수익률']
        new_row = pd.DataFrame([order_info])
        for c in ord_cols:
            if c not in new_row.columns: new_row[c] = ""
        new_row = new_row[ord_cols]

        if TradeData.order.df.empty: TradeData.order.df = new_row
        else: TradeData.order.df = pd.concat([TradeData.order.df, new_row], ignore_index=True)
        if len(TradeData.order.df) > 500: TradeData.order.df = TradeData.order.df.iloc[-500:].reset_index(drop=True)
        
        row_idx = self.tbOrder.rowCount(); self.tbOrder.insertRow(row_idx) 
        for col_idx, key in enumerate(TradeData.order.df.columns):
            item = QtWidgets.QTableWidgetItem(str(order_info.get(key, ''))); item.setTextAlignment(QtCore.Qt.AlignCenter); self.tbOrder.setItem(row_idx, col_idx, item)
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
                strategy_list.append({"symbol": sym, "symbol_name": str(row.get("종목명", "")), "ma_5": float(clean_num(row.get("MA_5", "0"))), "ma_20": float(clean_num(row.get("MA_20", "0"))), "RSI": float(clean_num(row.get("RSI", "0"))), "macd": float(clean_num(row.get("MACD", "0"))), "signal": sig})
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
        act_panic = menu.addAction("🛑 긴급 전체 청산 및 자동매매 종료 (Panic Sell)")
        menu.addSeparator() 
        act_save_log = menu.addAction("💾 현재 로그 텍스트로 저장 (Save Log)") 

        action = menu.exec_(pos)
        
        if action == act_toggle_mode: self.toggle_market_mode() 
        elif action == act_collect: self.start_data_collector()
        elif action == act_train: self.start_ai_trainer()
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
        if not hasattr(self, 'trade_worker') or not self.trade_worker.is_running: return
        if len(self.my_holdings) == 0: self.btnAutoTradingSwitch(); return

        stock_names = [self.DYNAMIC_STOCK_DICT.get(c, c) for c in self.my_holdings.keys()]
        msg = f"🚨 [긴급 전체 청산 발동]\n전체 시장가 매도 진행!\n대상: {', '.join(stock_names)}"
        self.add_log(msg, "error"); self.send_kakao_msg(msg)
        self.trade_worker.panic_mode = True 

    @QtCore.pyqtSlot()
    def panic_sell_done_slot(self):
        self.is_stopping = False 
        self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
        self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")

    def btnAutoTradingSwitch(self):
        if getattr(self, 'is_stopping', False): return
            
        if not self.trade_worker.is_running: 
            try:
                conn = self.db._get_connection(self.db.shared_db_path)
                conn.execute("DELETE FROM TradeHistory"); conn.commit(); conn.close()
                TradeData.order.df = pd.DataFrame(columns=['종목코드','종목명','주문종류','주문가격','주문수량','체결수량','주문시간','상태','수익률'])
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
            
            if hasattr(self, 'trade_worker'):
                self.trade_worker.is_running = False # 이 플래그로 인해 백그라운드 스레드는 모든 작업을 버리고 바로 탈출하게 됩니다!

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
        if hasattr(self, '_isDragging') and self._isDragging: self.move(event.globalPos() - self._startPos)
    def mouseReleaseEvent(self, event): self._isDragging = False

    def emergency_sell_event(self):
        try:
            selected_ranges = self.tbAccount.selectedRanges() 
            if not selected_ranges: return
            row = selected_ranges[0].topRow(); item = self.tbAccount.item(row, 0)
            if item is None: return
            code = item.text().strip() 
            if code == "-" or not code: return
            if code in self.my_holdings:
                qty = self.my_holdings[code]['qty']; stock_name = self.DYNAMIC_STOCK_DICT.get(code, code)
                if self.api_manager.sell(code, qty):
                    del self.my_holdings[code]; self.tbAccount.removeRow(row)
                    if hasattr(self, 'trade_worker'): self.trade_worker.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': '비상(SELL_LOSS)', '주문가격': '시장가', '주문수량': qty, '체결수량': qty, '주문시간': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '상태': '비상청산완료', '수익률': "0.00%"})
        except Exception: pass

    def get_ai_probability(self, code):
        df = self.api_manager.fetch_minute_data(code) 
        if df is None or len(df) < 26: return 0.0, 0, None
        df = self.strategy_engine.calculate_indicators(df)
        curr_price = df.iloc[-1]['close']; prob = 0.0
        if self.strategy_engine.ai_model is not None:
            features = self.strategy_engine.get_ai_features(df)
            if features is not None: prob = self.strategy_engine.ai_model.predict_proba(features)[0][1]
        return prob, curr_price, df

    @QtCore.pyqtSlot(object) 
    def update_account_table_slot(self, df): self.update_table(self.tbAccount, df)
    @QtCore.pyqtSlot(object) 
    def update_strategy_table_slot(self, df): self.update_table(self.tbStrategy, df)

    @QtCore.pyqtSlot(str, str) 
    def add_log(self, text, log_type="info"):
        self.sig_safe_log.emit(text, log_type)

    @QtCore.pyqtSlot(str, str)
    def _safe_append_log_sync(self, text, log_type):
        color = {"info": "white", "success": "lime", "warning": "yellow", "error": "red", "send": "cyan", "recv": "orange", "buy": "#4B9CFF", "sell": "#FF4B4B"}.get(log_type, "white")
        formatted_text = text.replace('\n', '<br>&nbsp;&nbsp;&nbsp;&nbsp;')
        html_msg = f'<span style="color:{color}"><b>{datetime.now().strftime("[%H:%M:%S]")}</b> {formatted_text}</span>'
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
        
    def btnDataClearClickEvent(self): 
        self.tbAccount.setRowCount(0); self.tbStrategy.setRowCount(0); self.tbOrder.setRowCount(0); self.tbMarket.setRowCount(0)

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    mainWindow = FormMain()
    mainWindow.show()
    sys.exit(app.exec_())