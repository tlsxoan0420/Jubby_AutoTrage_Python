# =====================================================================
# 📦 [1단계] 마법의 도구 상자 열기 (필요한 부품들을 가져옵니다)
# =====================================================================
import sys
import os                  
# 🔥 [핵심 추가] AI 라이브러리와 화면(PyQt5)이 동시에 작업을 처리하려다 
# 컴퓨터가 뻗어버리는(팅기는) 현상을 억지로 막아주는 마법의 설정입니다.
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True' 

import time                
import random              
import joblib              
import pandas as pd        
import numpy as np         
import requests # 카카오톡으로 주삐의 알림을 보내기 위한 통신 도구
from datetime import datetime 
from PyQt5 import QtWidgets, uic, QtCore, QtGui  
from PyQt5.QtCore import Qt, QThread, pyqtSignal 

from COMMON.Flag import TradeData            
from COMMON.KIS_Manager import KIS_Manager   

# 💡 [TCP 소켓 통신 삭제 완료] - TcpJsonClient 및 TCP 관련 흔적 100% 영구 제거!
from COMMON.Flag import SystemConfig
from COMMON.DB_Manager import JubbyDB_Manager

# 🛠️ AI 뇌를 활용해 언제 사고 팔지 판단하는 핵심 전략 엔진
from TRADE.Argorism.Strategy import JubbyStrategy 

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

# =========================================================================
# [ EXE 파일 변환 시 리소스(UI 파일, 이미지 등) 절대 경로를 찾아주는 함수 ]
# =========================================================================
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# =====================================================================
# 🖥️ 파이썬 검은 창(터미널)에 뜨는 글씨를 UI 화면으로 끌어오는 도구
# =====================================================================
class OutputLogger(QtCore.QObject):
    emit_log = QtCore.pyqtSignal(str)
    def write(self, text):
        if text.strip(): self.emit_log.emit(text.strip())
    def flush(self): pass


# =====================================================================
# 📡 [일꾼 1호] 종목 수집기 (유령 종목 제외한 전부 싹쓸이 수집 모드)
# =====================================================================
class DataCollectorWorker(QThread):
    sig_log = pyqtSignal(str, str)
    
    def __init__(self, app_key, app_secret, account_no, is_mock):
        super().__init__()
        self.real_app_key = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
        self.real_app_secret = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
        self.account_no = account_no
        self.is_mock = False  

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
                print(f"▶️ [수집기] 전체 종목 수 수신 완료: {len(df_market)}개", flush=True)

                if df_market is None or df_market.empty:
                    df_market = pd.concat([fdr.StockListing('KOSPI'), fdr.StockListing('KOSDAQ')], ignore_index=True)

                for col in ['Close', 'Amount', 'Volume']:
                    if col in df_market.columns:
                        df_market[col] = pd.to_numeric(df_market[col].astype(str).str.replace(r'[^0-9.]', '', regex=True), errors='coerce').fillna(0)

                top_df = df_market[(df_market['Close'] >= 1000) & (df_market['Amount'] > 0)]
                print(f"▶️ [수집기] 유령 종목 제외 후 남은 개수(전부 수집): {len(top_df)}개", flush=True)

                code_col = 'Code' if 'Code' in top_df.columns else 'Symbol'
                stock_list = top_df[code_col].astype(str).str.zfill(6).tolist()
                name_list = top_df['Name'].tolist()

            elif SystemConfig.MARKET_MODE == "OVERSEAS":
                self.emit_log("📡 미국 나스닥(NASDAQ) 정상 종목 전체 추출 중...", "info")
                df_market = fdr.StockListing('NASDAQ')
                top_df = df_market.head(3000) 
                stock_list = top_df['Symbol'].astype(str).tolist()
                name_list = top_df['Name'].tolist()
                print(f"▶️ [수집기] 미국 나스닥 추출 완료", flush=True)
                
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
            else:
                print("🚨 [수집기] 조건에 맞는 종목을 하나도 찾지 못했습니다.", flush=True)
                return

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
# 🤖 [일꾼 3호] 매매 관리자 (🔥 팅김 원인 100% 격리 버전)
# =====================================================================
class AutoTradeWorker(QThread):
    sig_log = pyqtSignal(str, str); sig_account_df = pyqtSignal(object)        
    sig_strategy_df = pyqtSignal(object); sig_market_df = pyqtSignal(object)         
    sig_sync_cs = pyqtSignal(); sig_order_append = pyqtSignal(dict)        
    sig_panic_done = pyqtSignal()

    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window; self.is_running = False; self.cumulative_realized_profit = 0 
        self.panic_mode = False; self.closing_mode_notified = False; self.imminent_notified = False
        
    def run(self):
        self.is_running = True
        try: JubbyDB_Manager().update_system_status('TRADER', '감시망 가동 중 🟢', 100)
        except: pass
        
        while self.is_running:
            try: self.process_trading() 
            except Exception as e: self.sig_log.emit(f"🚨 매매 분석 중 일시적 오류 발생 (스레드 복구됨): {e}", "error")
                
            for _ in range(120):
                if not self.is_running: break 
                time.sleep(0.5)
                
        # 🔥 스레드가 종료될 때는 조용히 루프만 빠져나옵니다. 
        # (이때 통신이나 DB를 건드리면 Segfault로 튕김)
        self.is_running = False

    def execute_guaranteed_sell(self, code, qty, current_price):
        stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
        max_retries = 10
        for i in range(max_retries):
            if self.mw.api_manager.sell(code, qty):
                if i > 0: self.sig_log.emit(f"✅ [{stock_name}] {i}번의 끈질긴 재시도 끝에 매도 주문 접수 완료!", "success")
                return True
            self.sig_log.emit(f"⚠️ [{stock_name}] 매도 실패! 즉시 재시도합니다... ({i+1}/{max_retries})", "warning")
            time.sleep(1.5) 
        self.sig_log.emit(f"🚨 [{stock_name}] 매도 {max_retries}회 연속 실패! 서버 장애 또는 미체결.", "error")
        self.mw.send_kakao_msg(f"🚨 [주삐 긴급 SOS]\n종목: {stock_name}\n매도 주문이 {max_retries}회 연속 튕겨 나갔습니다!")
        return False

    def get_realtime_hot_stocks(self, limit=100):
        import requests, random
        pool = list(self.mw.DYNAMIC_STOCK_DICT.keys())

        if SystemConfig.MARKET_MODE == "DOMESTIC":
            try:
                api = self.mw.api_manager.api
                url = f"{api.base_url}/uapi/domestic-stock/v1/quotations/volume-rank"
                headers = {
                    "content-type": "application/json",
                    "authorization": f"Bearer {api.access_token}",
                    "appkey": api.app_key,
                    "appsecret": api.app_secret,
                    "tr_id": "FHPST01710000",
                    "custtype": "P"
                }
                params = {
                    "FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "20171",
                    "FID_INPUT_ISCD": "0000", "FID_DIV_CLS_CODE": "0", "FID_BLNG_CLS_CODE": "0",
                    "FID_TRGT_CLS_CODE": "111111111", "FID_TRGT_EXLS_CLS_CODE": "0000000000",
                    "FID_INPUT_PRICE_1": "1000", "FID_INPUT_PRICE_2": "0",
                    "FID_VOL_CNT": "0", "FID_INPUT_DATE_1": ""
                }
                res = requests.get(url, headers=headers, params=params, timeout=3)
                if res.status_code == 200 and res.json().get('rt_cd') == '0':
                    data = res.json().get('output', [])
                    hot_list = []
                    for item in data:
                        code = item.get('mksc_shrn_iscd') or item.get('stck_shrn_iscd')
                        if code and code in pool:
                            hot_list.append(code)
                            if len(hot_list) >= limit: 
                                break
                    if hot_list: return hot_list
            except Exception as e:
                self.sig_log.emit(f"🔥 실시간 랭킹 스캐너 일시적 통신 오류: {e}", "warning")

        return random.sample(pool, min(limit, len(pool))) if pool else []

    def process_trading(self):
        now = datetime.now() 
        api_cash = self.mw.api_manager.get_balance()
        my_cash = api_cash if api_cash is not None else getattr(self.mw, 'last_known_cash', 0)
        self.mw.last_known_cash = my_cash; cash_str = f"{my_cash:,}" 

        MAX_STOCKS = 10; SCAN_POOL = list(self.mw.DYNAMIC_STOCK_DICT.keys()) 
        account_rows = []; market_rows = []; strategy_rows = [] 
        total_invested = 0; total_current_val = 0  

        is_closing_phase = False; is_safe_profit_close = False; is_imminent_close = False

        if SystemConfig.MARKET_MODE == "DOMESTIC":
            if now.hour == 15 and now.minute >= 0: is_closing_phase = True
            if now.hour == 15 and 0 <= now.minute < 10: is_safe_profit_close = True
            if now.hour == 15 and now.minute >= 10: is_imminent_close = True
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            if now.hour == 4 and now.minute >= 30: is_closing_phase = True
            if now.hour == 4 and 30 <= now.minute < 45: is_safe_profit_close = True
            if now.hour == 4 and now.minute >= 45: is_imminent_close = True
            if now.hour == 5: is_imminent_close = True 
        elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
            if now.hour == 5 and now.minute >= 30: is_closing_phase = True
            if now.hour == 5 and 30 <= now.minute < 45: is_safe_profit_close = True
            if now.hour == 5 and now.minute >= 45: is_imminent_close = True
            if now.hour == 6: is_imminent_close = True 

        if is_imminent_close:
            if not getattr(self, 'imminent_notified', False):
                self.sig_log.emit(f"⚠️ [마감 임박] 장 종료가 다가옵니다! 보유 중인 모든 종목을 시장가로 강제 청산합니다!", "error")
                self.imminent_notified = True
        elif not is_closing_phase: self.imminent_notified = False

        if is_closing_phase and not is_imminent_close:
            if not getattr(self, 'closing_mode_notified', False):
                self.sig_log.emit(f"⏰ [마감 모드 돌입] 장 마감 대기. 신규 매수를 중지하고 안전 익절/손절만 진행합니다.", "warning")
                self.closing_mode_notified = True
        elif not is_closing_phase: self.closing_mode_notified = False

        market_crash_mode = False
        market_ticker = "069500" if SystemConfig.MARKET_MODE == "DOMESTIC" else ("QQQ" if SystemConfig.MARKET_MODE == "OVERSEAS" else "NQM26")
        market_etf = self.mw.api_manager.fetch_minute_data(market_ticker)
        
        db_temp = JubbyDB_Manager() 
        
        if market_etf is not None and len(market_etf) > 1:
            etf_now = market_etf.iloc[-1]['close']; etf_prev = market_etf.iloc[-2]['close']
            self.mw.strategy_engine.market_return_1m = ((etf_now - etf_prev) / etf_prev) * 100.0
            etf_drop = ((etf_now - market_etf.iloc[0]['open']) / market_etf.iloc[0]['open']) * 100
            try: crash_limit = float(db_temp.get_shared_setting("TRADE", "CRASH_LIMIT", "-1.5"))
            except: crash_limit = -1.5
            
            if etf_drop <= crash_limit: 
                market_crash_mode = True
                self.sig_log.emit(f"⚠️ [시장 경고] {market_ticker} 지수가 급락 중입니다. 매수를 차단합니다.", "warning")

        stock_details_str = ""
        current_holdings = list(self.mw.my_holdings.items())

        if len(current_holdings) > 0: 
            sold_codes = []; hold_status_list = [] 
            for code, info in current_holdings: 
                if code not in self.mw.my_holdings: continue 

                buy_price = info['price']; buy_qty = info['qty']; stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
                high_watermark = info.get('high_watermark', buy_price); buy_time = info.get('buy_time', now); half_sold = info.get('half_sold', False) 

                df = self.mw.api_manager.fetch_minute_data(code)
                if df is None or len(df) < 30: continue 
                
                df = self.mw.strategy_engine.calculate_indicators(df)
                curr_price = float(df.iloc[-1]['close']) 
                profit_rate = ((curr_price - buy_price) / buy_price) * 100 
                profit_amt = (curr_price - buy_price) * buy_qty
                
                stock_details_str += f"  🔸 {stock_name}: 매입 {buy_price:,.2f} -> 현재 {curr_price:,.2f} ({profit_rate:+.2f}%)\n"
                
                target_price, stop_price = self.mw.strategy_engine.get_dynamic_exit_prices(df, buy_price)
                target_rate = ((target_price - buy_price) / buy_price) * 100
                stop_rate = ((stop_price - buy_price) / buy_price) * 100

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

                if getattr(self, 'panic_mode', False): is_sell_all = True; status_msg = "🚨 긴급 전체 청산 (사용자 요청)"
                elif is_imminent_close: is_sell_all = True; status_msg = "마감 임박 묻지마 시장가 청산"
                elif is_safe_profit_close:
                    if profit_rate >= 0.3: is_sell_all = True; status_msg = "수수료 방어 마감 익절"
                    elif profit_rate > 0.0 and curr_macd < curr_signal: is_sell_all = True; status_msg = "마감 전 추세꺾임 탈출"
                    elif profit_rate <= stop_rate: is_sell_all = True; status_msg = "마감 전 기계적 손절"
                else:
                    if strat_signal == "SELL" and profit_rate > 0.5: is_sell_all = True; status_msg = "전략엔진 매도 신호 (수익 보존)"
                    elif strat_signal == "SELL" and profit_rate <= stop_rate: is_sell_all = True; status_msg = "전략엔진 매도 신호 (리스크 최소화)"
                    elif profit_rate >= target_rate and not half_sold: is_sell_half = True; sell_qty = max(1, int(buy_qty // 2)); status_msg = f"목표가({target_rate:.1f}%) 도달 1차 익절"
                    elif half_sold and trail_drop_rate >= 0.5: is_sell_all = True; status_msg = "트레일링 스탑 (나머지 전량 익절)"
                    elif profit_rate <= stop_rate: is_sell_all = True; status_msg = f"손절라인({stop_rate:.1f}%) 이탈"
                    elif profit_rate >= 1.5 and curr_macd < curr_signal: is_sell_all = True; status_msg = "데드크로스 수익보존 탈출"
                    elif elapsed_mins >= 45 and (-1.0 <= profit_rate <= 1.0): is_sell_all = True; status_msg = f"타임아웃 ({int(elapsed_mins)}분 횡보) 탈출"

                if is_sell_half or is_sell_all:
                    if getattr(self, 'panic_mode', False): self.sig_log.emit(f"🔥 [긴급청산 진행] 👉 '{stock_name}' {sell_qty}주 전량 매도 프로세스 진입...", "warning")

                    if self.execute_guaranteed_sell(code, sell_qty, curr_price): 
                        if is_sell_all: sold_codes.append(code) 
                        else: 
                            self.mw.my_holdings[code]['qty'] -= sell_qty
                            self.mw.my_holdings[code]['half_sold'] = True
                        
                        realized_profit = (curr_price - buy_price) * sell_qty
                        self.cumulative_realized_profit += realized_profit
                        my_cash += (curr_price * sell_qty); self.mw.last_known_cash = my_cash  
                        total_invested -= (buy_price * sell_qty); total_current_val -= (curr_price * sell_qty)

                        log_icon, log_color = ("🟢", "success") if profit_rate > 0 else ("🔴", "sell")
                        sell_msg = (f"{log_icon} [매도 체결 완료] {stock_name} | 매도가: {curr_price:,.2f} | 수량: {sell_qty}주 | 손익: {int(realized_profit):,}원 ({profit_rate:.2f}%) | 사유: {status_msg}")
                        self.sig_log.emit(sell_msg, log_color) 
                        self.mw.send_kakao_msg(f"🔔 [주삐 매도 알림]\n종목: {stock_name}\n수익률: {profit_rate:.2f}%\n손익: {int(realized_profit):,}원\n사유: {status_msg}") 
                        
                        sell_type_str = '익절(SELL_PROFIT)' if profit_rate > 0 else '손절(SELL_LOSS)'
                        self.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': sell_type_str, '주문가격': f"{curr_price:,.2f}", '주문수량': sell_qty, '체결수량': sell_qty, '주문시간': now.strftime("%Y-%m-%d %H:%M:%S"), '상태': '체결완료', '수익률': f"{profit_rate:.2f}%"})

                if not is_sell_all:
                    if code not in self.mw.my_holdings: continue 
                    cur_qty = self.mw.my_holdings[code]['qty'] if is_sell_half else buy_qty
                    account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': cur_qty, '평균매입가': f"{buy_price:,.2f}", '현재가': f"{curr_price:,.2f}", '평가손익금': f"{profit_amt:,.0f}", '수익률': f"{profit_rate:.2f}%", '주문가능금액': 0})
                
                ma5_val = float(df.iloc[-1].get('MA5', curr_price)); ma20_val = float(df.iloc[-1].get('MA20', curr_price))
                rsi_val = float(df.iloc[-1].get('RSI', 50.0))
                strategy_rows.append({'종목코드': code, '종목명': stock_name, '상승확률': '-', 'MA_5': f"{ma5_val:.0f}", 'MA_20': f"{ma20_val:.0f}", 'RSI': f"{rsi_val:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': '보유중'})
                
                try: db_temp.update_realtime(code, curr_price, 0.0, "YES", status_msg)
                except: pass
            
            for code in sold_codes: 
                if code in self.mw.my_holdings: del self.mw.my_holdings[code]

        if getattr(self, 'panic_mode', False):
            if len(self.mw.my_holdings) > 0:
                remain_stocks = [self.mw.DYNAMIC_STOCK_DICT.get(c, c) for c in list(self.mw.my_holdings.keys())]
                panic_msg = f"🚨 [긴급청산 중간 보고]\n미체결 잔여 종목: {', '.join(remain_stocks)}"
                self.sig_log.emit(panic_msg, "error"); self.mw.send_kakao_msg(panic_msg) 
        else:
            total_unrealized_profit = total_current_val - total_invested 
            total_asset = my_cash + total_current_val 
            realized_profit = getattr(self, 'cumulative_realized_profit', 0) 
            
            briefing_msg = f"📊 [주삐 1분 브리핑] {now.strftime('%H:%M')}\n💎 추정 총자산: {int(total_asset):,}원\n💰 누적 실현손익: {int(realized_profit):+,}원\n💸 보유주식 평가손익: {int(total_unrealized_profit):+,}원"
            if len(self.mw.my_holdings) > 0:
                briefing_msg += f"\n\n[현재 보유 주식 상세 목록]\n{stock_details_str.strip()}"
                self.sig_log.emit(briefing_msg, "info")
            else:
                if is_closing_phase: briefing_msg += "\n\n[현재 보유 주식 상세 목록]\n보유 종목 없음 (⏰ 마감 대기 모드로 신규 매수를 하지 않습니다)"
                else: briefing_msg += "\n\n[현재 보유 주식 상세 목록]\n보유 종목 없음 (새로운 종목 탐색 중)"
                self.sig_log.emit(briefing_msg, "info")

        current_count = len(self.mw.my_holdings)
        try: max_stocks_setting = int(db_temp.get_shared_setting("TRADE", "MAX_STOCKS", "10"))
        except: max_stocks_setting = 10
        needed_count = max_stocks_setting - current_count 
        
        # =================================================================
        # 🛒 4. 신규 종목 스캔 (🔥 실시간 주도주 스캐너 발동!)
        # =================================================================
        candidates = []; scanned_log_list = []; scan_targets = []

        if is_closing_phase: pass 
        elif market_crash_mode: pass 
        elif needed_count > 0 and not getattr(self, 'panic_mode', False):
            safe_holdings_values = list(self.mw.my_holdings.values())
            total_asset = my_cash + sum([info['price'] * info['qty'] for info in safe_holdings_values])
            
            scan_targets = self.get_realtime_hot_stocks(limit=100)

            for code in scan_targets:
                if code in self.mw.my_holdings: continue 

                prob = -1.0; curr_price = 0.0; df_feat = None

                try: prob, curr_price, df_feat = self.mw.get_ai_probability(code)
                except Exception as e: continue
                
                if prob == -1.0 or curr_price <= 0 or np.isnan(curr_price): continue 

                stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code) 
                scanned_log_list.append({'name': stock_name, 'prob': prob})
                
                try: ai_limit = float(db_temp.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
                except: ai_limit = 0.70
                
                if df_feat is not None and not df_feat.empty:
                    strat_signal = self.mw.strategy_engine.check_trade_signal(df_feat, code)
                    
                    if 0.5 <= prob < ai_limit: 
                        self.sig_log.emit(f"🔎 [{stock_name}] AI 확신도 부족 ({prob*100:.1f}%) -> 매수 보류", "warning")
                    if strat_signal == "BUY" and prob < ai_limit: 
                        self.sig_log.emit(f"💡 [{stock_name}] 전략엔진은 매수 추천이나, AI 확신도 미달로 스킵", "info")

                    curr_open = float(df_feat.iloc[-1]['open']); curr_high = float(df_feat.iloc[-1]['high']); curr_low  = float(df_feat.iloc[-1]['low']); curr_vol  = float(df_feat.iloc[-1]['volume'])
                    ret_1m = float(df_feat.iloc[-1].get('return', 0.0)); trade_amt = float(df_feat.iloc[-1].get('Trade_Amount', (curr_price * curr_vol) / 1000000))
                    curr_vol_energy = float(df_feat.iloc[-1].get('Vol_Energy', 1.0)); curr_disp = float(df_feat.iloc[-1].get('Disparity_20', 100.0))
                    curr_macd = float(df_feat.iloc[-1].get('MACD', 0.0)); curr_rsi = float(df_feat.iloc[-1].get('RSI', 50.0))
                    ma5_val = float(df_feat.iloc[-1].get('MA5', curr_price)); ma20_val = float(df_feat.iloc[-1].get('MA20', curr_price))
                else: 
                    curr_open = curr_high = curr_low = curr_price; curr_vol = ret_1m = trade_amt = 0.0
                    curr_disp = 100.0; curr_vol_energy = 1.0; curr_macd = 0.0; curr_rsi = 50.0
                    ma5_val = curr_price; ma20_val = curr_price

                market_rows.append({'종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.2f}", '시가': f"{curr_open:,.2f}", '고가': f"{curr_high:,.2f}", '저가': f"{curr_low:,.2f}", '1분등락률': f"{ret_1m:.2f}", '거래대금': f"{trade_amt:,.1f}", '거래량에너지': f"{curr_vol_energy:.2f}", '이격도': f"{curr_disp:.2f}", '거래량': f"{curr_vol:,.0f}"})
                
                if df_feat is not None: 
                    strategy_rows.append({'종목코드': code, '종목명': stock_name, '상승확률': f"{prob*100:.1f}%", 'MA_5': f"{ma5_val:.0f}", 'MA_20': f"{ma20_val:.0f}", 'RSI': f"{curr_rsi:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': "BUY 🟢" if prob >= ai_limit else "WAIT 🟡"})
                
                if prob >= ai_limit: candidates.append({'code': code, 'prob': prob, 'price': curr_price})
                
                try: db_temp.update_realtime(code, curr_price, prob*100, "NO", "탐색 및 분석 중...")
                except: pass
                
                time.sleep(0.05)
            
            if scanned_log_list:
                scanned_log_list = sorted(scanned_log_list, key=lambda x: x['prob'], reverse=True)
                top_list = scanned_log_list[:3] 
                top_msg = ", ".join([f"{x['name']}({x['prob']*100:.1f}%)" for x in top_list])
                try: ai_limit_display = float(db_temp.get_shared_setting("AI", "THRESHOLD", "70.0"))
                except: ai_limit_display = 70.0
                
                if candidates: self.sig_log.emit(f"🔥 [실시간 랭커 스캔 완료] 시장 주도주 {len(scan_targets)}개 집중분석. TOP 3: {top_msg} 👉 기준 통과! 매수 진입", "send")
                else: self.sig_log.emit(f"🔎 [실시간 랭커 스캔 완료] 시장 주도주 {len(scan_targets)}개 집중분석. TOP 3: {top_msg} 👉 기준치({ai_limit_display}%) 미달", "warning")

            if candidates:
                candidates = sorted(candidates, key=lambda x: x['prob'], reverse=True)
                for i in range(min(needed_count, len(candidates))):
                    target = candidates[i]; code = target['code']; curr_price = float(target['price']); prob = target['prob']
                    stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code) 
                    
                    try: buy_amount_setting = float(db_temp.get_shared_setting("TRADE", "BUY_AMOUNT", "1000000"))
                    except: buy_amount_setting = 1000000.0

                    if prob >= 0.85: weight = 0.20     
                    elif prob >= 0.70: weight = 0.10   
                    else: weight = 0.05                

                    budget = min(float(total_asset * weight), buy_amount_setting); buy_qty = int(budget // curr_price) 
                    if buy_qty * curr_price > my_cash: buy_qty = int(my_cash // curr_price)
                    if buy_qty == 0:
                        self.sig_log.emit(f"⚠️ [{stock_name}] 매수 자금 부족으로 스킵", "warning"); continue

                    if buy_qty == 0:
                        self.sig_log.emit(f"⚠️ [{stock_name}] 매수 자금 부족으로 스킵 (필요금액: {curr_price:,.0f}원 / 잔고: {my_cash:,.0f}원)", "warning")
                        continue

                    if buy_qty > 0 and self.mw.api_manager.buy_market_price(code, buy_qty):
                        self.mw.my_holdings[code] = {'price': curr_price, 'qty': buy_qty, 'high_watermark': curr_price, 'buy_time': now, 'half_sold': False}
                        my_cash -= (curr_price * buy_qty) 
                        self.sig_log.emit(f"🔵 [매수 체결 성공] {stock_name} | 매수가: {curr_price:,.2f} | 수량: {buy_qty}주 | 확률: {prob*100:.1f}% | 비중: {weight*100:.0f}%", "buy") 
                        self.mw.send_kakao_msg(f"🛒 [주삐 매수 알림]\n종목: {stock_name}\n체결가: {curr_price:,.2f}\n수량: {buy_qty}주\nAI 확률: {prob*100:.1f}%") 
                        self.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': '매수(BUY)', '주문가격': f"{curr_price:,.2f}", '주문수량': buy_qty, '체결수량': buy_qty, '주문시간': now.strftime("%Y-%m-%d %H:%M:%S"), '상태': '체결완료', '수익률': '0.00%'})
                        
                        account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': buy_qty, '평균매입가': f"{curr_price:,.2f}", '현재가': f"{curr_price:,.2f}", '평가손익금': "0", '수익률': "0.00%", '주문가능금액': 0})
                        if account_rows: account_rows[0]['주문가능금액'] = f"{my_cash:,}" 
                        
                        acc_cols = ['종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','주문가능금액']
                        temp_df = pd.DataFrame(account_rows)
                        for c in acc_cols:
                            if c not in temp_df.columns: temp_df[c] = ""
                        self.sig_account_df.emit(temp_df[acc_cols]) 
                        self.sig_sync_cs.emit()                     

        if account_rows: account_rows[0]['주문가능금액'] = f"{my_cash:,}" 
        else: account_rows.append({'종목코드': '-', '종목명': '보유종목 없음', '보유수량': 0, '평균매입가': '0', '현재가': '0', '평가손익금': '0', '수익률': '0.00%', '주문가능금액': f"{my_cash:,}"})
        
        acc_cols = ['종목코드','종목명','보유수량','평균매입가','현재가','평가손익금','수익률','주문가능금액']
        mkt_cols = ['종목코드','종목명','현재가','시가','고가','저가','1분등락률','거래대금','거래량에너지','이격도','거래량']
        str_cols = ['종목코드','종목명','상승확률','MA_5','MA_20','RSI','MACD','전략신호']

        if account_rows:
            df_acc = pd.DataFrame(account_rows)
            for c in acc_cols:
                if c not in df_acc.columns: df_acc[c] = ""
            self.sig_account_df.emit(df_acc[acc_cols]) 

        if market_rows: 
            df_mkt = pd.DataFrame(market_rows)
            for c in mkt_cols:
                if c not in df_mkt.columns: df_mkt[c] = "0"
            self.sig_market_df.emit(df_mkt[mkt_cols])

        if strategy_rows: 
            df_str = pd.DataFrame(strategy_rows)
            for c in str_cols:
                if c not in df_str.columns: df_str[c] = "0"
            self.sig_strategy_df.emit(df_str[str_cols])
            
        self.sig_sync_cs.emit()
        self.sig_log.emit("📡 [시스템] DB 데이터 동기화 완료!", "info")

        if getattr(self, 'panic_mode', False) and len(self.mw.my_holdings) == 0:
            self.sig_log.emit("🛑 [긴급 청산 완료] 모든 종목이 전량 매도되었습니다. 자동매매를 종료합니다.", "warning")
            self.panic_mode = False; self.is_running = False; self.sig_panic_done.emit()


# =====================================================================
# 🖥️ 메인 UI 클래스 (프로그램의 시작점)
# =====================================================================
class FormMain(QtWidgets.QMainWindow):
    # 🔥 [핵심 수정 1] 백그라운드 스레드에서 직접 UI 타이머를 생성하지 못하도록, 
    # 무조건 메인 큐를 통과하게 만드는 안전장치(Signal)를 신설합니다.
    sig_safe_log = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.KAKAO_TOKEN = "여기에_발급받은_카카오톡_REST_API_토큰을_입력하세요" 

        # 로그 안전 신호 연결
        self.sig_safe_log.connect(self._safe_append_log_sync)

        self.db = JubbyDB_Manager()
        self.db.cleanup_old_data() 
        
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            conn.execute("DELETE FROM MarketStatus")
            conn.execute("DELETE FROM AccountStatus")
            conn.execute("DELETE FROM StrategyStatus")
            conn.close()
            self.db.insert_log("INFO", "🧹 [시스템] 이전 실시간 DB 데이터를 성공적으로 초기화했습니다.")
        except Exception as e:
            if hasattr(self, 'db'):
                self.db.insert_log("WARNING", f"⚠️ DB 실시간 데이터 초기화 실패: {e}")
        
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
            
            if SystemConfig.MARKET_MODE == "DOMESTIC":
                self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str).str.zfill(6), df_dict['symbol_name']))
            else:
                self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str), df_dict['symbol_name']))
                
            if not self.DYNAMIC_STOCK_DICT: raise ValueError("DB 명단이 비어 있습니다.")
            self.add_log(f"📖 DB에서 {len(self.DYNAMIC_STOCK_DICT)}개 종목 명단을 무사히 불러왔습니다!", "info")
        except Exception as e:
            self.add_log(f"⚠️ DB 명단 로드 실패: {e} -> Data Collector를 한 번 실행해 주세요.", "warning")
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
        
        # 🔗 스레드가 종료되었을 때 UI를 안전하게 복구하는 슬롯 연결
        self.trade_worker.finished.connect(self.check_worker_stopped)

        QtCore.QTimer.singleShot(3000, self.load_real_holdings) 
        
        self.kakao_timer = QtCore.QTimer(self)
        self.kakao_timer.timeout.connect(self.auto_status_report)
        self.kakao_timer.start(1000 * 60 * 60) 

        QtCore.QTimer.singleShot(3000, lambda: self.send_kakao_msg("🚀 [주삐 시스템] 카카오톡 연동 확인"))

    def send_kakao_msg(self, text):
        REST_API_KEY = "4cbe02304c893a129a812045d5f200a3" 
        try:
            import json, os, requests
            gui_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.dirname(gui_dir)
            path_candidates = [os.path.join(gui_dir, "kakao_token.json"), os.path.join(root_dir, "kakao_token.json"), os.path.join(root_dir, "COMMON", "kakao_token.json")]
            
            token_path = None
            for path in path_candidates:
                if os.path.exists(path):
                    token_path = path; break
                    
            if token_path is None: return False
            
            with open(token_path, "r") as fp: tokens = json.load(fp)
            
            url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
            headers = {"Authorization": f"Bearer {tokens['access_token']}"}
            safe_text = text.replace('\n', '\\n').replace('"', '\\"')
            data = {"template_object": '{"object_type": "text", "text": "' + safe_text + '", "link": {}}'}
            
            res = requests.post(url, headers=headers, data=data)
            if res.status_code == 200: return True 
            else:
                refresh_url = "https://kauth.kakao.com/oauth/token"
                refresh_data = {"grant_type": "refresh_token", "client_id": REST_API_KEY, "refresh_token": tokens.get("refresh_token")}
                new_token_res = requests.post(refresh_url, data=refresh_data, timeout=3).json()
                
                if "access_token" not in new_token_res: return False
                    
                tokens["access_token"] = new_token_res["access_token"]
                if "refresh_token" in new_token_res: tokens["refresh_token"] = new_token_res["refresh_token"]
                with open(token_path, "w") as fp: json.dump(tokens, fp)
                    
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}
                res2 = requests.post(url, headers=headers, data=data, timeout=3)
                if res2.status_code == 200: return True
                else: return False
        except Exception as e: return False

    def auto_status_report(self): pass 

    @QtCore.pyqtSlot(str)
    def sys_print_to_log(self, text): self.add_log(f"🖥️ {text}", "info")

    @QtCore.pyqtSlot(dict)
    def append_order_table_slot(self, order_info):
        if not order_info: return 
        
        try:
            code = order_info.get('종목코드', '')
            o_type = "BUY" if "BUY" in str(order_info.get('주문종류', '')).upper() else "SELL"
            price = float(str(order_info.get('주문가격', '0')).replace(',', ''))
            qty = int(order_info.get('주문수량', 0))
            y_rate = float(str(order_info.get('수익률', '0')).replace('%', ''))
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
        self.tbOrder.scrollToBottom(); self.btnDataSendClickEvent()

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
                market_list.append({
                    "symbol": sym, "symbol_name": str(row.get("종목명", "")),
                    "last_price": float(clean_num(row.get("현재가", "0"))),
                    "open_price": float(clean_num(row.get("시가", "0"))),
                    "high_price": float(clean_num(row.get("고가", "0"))),
                    "low_price": float(clean_num(row.get("저가", "0"))),
                    "return_1m": float(clean_num(row.get("1분등락률", "0"))),
                    "trade_amount": float(clean_num(row.get("거래대금", "0"))),
                    "vol_energy": float(clean_num(row.get("거래량에너지", "1"))),
                    "disparity": float(clean_num(row.get("이격도", "100"))),
                    "volume": float(clean_num(row.get("거래량", "0")))
                })
            try: self.db.update_market_table(market_list)
            except Exception as e:
                self.add_log(f"🚨 MarketStatus DB 업데이트 실패: {e}", "error")

        account_list = []
        if not TradeData.account.df.empty:
            for _, row in TradeData.account.df.iterrows():
                sym = get_symbol(row)
                if not sym: continue
                curr_price = float(clean_num(row.get("현재가", "0")))
                
                account_list.append({
                    "symbol": sym, "symbol_name": str(row.get("종목명", "")), 
                    "quantity": int(float(clean_num(row.get("보유수량", "0")))), 
                    "avg_price": float(clean_num(row.get("평균매입가", "0"))), 
                    "current_price": curr_price, 
                    "pnl_amt": float(clean_num(row.get("평가손익금", "0"))), 
                    "pnl_rate": float(clean_num(row.get("수익률", "0"))), 
                    "available_cash": float(clean_num(row.get("주문가능금액", "0")))
                })
                
                if curr_price > 0:
                    try: self.db.insert_price_history(sym, curr_price)
                    except: pass
            
            try: self.db.update_account_table(account_list)
            except Exception as e:
                self.add_log(f"🚨 AccountStatus DB 업데이트 실패: {e}", "error")

        strategy_list = []
        if not TradeData.strategy.df.empty:
            for _, row in TradeData.strategy.df.iterrows():
                sym = get_symbol(row)
                if not sym: continue
                sig = str(row.get("전략신호", "")); sig = "BUY" if "BUY" in sig else ("SELL" if "SELL" in sig else ("WAIT" if "WAIT" in sig else sig))
                strategy_list.append({
                    "symbol": sym, "symbol_name": str(row.get("종목명", "")), 
                    "ma_5": float(clean_num(row.get("MA_5", "0"))), 
                    "ma_20": float(clean_num(row.get("MA_20", "0"))), 
                    "RSI": float(clean_num(row.get("RSI", "0"))), 
                    "macd": float(clean_num(row.get("MACD", "0"))), 
                    "signal": sig
                })
            try: self.db.update_strategy_table(strategy_list)
            except Exception as e:
                self.add_log(f"🚨 StrategyStatus DB 업데이트 실패: {e}", "error")

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
                self.add_log(f"💼 [보유 종목 동기화] {len(self.my_holdings)}개 종목 로드 완료 👉 {holdings_str}", "success")
            else:
                self.add_log("💼 [보유 종목 동기화] 현재 계좌에 보유 중인 종목이 없습니다.", "info")
        except Exception as e: 
            self.add_log(f"🚨 보유 종목 동기화 실패: {e}", "error")
            return
            
        my_cash = self.api_manager.get_balance()
        cash_str = f"{my_cash:,}" if my_cash is not None else "0"
        self.add_log(f"💰 [잔고 동기화] 현재 주문 가능 예수금: {cash_str}원", "success")
        
        account_rows = []; is_first = True
        
        for code, info in list(self.my_holdings.items()):
            buy_price = info['price']; buy_qty = info['qty']; stock_name = self.DYNAMIC_STOCK_DICT.get(code, f"알수없음_{code}")
            self.my_holdings[code]['high_watermark'] = buy_price

            df = self.api_manager.fetch_minute_data(code); pnl_str = "0.00%"; curr_price = buy_price
            if df is not None:
                curr_price = df.iloc[-1]['close']; profit_rate = ((curr_price - buy_price) / buy_price) * 100; pnl_str = f"{profit_rate:.2f}%"
                self.my_holdings[code]['high_watermark'] = max(buy_price, curr_price) 
                self.my_holdings[code]['buy_time'] = datetime.now() 
                self.my_holdings[code]['half_sold'] = False
                
            account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': buy_qty, '평균매입가': f"{buy_price:,.0f}", '현재가': f"{curr_price:,.0f}", '평가손익금': pnl_str, '수익률': pnl_str, '주문가능금액': cash_str if is_first else "" })
            is_first = False
            
        if account_rows: 
            df_acc = pd.DataFrame(account_rows)
            acc_cols = ['종목코드','종목명','보유수량','평균매입가','현재가','평가손익금', '수익률','주문가능금액']
            for c in acc_cols:
                if c not in df_acc.columns: df_acc[c] = ""
            TradeData.account.df = df_acc[acc_cols]
            QtCore.QTimer.singleShot(500, lambda: self.update_table(self.tbAccount, TradeData.account.df))

    def initUI(self):
        ui_file_path = resource_path("GUI/Main.ui")
        uic.loadUi(ui_file_path, self)
        
        # 💡 TCP 연결 버튼 삭제!
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
        self.add_log("🔓 [시스템] 보안 로그인 성공! 주삐 AI 엔진 화면을 활성화합니다.", "success")

    def btnSimulTestClickEvent(self):
        self.add_log("🔄 [수동 조회] 증권사 서버에 계좌 상세 현황을 요청합니다...", "info")
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
        act_strategy = menu.addAction("📊 Strategy (전략 엔진 점검)")
        
        menu.addSeparator() 
        act_panic = menu.addAction("🛑 긴급 전체 청산 및 자동매매 종료 (Panic Sell)")
        menu.addSeparator() 
        act_save_log = menu.addAction("💾 현재 로그 텍스트로 저장 (Save Log)") 

        action = menu.exec_(pos)
        
        if action == act_toggle_mode: self.toggle_market_mode() 
        elif action == act_collect: self.start_data_collector()
        elif action == act_train: self.start_ai_trainer()
        elif action == act_strategy: self.add_log("📊 [Strategy] 15개 다차원 전략 엔진(Strategy.py)이 메인 루프에 정상 연결되어 있습니다.", "success")
        elif action == act_panic: self.start_panic_sell()
        elif action == act_save_log: self.save_manual_log()

    def toggle_market_mode(self):
        if self.trade_worker.is_running:
            self.add_log("⚠️ 자동매매 가동 중에는 시장 모드를 변경할 수 없습니다. 먼저 STOP 해주세요.", "warning")
            return

        if SystemConfig.MARKET_MODE == "DOMESTIC":
            SystemConfig.MARKET_MODE = "OVERSEAS"
            self.add_log("🌐 [모드 변경] 미국(NASDAQ) 주식 자동매매 모드로 전환되었습니다!", "send")
            self.api_manager.ACCOUNT_NO = "50172151"
            self.api_manager.api.account_no = "50172151"
            
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            SystemConfig.MARKET_MODE = "OVERSEAS_FUTURES"
            self.add_log("🚀 [모드 변경] 해외선물(CME) 자동매매 모드로 전환되었습니다!", "send")
            self.api_manager.ACCOUNT_NO = "60039684"         
            self.api_manager.api.account_no = "60039684"
            
        else:
            SystemConfig.MARKET_MODE = "DOMESTIC"
            self.add_log("🇰🇷 [모드 변경] 국내(KRX) 주식 자동매매 모드로 전환되었습니다!", "send")
            self.api_manager.ACCOUNT_NO = "50172151"
            self.api_manager.api.account_no = "50172151"

        try: self.db.set_shared_setting("SYSTEM", "MARKET_MODE", SystemConfig.MARKET_MODE)
        except: pass
        
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            query = f"SELECT symbol, symbol_name FROM target_stocks WHERE market_mode = '{SystemConfig.MARKET_MODE}'"
            df_dict = pd.read_sql(query, conn)
            conn.close()
            
            if SystemConfig.MARKET_MODE == "DOMESTIC":
                self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str).str.zfill(6), df_dict['symbol_name']))
            else:
                self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['symbol'].astype(str), df_dict['symbol_name']))
                
            self.add_log(f"📖 시장 모드에 맞춰 종목 사전 DB 갱신 완료 (총 {len(self.DYNAMIC_STOCK_DICT)}개 종목)", "info")
        except Exception as e:
            self.add_log(f"⚠️ DB에서 종목 사전을 불러올 수 없습니다. Data Collector를 실행해 주세요. ({e})", "warning")
            self.DYNAMIC_STOCK_DICT = {}

        if hasattr(self.strategy_engine, 'load_ai_brain'):
            self.strategy_engine.load_ai_brain()

        self.btnDataClearClickEvent()

    def start_panic_sell(self):
        if not self.trade_worker.is_running: return
        if len(self.my_holdings) == 0: self.btnAutoTradingSwitch(); return

        stock_names = [self.DYNAMIC_STOCK_DICT.get(c, c) for c in self.my_holdings.keys()]
        msg = f"🚨 [긴급 전체 청산 발동]\n신규 매수를 전면 차단하고 보유 중인 {len(self.my_holdings)}개 종목을 모두 시장가로 정리합니다!\n\n📌 척살 대상: {', '.join(stock_names)}"
        self.add_log(msg, "error"); self.send_kakao_msg(msg)
        self.trade_worker.panic_mode = True 

    @QtCore.pyqtSlot()
    def panic_sell_done_slot(self):
        self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
        self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")

    def btnAutoTradingSwitch(self):
        if not self.trade_worker.is_running: 
            if self.trade_worker.isRunning():
                self.add_log("⚠️ 이전 감시망이 아직 안전하게 종료 중입니다. 잠시 후 다시 눌러주세요.", "warning")
                return
            self.trade_worker.panic_mode = False 
            self.trade_worker.start()
            self.btnAutoDataTest.setText("자동 매매 중단 (STOP)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 [주삐 엔진] 1분 단위 감시망 가동! 잠시 후 첫 브리핑이 시작됩니다.", "success")
        else: 
            if hasattr(self, 'trade_worker'):
                self.trade_worker.is_running = False
            
            self.btnAutoDataTest.setText("감시망 종료 중...")
            self.btnAutoDataTest.setEnabled(False) 
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(40, 40, 40); color: Gray;")
            self.add_log("🛑 [주삐 엔진] 감시망 종료 명령이 전달되었습니다. 스레드가 완전히 멈추면 복구됩니다.", "warning")

    @QtCore.pyqtSlot()
    def check_worker_stopped(self):
        """스레드가 100% 안전하게 죽은 뒤에만 호출됩니다."""
        if self.btnAutoDataTest.text() == "감시망 종료 중...":
            self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
            self.btnAutoDataTest.setEnabled(True)
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
            self.add_log(f"✅ [저장 성공] 현재 로그가 {filename} 로 캡처되었습니다.", "success")
        except Exception as e: pass

    def start_data_collector(self):
        try:
            if hasattr(self, 'collector_worker') and self.collector_worker.isRunning(): return
            self.add_log("🚀 핫플레이스 수집을 백그라운드에서 실행합니다. (1~2시간 소요)", "info")
            app_key = getattr(self.api_manager, 'APP_KEY', "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy")
            app_secret = getattr(self.api_manager, 'APP_SECRET', "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8=")
            account_no = getattr(self.api_manager, 'ACCOUNT_NO', "50172151")
            is_mock = getattr(self.api_manager, 'IS_MOCK', True)
            
            self.collector_worker = DataCollectorWorker(app_key, app_secret, account_no, is_mock)
            self.collector_worker.sig_log.connect(self.add_log)
            self.collector_worker.start()
        except Exception as e: pass

    def start_ai_trainer(self):
        if hasattr(self, 'trade_worker') and self.trade_worker.is_running:
            self.add_log("🛑 [시스템 경고] 자동매매 가동 중에는 AI를 학습시킬 수 없습니다! (메모리 충돌 방지). 반드시 자동매매를 'STOP' 한 후 다시 실행해 주세요.", "error")
            return
            
        if hasattr(self, 'trainer_worker') and self.trainer_worker.isRunning(): return
        self.add_log("🚀 주삐 AI 학습 엔진을 가동합니다...", "info")
        self.trainer_worker = AITrainerWorker()
        self.trainer_worker.sig_log.connect(self.add_log)
        self.trainer_worker.start()
        
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
                buy_price = self.my_holdings[code]['price']
                self.add_log(f"🚨 [{stock_name}] 비상 탈출 시작! 수량: {qty}주 | 시장가 매도 진행", "send")
                if self.api_manager.sell(code, qty):
                    del self.my_holdings[code]; self.tbAccount.removeRow(row)
                    if hasattr(self, 'trade_worker'): self.trade_worker.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': '비상(SELL_LOSS)', '주문가격': '시장가', '주문수량': qty, '체결수량': qty, '주문시간': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '상태': '비상청산완료', '수익률': "0.00%"})
                    self.add_log(f"✅ [비상 탈출 성공] {stock_name} 전량 매도 완료", "sell"); self.btnDataSendClickEvent()
        except Exception as e: pass

    def get_ai_probability(self, code):
        df = self.api_manager.fetch_minute_data(code) 
        if df is None or len(df) < 30: return 0.0, 0, None 
        
        df = self.strategy_engine.calculate_indicators(df)
        curr_price = df.iloc[-1]['close'] 
        
        prob = 0.0
        if self.strategy_engine.ai_model is not None:
            features = self.strategy_engine.get_ai_features(df)
            if features is not None:
                prob = self.strategy_engine.ai_model.predict_proba(features)[0][1]
                
        return prob, curr_price, df

    @QtCore.pyqtSlot(object) 
    def update_account_table_slot(self, df): self.update_table(self.tbAccount, df)
    @QtCore.pyqtSlot(object) 
    def update_strategy_table_slot(self, df): self.update_table(self.tbStrategy, df)

    # 🔥 [핵심 수정 2] 백그라운드 스레드에서 QTimer 생성을 100% 방지하기 위해 
    # 무조건 pyqtSignal(sig_safe_log)을 통해 메인 화면으로 던지도록 바꿨습니다!
    @QtCore.pyqtSlot(str, str) 
    def add_log(self, text, log_type="info"):
        self.sig_safe_log.emit(text, log_type)

    @QtCore.pyqtSlot(str, str)
    def _safe_append_log_sync(self, text, log_type):
        color = {"info": "white", "success": "lime", "warning": "yellow", "error": "red", "send": "cyan", "recv": "orange", "buy": "#4B9CFF", "sell": "#FF4B4B"}.get(log_type, "white")
        formatted_text = text.replace('\n', '<br>&nbsp;&nbsp;&nbsp;&nbsp;')
        html_msg = f'<span style="color:{color}"><b>{datetime.now().strftime("[%H:%M:%S]")}</b> {formatted_text}</span>'
        self.txtLog.appendHtml(html_msg)
        self.txtLog.verticalScrollBar().setValue(self.txtLog.verticalScrollBar().maximum())
        try:
            if hasattr(self, 'db'): self.db.insert_log(log_type.upper(), text)
        except Exception: pass

    def _setup_table(self, table, columns): table.setColumnCount(len(columns)); table.setHorizontalHeaderLabels(columns); self.style_table(table)
    def style_table(self, table): table.setFont(QtGui.QFont("Noto Sans KR", 12)); table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch); table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows); table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection); table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers); table.setStyleSheet("QTableWidget { background-color: rgb(50,80,110); color: Black; selection-background-color: rgb(80, 120, 160); } QHeaderView::section { background-color: rgb(40,60,90); color: Black; font-weight: bold; }")
    def _create_nav_button(self, text, x_pos): btn = QtWidgets.QPushButton(text, self.centralwidget); btn.setGeometry(x_pos, 5, 300, 40); btn.setStyleSheet("background-color: rgb(5,5,15); color: Silver;"); btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor)); btn.installEventFilter(self); return btn
    def eventFilter(self, source, event):
        if event.type() == QtCore.QEvent.Enter: source.setStyleSheet("background-color: rgb(5,5,10); color: Lime;")
        elif event.type() == QtCore.QEvent.Leave: source.setStyleSheet("background-color: rgb(5,5,10); color: Silver;")
        return super().eventFilter(source, event)
    def btnCloseClickEvent(self): QtWidgets.QApplication.quit()         
    def btnDataCreatClickEvent(self): pass
    def generate_and_send_mock_data(self): pass
    
    def update_table(self, tableWidget, df):
        tableWidget.setUpdatesEnabled(False)
        if tableWidget.columnCount() != len(df.columns) or [tableWidget.horizontalHeaderItem(i).text() for i in range(tableWidget.columnCount())] != list(df.columns):
            tableWidget.setColumnCount(len(df.columns))
            tableWidget.setHorizontalHeaderLabels(list(df.columns))
            
        current_row_count = tableWidget.rowCount(); new_row_count = len(df)                    
        if current_row_count < new_row_count:
            for _ in range(new_row_count - current_row_count): tableWidget.insertRow(tableWidget.rowCount())
        elif current_row_count > new_row_count:
            for _ in range(current_row_count - new_row_count): tableWidget.removeRow(tableWidget.rowCount() - 1)
        for i in range(new_row_count):
            for j, col in enumerate(df.columns):
                val = str(df.iloc[i, j]); item = tableWidget.item(i, j)     
                if item is None: item = QtWidgets.QTableWidgetItem(val); item.setTextAlignment(QtCore.Qt.AlignCenter); tableWidget.setItem(i, j, item)
                else:
                    if item.text() != val: item.setText(val)
        tableWidget.scrollToBottom(); tableWidget.setUpdatesEnabled(True)
        
    def btnDataClearClickEvent(self): self.tbAccount.setRowCount(0); self.tbStrategy.setRowCount(0); self.tbOrder.setRowCount(0); self.tbMarket.setRowCount(0)

# =====================================================================
# 🚀 파이썬 프로그램의 진짜 시작점! 
# =====================================================================
if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    mainWindow = FormMain()
    mainWindow.show()
    sys.exit(app.exec_())