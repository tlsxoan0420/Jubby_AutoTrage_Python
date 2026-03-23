# =====================================================================
# 📦 [1단계] 마법의 도구 상자 열기
# =====================================================================
import sys
import os                  
import time                
import random              
import joblib              
import pandas as pd        
import numpy as np         
import requests # 카카오톡 통신용
from datetime import datetime 
from PyQt5 import QtWidgets, uic, QtCore, QtGui  
from PyQt5.QtCore import Qt, QThread, pyqtSignal 

from COMMON.Flag import TradeData            
from COM.TcpJsonClient import TcpJsonClient  
from COMMON.KIS_Manager import KIS_Manager   

# 🛠️ 왜 매수/매도 안하는지 알려주는 뇌(Strategy)를 가져옵니다.
from TRADE.Argorism.Strategy import JubbyStrategy 

class OutputLogger(QtCore.QObject):
    emit_log = QtCore.pyqtSignal(str)
    def write(self, text):
        if text.strip(): self.emit_log.emit(text.strip())
    def flush(self): pass

class DataCollectorWorker(QThread):
    sig_log = pyqtSignal(str, str)
    def __init__(self, app_key, app_secret, account_no, is_mock):
        super().__init__()
        self.app_key = app_key; self.app_secret = app_secret; self.account_no = account_no; self.is_mock = is_mock
    def run(self):
        try:
            try: from TRADE.Argorism.Data_Collector import UltraDataCollector
            except: from TRADE.Argorism.Data_Collector import UltraDataCollector
            import FinanceDataReader as fdr
            self.emit_log("📡 한국 거래소(KRX)에서 [당일 거래대금 상위 1000개] 핫플레이스 명단을 추출합니다...", "info")
            krx_df = fdr.StockListing('KRX')
            krx_df = krx_df[(krx_df['Market'] == 'KOSPI') | (krx_df['Market'] == 'KOSDAQ')]
            if 'Close' in krx_df.columns: krx_df = krx_df[krx_df['Close'] >= 1000]
            if 'Amount' in krx_df.columns: top_1000_df = krx_df.sort_values('Amount', ascending=False).head(1000)
            else: top_1000_df = krx_df.sort_values('Marcap', ascending=False).head(1000)
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            top_1000_df[['Code', 'Name']].to_csv(os.path.join(root_dir, "stock_dict.csv"), index=False, encoding="utf-8-sig")
            
            collector = UltraDataCollector(self.app_key, self.app_secret, self.account_no, self.is_mock, log_callback=self.emit_log)
            collector.run_collection(top_1000_df['Code'].tolist())
        except Exception as e: self.emit_log(f"🚨 수집기 스레드 내부 오류: {e}", "error")
    def emit_log(self, msg, level="info"): self.sig_log.emit(msg, level)

class AITrainerWorker(QThread):
    sig_log = pyqtSignal(str, str)
    def run(self):
        try:
            from TRADE.Argorism.Jubby_AI_Trainer import train_jubby_brain
            train_jubby_brain(log_callback=self.emit_log)
        except Exception as e: self.emit_log(f"🚨 AI 학습기 실행 오류: {e}", "error")
    def emit_log(self, msg, level="info"): self.sig_log.emit(msg, level)

class AutoTradeWorker(QThread):
    sig_log = pyqtSignal(str, str); sig_account_df = pyqtSignal(object)        
    sig_strategy_df = pyqtSignal(object); sig_market_df = pyqtSignal(object)         
    sig_sync_cs = pyqtSignal(); sig_order_append = pyqtSignal(dict)        
    
    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window; self.is_running = False; self.cumulative_realized_profit = 0 
        
    def run(self):
        self.is_running = True
        while self.is_running:
            self.process_trading() 
            for _ in range(60):
                if not self.is_running: break 
                time.sleep(1)

    def execute_guaranteed_sell(self, code, qty, current_price):
        for _ in range(3):
            if self.mw.api_manager.sell(code, qty): return True
            time.sleep(1.0) 
        return self.mw.api_manager.sell(code, qty) 

    def process_trading(self):
        now = datetime.now() 
        self.sig_log.emit(f"🔄 [주삐 엔진 가동중] {now.strftime('%H:%M')} - 스캔 및 AI 방어 모드 작동중...", "info")
        MAX_STOCKS = 10 
        SCAN_POOL = list(self.mw.DYNAMIC_STOCK_DICT.keys()) 
        account_rows = []; market_rows = []; strategy_rows = [] 
        total_invested = 0; total_current_val = 0  

        market_crash_mode = False
        kospi_etf = self.mw.api_manager.fetch_minute_data("069500")
        if kospi_etf is not None and len(kospi_etf) > 1:
            etf_now = kospi_etf.iloc[-1]['close']
            etf_prev = kospi_etf.iloc[-2]['close']
            market_ret_1m = ((etf_now - etf_prev) / etf_prev) * 100.0
            
            self.mw.strategy_engine.market_return_1m = market_ret_1m
            
            etf_open = kospi_etf.iloc[0]['open']
            etf_drop = ((etf_now - etf_open) / etf_open) * 100
            if etf_drop <= -1.5: 
                market_crash_mode = True
                self.sig_log.emit(f"⚠️ [시장 경고] 코스피 지수가 급락 중입니다. (시가 대비 {etf_drop:.2f}%) 신규 매수를 일시 차단합니다.", "warning")

        if len(self.mw.my_holdings) > 0: 
            sold_codes = []; hold_status_list = [] 
            for code, info in list(self.mw.my_holdings.items()): 
                buy_price = info['price']; buy_qty = info['qty']; stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code)
                high_watermark = info.get('high_watermark', buy_price); buy_time = info.get('buy_time', now); half_sold = info.get('half_sold', False) 

                df = self.mw.api_manager.fetch_minute_data(code)
                if df is None or len(df) < 30: continue 
                
                df = self.mw.strategy_engine.calculate_indicators(df)
                
                curr_price = df.iloc[-1]['close']
                profit_rate = ((curr_price - buy_price) / buy_price) * 100 
                
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
                curr_macd = df.iloc[-1]['MACD']; curr_signal = df.iloc[-1]['Signal_Line']
                ret_1m = df.iloc[-1]['return']; trade_amt = df.iloc[-1]['Trade_Amount']
                curr_vol_energy = df.iloc[-1]['Vol_Energy']; curr_disp = df.iloc[-1]['Disparity_20']

                market_rows.append({
                    '종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.0f}", '시가': f"{curr_open:,.0f}", '고가': f"{curr_high:,.0f}", '저가': f"{curr_low:,.0f}",
                    '1분등락률': f"{ret_1m:.2f}", '거래대금': f"{trade_amt:,.1f}", '거래량에너지': f"{curr_vol_energy:.2f}", '이격도': f"{curr_disp:.2f}", '거래량': f"{curr_vol:,.0f}"
                })

                is_sell_all = False; is_sell_half = False; status_msg = ""; sell_qty = buy_qty
                
                strat_signal = self.mw.strategy_engine.check_trade_signal(df, code)

                if now.hour == 15 and now.minute >= 10: is_sell_all = True; status_msg = "마감 임박 청산"
                elif now.hour == 15 and 0 <= now.minute < 10:
                    if profit_rate >= 0.3: is_sell_all = True; status_msg = "수수료 방어 마감 익절"
                    elif profit_rate > 0.0 and curr_macd < curr_signal: is_sell_all = True; status_msg = "마감 전 추세꺾임 탈출"
                    elif profit_rate <= stop_rate: is_sell_all = True; status_msg = "마감 전 기계적 손절"
                else:
                    if strat_signal == "SELL" and profit_rate > 0.5:
                        is_sell_all = True; status_msg = "전략엔진 매도 신호 (수익 보존)"
                    elif strat_signal == "SELL" and profit_rate <= stop_rate:
                        is_sell_all = True; status_msg = "전략엔진 매도 신호 (리스크 최소화)"
                    elif profit_rate >= target_rate and not half_sold: 
                        is_sell_half = True; sell_qty = max(1, buy_qty // 2); status_msg = f"동적 목표가({target_rate:.1f}%) 도달 1차 익절"
                    elif half_sold and trail_drop_rate >= 0.5:
                        is_sell_all = True; status_msg = "트레일링 스탑 (나머지 전량 익절)"
                    elif profit_rate <= stop_rate: 
                        is_sell_all = True; status_msg = f"ATR 동적 손절라인({stop_rate:.1f}%) 이탈"
                    elif profit_rate >= 1.5 and curr_macd < curr_signal: 
                        is_sell_all = True; status_msg = "데드크로스 수익보존 탈출"
                    elif elapsed_mins >= 45 and (-1.0 <= profit_rate <= 1.0):
                        is_sell_all = True; status_msg = f"타임아웃 ({int(elapsed_mins)}분 횡보) 탈출"

                if is_sell_half or is_sell_all:
                    if self.execute_guaranteed_sell(code, sell_qty, curr_price): 
                        if is_sell_all: sold_codes.append(code) 
                        else: 
                            self.mw.my_holdings[code]['qty'] -= sell_qty
                            self.mw.my_holdings[code]['half_sold'] = True
                        
                        realized_profit = (curr_price - buy_price) * sell_qty
                        self.cumulative_realized_profit += realized_profit
                        
                        log_icon, log_color = ("🟢", "success") if profit_rate > 0 else ("🔴", "sell")
                        sell_msg = (f"{log_icon} [매도 체결 완료] {stock_name} | 매도가: {curr_price:,.0f}원 | "
                                    f"수량: {sell_qty}주 | 실현 손익: {int(realized_profit):,}원 ({profit_rate:.2f}%) | 사유: {status_msg}")
                        self.sig_log.emit(sell_msg, log_color) 
                        
                        # 💬 카카오톡 매도 알림 전송
                        self.mw.send_kakao_msg(f"🔔 [주삐 매도 알림]\n종목: {stock_name}\n수익률: {profit_rate:.2f}%\n손익: {int(realized_profit):,}원\n사유: {status_msg}") 
                        
                        sell_type_str = '익절(SELL_PROFIT)' if profit_rate > 0 else '손절(SELL_LOSS)'
                        self.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': sell_type_str, '주문가격': f"{curr_price:,.0f}", '주문수량': sell_qty, '체결수량': sell_qty, '주문시간': now.strftime("%Y-%m-%d %H:%M:%S"), '상태': '체결완료'})

                if not is_sell_all:
                    cur_qty = self.mw.my_holdings[code]['qty'] if is_sell_half else buy_qty
                    account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': cur_qty, '평균매입가': f"{buy_price:,.0f}", '현재가': f"{curr_price:,.0f}", '평가손익': f"{profit_rate:.2f}%", '주문가능금액': 0})
                    if half_sold or is_sell_half: hold_status_list.append(f"[{stock_name}: 🚀트레일링 추적({profit_rate:.2f}%)]")
                    else: hold_status_list.append(f"[{stock_name}: ⏳{int(elapsed_mins)}분째({profit_rate:.2f}%)]") 
                
                strategy_rows.append({'종목코드': code, '종목명': stock_name, '상승확률': '-', 'MA_5': f"{df.iloc[-1]['MA5']:.0f}", 'MA_20': f"{df.iloc[-1]['MA20']:.0f}", 'RSI': f"{df.iloc[-1]['RSI']:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': '보유중'})
            
            for code in sold_codes: 
                if code in self.mw.my_holdings: del self.mw.my_holdings[code]

        current_count = len(self.mw.my_holdings); needed_count = MAX_STOCKS - current_count 
        api_cash = self.mw.api_manager.get_balance(); my_cash = api_cash if api_cash is not None else getattr(self.mw, 'last_known_cash', 0)
        self.mw.last_known_cash = my_cash; cash_str = f"{my_cash:,}" 

        if now.hour >= 15: pass
        elif market_crash_mode: pass
        elif needed_count > 0:
            total_asset = my_cash + sum([info['price'] * info['qty'] for info in self.mw.my_holdings.values()])
            candidates = []; scan_targets = random.sample(SCAN_POOL, min(40, len(SCAN_POOL)))

            for code in scan_targets:
                if code in self.mw.my_holdings: continue 
                
                prob, curr_price, df_feat = self.mw.get_ai_probability(code)
                if prob == -1.0: break 

                stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code) 
                
                if df_feat is not None and not df_feat.empty:
                    strat_signal = self.mw.strategy_engine.check_trade_signal(df_feat, code)
                    if 0.5 <= prob < 0.7:
                        self.sig_log.emit(f"🔎 [{stock_name}] AI 확신도 부족 ({prob*100:.1f}%) -> 매수 보류", "warning")
                    if strat_signal == "BUY" and prob < 0.7:
                        self.sig_log.emit(f"💡 [{stock_name}] 전략엔진은 강력 매수를 추천하나, AI 확신도(70% 미달)로 스킵", "info")

                    curr_open = float(df_feat.iloc[-1]['open']); curr_high = float(df_feat.iloc[-1]['high'])
                    curr_low  = float(df_feat.iloc[-1]['low']); curr_vol  = float(df_feat.iloc[-1]['volume'])
                    ret_1m = float(df_feat.iloc[-1]['return']); trade_amt = float(df_feat.iloc[-1]['Trade_Amount'])
                    curr_vol_energy = float(df_feat.iloc[-1]['Vol_Energy']); curr_disp = float(df_feat.iloc[-1]['Disparity_20'])
                    curr_macd = float(df_feat.iloc[-1]['MACD']); curr_rsi = float(df_feat.iloc[-1]['RSI'])
                else: 
                    curr_open = curr_high = curr_low = curr_price; curr_vol = ret_1m = trade_amt = curr_disp = 0.0; curr_vol_energy = 1.0
                    curr_macd = curr_rsi = 0.0

                market_rows.append({'종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.0f}", '시가': f"{curr_open:,.0f}", '고가': f"{curr_high:,.0f}", '저가': f"{curr_low:,.0f}", '1분등락률': f"{ret_1m:.2f}", '거래대금': f"{trade_amt:,.1f}", '거래량에너지': f"{curr_vol_energy:.2f}", '이격도': f"{curr_disp:.2f}", '거래량': f"{curr_vol:,.0f}"})
                
                if df_feat is not None: 
                    strategy_rows.append({'종목코드': code, '종목명': stock_name, '상승확률': f"{prob*100:.1f}%", 'MA_5': f"{df_feat.iloc[-1]['MA5']:.0f}", 'MA_20': f"{df_feat.iloc[-1]['MA20']:.0f}", 'RSI': f"{curr_rsi:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': "BUY 🟢" if prob >= 0.7 else "WAIT 🟡"})
                
                if prob >= 0.7: candidates.append({'code': code, 'prob': prob, 'price': curr_price})
                time.sleep(0.1) 
            
            if candidates:
                candidates = sorted(candidates, key=lambda x: x['prob'], reverse=True)
                for i in range(min(needed_count, len(candidates))):
                    target = candidates[i]
                    code = target['code']; curr_price = target['price']; prob = target['prob']
                    stock_name = self.mw.DYNAMIC_STOCK_DICT.get(code, code) 
                    
                    if prob >= 0.85: weight = 0.20     
                    elif prob >= 0.70: weight = 0.10   
                    else: weight = 0.05                

                    budget = int(total_asset * weight)
                    buy_qty = int(budget / curr_price) 

                    if buy_qty * curr_price > my_cash: buy_qty = int(my_cash / curr_price)

                    if buy_qty > 0 and self.mw.api_manager.buy_market_price(code, buy_qty):
                        self.mw.my_holdings[code] = {
                            'price': curr_price, 'qty': buy_qty, 
                            'high_watermark': curr_price, 'buy_time': now, 'half_sold': False
                        }
                        
                        my_cash -= (curr_price * buy_qty) 
                        self.sig_log.emit(f"🔵 [매수 체결 성공] {stock_name} | 매수가: {curr_price:,.0f}원 | 수량: {buy_qty}주 | 확률: {prob*100:.1f}% | 비중: {weight*100:.0f}%", "buy") 
                        
                        # 💬 카카오톡 매수 알림 전송
                        self.mw.send_kakao_msg(f"🛒 [주삐 매수 알림]\n종목: {stock_name}\n체결가: {curr_price:,.0f}원\n수량: {buy_qty}주\nAI 확률: {prob*100:.1f}%\n투자비중: {weight*100:.0f}%") 
                        
                        self.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': '매수(BUY)', '주문가격': f"{curr_price:,.0f}", '주문수량': buy_qty, '체결수량': buy_qty, '주문시간': now.strftime("%Y-%m-%d %H:%M:%S"), '상태': '체결완료'})
                        account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': buy_qty, '평균매입가': f"{curr_price:,.0f}", '현재가': f"{curr_price:,.0f}", '평가손익': "0.00%", '주문가능금액': 0})

        if account_rows: account_rows[0]['주문가능금액'] = f"{my_cash:,}" 
        else: account_rows.append({'종목코드': '-', '종목명': '보유종목 없음', '보유수량': 0, '평균매입가': '0', '현재가': '0', '평가손익': '0.00%', '주문가능금액': f"{my_cash:,}"})
        
        acc_cols = ['종목코드','종목명','보유수량','평균매입가','현재가','평가손익','주문가능금액']
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

class FormMain(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        
        # 💬 카카오톡 설정 (토큰만 유지)
        self.KAKAO_TOKEN = "여기에_발급받은_카카오톡_REST_API_토큰을_입력하세요" 

        self.initUI() 
        self.output_logger = OutputLogger(); self.output_logger.emit_log.connect(self.sys_print_to_log)
        sys.stdout = self.output_logger; sys.stderr = self.output_logger 

        current_dir = os.path.dirname(os.path.abspath(__file__)); root_dir = os.path.dirname(current_dir)
        dict_path = os.path.join(root_dir, "stock_dict.csv")
        if os.path.exists(dict_path):
            df_dict = pd.read_csv(dict_path); self.DYNAMIC_STOCK_DICT = dict(zip(df_dict['Code'].astype(str).str.zfill(6), df_dict['Name']))
        else: self.DYNAMIC_STOCK_DICT = {"005930": "삼성전자"} 

        self.strategy_engine = JubbyStrategy(log_callback=self.add_log)

        self.api_manager = KIS_Manager(ui_main=self); self.api_manager.start_api() 
        self.my_holdings = {}; self.last_known_cash = 0 
        self.trade_worker = AutoTradeWorker(main_window=self) 
        self.trade_worker.sig_log.connect(self.add_log)                                
        self.trade_worker.sig_account_df.connect(self.update_account_table_slot)       
        self.trade_worker.sig_strategy_df.connect(self.update_strategy_table_slot)     
        self.trade_worker.sig_sync_cs.connect(self.btnDataSendClickEvent)
        self.trade_worker.sig_order_append.connect(self.append_order_table_slot)            
        self.trade_worker.sig_market_df.connect(self.update_market_table_slot)   
        
        QtCore.QTimer.singleShot(3000, self.load_real_holdings) 
        
        # ⏱️ [추가] 1시간마다 카카오톡 자동 보고 타이머 설정
        self.kakao_timer = QtCore.QTimer(self)
        self.kakao_timer.timeout.connect(self.auto_status_report)
        self.kakao_timer.start(1000 * 60 * 60) # 3600000ms = 1시간마다 실행

    # =====================================================================
    # 💬 [최종 완성] 카카오톡 무한 자동 갱신 전송 시스템
    # =====================================================================
    def send_kakao_msg(self, text):
        # 🚨 여기에 회원님의 카카오 디벨로퍼스 [REST API 키]를 꼭 넣어주세요!
        REST_API_KEY = "4cbe02304c893a129a812045d5f200a3" 
        
        try:
            import json
            # 아까 만든 kakao_token.json 파일 위치 찾기
            token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kakao_token.json")
            
            # 파일 읽어서 토큰 꺼내기
            with open(token_path, "r") as fp:
                tokens = json.load(fp)
            
            url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
            headers = {"Authorization": f"Bearer {tokens['access_token']}"}
            safe_text = text.replace('\n', '\\n').replace('"', '\\"')
            data = {"template_object": '{"object_type": "text", "text": "' + safe_text + '", "link": {}}'}
            
            # 1차 카톡 전송 시도
            res = requests.post(url, headers=headers, data=data)
            
            # 만약 에러가 났다면? (토큰 6시간 수명 만료됨)
            if res.status_code != 200:
                self.add_log("🔄 카카오톡 토큰이 만료되었습니다. 스스로 인공호흡(자동 갱신)을 시작합니다...", "warning")
                
                # 리프레시 토큰으로 새로운 액세스 토큰 발급 받기
                refresh_url = "https://kauth.kakao.com/oauth/token"
                refresh_data = {
                    "grant_type": "refresh_token",
                    "client_id": REST_API_KEY,
                    "refresh_token": tokens["refresh_token"]
                }
                new_token_res = requests.post(refresh_url, data=refresh_data).json()
                
                # 새 생명을 얻은 토큰을 json 파일에 덮어쓰기 (다음번을 위해)
                tokens["access_token"] = new_token_res.get("access_token", tokens["access_token"])
                if "refresh_token" in new_token_res:
                    tokens["refresh_token"] = new_token_res["refresh_token"]
                    
                with open(token_path, "w") as fp:
                    json.dump(tokens, fp)
                    
                # 새 토큰으로 다시 카톡 전송!
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}
                requests.post(url, headers=headers, data=data)
                self.add_log("✅ 카카오톡 토큰 자동 갱신 및 메시지 재전송 성공!", "success")
                
        except Exception as e:
            self.add_log(f"카카오톡 전송/갱신 완전 실패: {e}", "error")

    # =====================================================================
    # ⏱️ 1시간 자동 보고서 브리핑
    # =====================================================================
    def auto_status_report(self):
        my_cash = self.api_manager.get_balance()
        if my_cash is None: my_cash = 0
        
        msg = f"📊 [주삐 정기 보고]\n💰 남은 현금: {my_cash:,}원\n\n[현재 보유 종목]\n"
        
        if len(self.my_holdings) == 0:
            msg += "보유 중인 주식이 없습니다."
        else:
            for code, info in self.my_holdings.items():
                name = self.DYNAMIC_STOCK_DICT.get(code, code)
                df = self.api_manager.fetch_minute_data(code)
                if df is not None and len(df) > 0:
                    profit = ((df.iloc[-1]['close'] - info['price']) / info['price']) * 100
                    msg += f"🔹 {name}: {profit:+.2f}%\n"
                else:
                    msg += f"🔹 {name}: 데이터 대기중\n"
                    
        self.send_kakao_msg(msg)
        self.add_log("💬 카카오톡으로 현재 계좌 현황을 자동 전송했습니다.", "info")

    @QtCore.pyqtSlot(str)
    def sys_print_to_log(self, text): self.add_log(f"🖥️ {text}", "info")

    @QtCore.pyqtSlot(dict)
    def append_order_table_slot(self, order_info):
        ord_cols = ['종목코드','종목명','주문종류','주문가격','주문수량','체결수량','주문시간','상태']
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
        if not TcpJsonClient.Isconnected: return
        
        def clean_num(val): 
            v = str(val).replace(",", "").replace("%", "").strip()
            if v.lower() in ["-", "", "nan", "inf", "-inf", "infinity"]: return "0"
            try:
                float(v)
                return v
            except ValueError:
                return "0"

        if not TradeData.market.df.empty:
            market_list = [] 
            for _, row in TradeData.market.df.iterrows():
                if str(row.get("종목코드", "")) in ["-", ""]: continue
                market_list.append({"symbol": str(row.get("종목코드", "")).zfill(6), "symbol_name": str(row.get("종목명", "")), "last_price": clean_num(row.get("현재가", "0")), "open_price": clean_num(row.get("시가", "0")), "high_price": clean_num(row.get("고가", "0")), "low_price": clean_num(row.get("저가", "0")), "return_1m": clean_num(row.get("1분등락률", "0")), "trade_amount": clean_num(row.get("거래대금", "0")), "vol_energy": clean_num(row.get("거래량에너지", "0")), "disparity": clean_num(row.get("이격도", "0")), "volume": clean_num(row.get("거래량", "0"))})
            if market_list: self.client.send_message("market", market_list)

        if not TradeData.account.df.empty:
            account_list = []
            for _, row in TradeData.account.df.iterrows():
                if str(row.get("종목코드", "")) in ["-", ""]: continue
                
                account_list.append({
                    "symbol": str(row.get("종목코드", "")).zfill(6), 
                    "symbol_name": str(row.get("종목명", "")), 
                    "quantity": clean_num(row.get("보유수량", "0")), 
                    "avg_price": clean_num(row.get("평균매입가", "0")), 
                    "current_price": clean_num(row.get("현재가", "0")), 
                    "pnl": clean_num(row.get("평가손익", "0")), 
                    "available_cash": clean_num(row.get("주문가능금액", "0"))
                })
            if account_list: self.client.send_message("account", account_list)

        if not TradeData.strategy.df.empty:
            strategy_list = []
            for _, row in TradeData.strategy.df.iterrows():
                if str(row.get("종목코드", "")) in ["-", ""]: continue
                sig = str(row.get("전략신호", "")); sig = "BUY" if "BUY" in sig else ("SELL" if "SELL" in sig else ("WAIT" if "WAIT" in sig else sig))
                strategy_list.append({"symbol": str(row.get("종목코드", "")).zfill(6), "symbol_name": str(row.get("종목명", "")), "ma_5": clean_num(row.get("MA_5", "0")), "ma_20": clean_num(row.get("MA_20", "0")), "RSI": clean_num(row.get("RSI", "0")), "macd": clean_num(row.get("MACD", "0")), "signal": sig})
            if strategy_list: self.client.send_message("strategy", strategy_list)

        if not TradeData.order.df.empty:
            order_list = []
            for _, row in TradeData.order.df.iterrows():
                if str(row.get("종목코드", "")) in ["-", ""]: continue
                o_type = str(row.get("주문종류", "")); o_type = "BUY" if "BUY" in o_type else ("SELL_PROFIT" if "SELL_PROFIT" in o_type else "SELL_LOSS")
                order_list.append({"symbol": str(row.get("종목코드", "")).zfill(6), "symbol_name": str(row.get("종목명", "")), "order_type": o_type, "order_price": clean_num(row.get("주문가격", "0")), "order_quantity": clean_num(row.get("주문수량", "0")), "filled_quantity": clean_num(row.get("체결수량", "0")), "order_time": str(row.get("주문시간", "")), "Status": str(row.get("상태", ""))})
            if order_list: self.client.send_message("order", order_list)

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
            self.add_log(f"💼 [잔고 동기화] {len(self.my_holdings)}개 종목 로드 완료.", "success")
        except Exception as e: return
        my_cash = self.api_manager.get_balance(); cash_str = f"{my_cash:,}" if my_cash is not None else "0"
        account_rows = []; is_first = True
        for code, info in self.my_holdings.items():
            buy_price = info['price']; buy_qty = info['qty']; stock_name = self.DYNAMIC_STOCK_DICT.get(code, f"알수없음_{code}")
            
            self.my_holdings[code]['high_watermark'] = buy_price

            df = self.api_manager.fetch_minute_data(code); pnl_str = "0.00%"; curr_price = buy_price
            if df is not None:
                curr_price = df.iloc[-1]['close']; profit_rate = ((curr_price - buy_price) / buy_price) * 100; pnl_str = f"{profit_rate:.2f}%"
                self.my_holdings[code]['high_watermark'] = max(buy_price, curr_price) 
                self.my_holdings[code]['buy_time'] = datetime.now() 
                self.my_holdings[code]['half_sold'] = False
                
            account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': buy_qty, '평균매입가': f"{buy_price:,.0f}", '현재가': f"{curr_price:,.0f}", '평가손익': pnl_str, '주문가능금액': cash_str if is_first else "" })
            is_first = False
        if account_rows: 
            df_acc = pd.DataFrame(account_rows)
            acc_cols = ['종목코드','종목명','보유수량','평균매입가','현재가','평가손익','주문가능금액']
            for c in acc_cols:
                if c not in df_acc.columns: df_acc[c] = ""
            TradeData.account.df = df_acc[acc_cols]
            QtCore.QTimer.singleShot(500, lambda: self.update_table(self.tbAccount, TradeData.account.df))

    def initUI(self):
        uic.loadUi("GUI/Main.ui", self)
        self.client = TcpJsonClient(host="127.0.0.1", port=9001)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint); self.setGeometry(0, 0, 1920, 1080); self.centralwidget.setStyleSheet("background-color: rgb(5,5,15);") 
        self.tbMarket = QtWidgets.QTableWidget(self.centralwidget); self.tbMarket.setGeometry(5, 50, 1420, 240); self._setup_table(self.tbMarket, list(TradeData.market.df.columns))
        self.tbAccount = QtWidgets.QTableWidget(self.centralwidget); self.tbAccount.setGeometry(5, 295, 1420, 240); self._setup_table(self.tbAccount, list(TradeData.account.df.columns))
        self.tbOrder = QtWidgets.QTableWidget(self.centralwidget); self.tbOrder.setGeometry(5, 540, 1420, 240); self._setup_table(self.tbOrder, list(TradeData.order.df.columns))
        self.tbStrategy = QtWidgets.QTableWidget(self.centralwidget); self.tbStrategy.setGeometry(5, 785, 1420, 240); self._setup_table(self.tbStrategy, list(TradeData.strategy.df.columns))
        self.txtLog = QtWidgets.QPlainTextEdit(self.centralwidget); self.txtLog.setGeometry(1430, 95, 485, 930); self.txtLog.setReadOnly(True); self.txtLog.setStyleSheet("background-color: rgb(20, 30, 45); color: white; font-family: Consolas; font-size: 13px;")
        self.btnDataCreatTest = self._create_nav_button("데이터 자동생성 시작", 5); self.btnDataSendTest = self._create_nav_button("C# 데이터 수동전송", 310); self.btnSimulDataTest = self._create_nav_button("계좌 잔고 조회", 615); self.btnAutoDataTest = self._create_nav_button("자동 매매 가동 (GO)", 920); self.btnDataClearTest = self._create_nav_button("화면 데이터 초기화", 1225)
        self.btnClose = QtWidgets.QPushButton(" X ", self.centralwidget); self.btnClose.setGeometry(1875, 5, 40, 40); self.btnClose.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")
        self.btnConnected = QtWidgets.QPushButton("통신 연결 X", self.centralwidget); self.btnConnected.setGeometry(1430, 50, 485, 40); self.btnConnected.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")
        self.btnDataCreatTest.clicked.connect(self.btnDataCreatClickEvent); self.btnDataSendTest.clicked.connect(self.btnDataSendClickEvent); self.btnSimulDataTest.clicked.connect(self.btnSimulTestClickEvent); self.btnAutoDataTest.clicked.connect(self.btnAutoTradingSwitch); self.btnDataClearTest.clicked.connect(self.btnDataClearClickEvent); self.btnClose.clicked.connect(self.btnCloseClickEvent); self.btnConnected.clicked.connect(self.btnConnectedClickEvent)
        self.shortcut_sell = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Shift+W"), self); self.shortcut_sell.activated.connect(self.emergency_sell_event)

    def btnSimulTestClickEvent(self):
        self.add_log("🔄 [수동 조회] 증권사 서버에 계좌 상세 현황을 요청합니다...", "info")
        self.api_manager.check_my_balance() 
        current_cash = self.api_manager.get_balance()
        cash_str = f"{current_cash:,}원" if current_cash is not None else "조회 실패"
        
        if len(self.my_holdings) == 0:
            self.add_log(f"💰 [계좌 잔고 보고] 남은 현금: {cash_str} / 현재 보유 중인 주식이 없습니다.", "warning")
        else:
            self.add_log(f"💰 [계좌 잔고 보고] 남은 현금: {cash_str} / 총 {len(self.my_holdings)}개 종목 분석 결과:", "info")
            
            for code, info in self.my_holdings.items():
                stock_name = self.DYNAMIC_STOCK_DICT.get(code, code)
                buy_price = info['price']
                buy_qty = info['qty']
                
                df = self.api_manager.fetch_minute_data(code)
                if df is not None and len(df) > 0:
                    curr_price = df.iloc[-1]['close']
                    profit_amt = (curr_price - buy_price) * buy_qty 
                    profit_rate = ((curr_price - buy_price) / buy_price) * 100 
                    
                    if profit_amt > 0:
                        status_icon = "🔥 [이득]"; log_type = "success" 
                    elif profit_amt < 0:
                        status_icon = "❄️ [손해]"; log_type = "sell"    
                    else:
                        status_icon = "⚖️ [본전]"; log_type = "info"    

                    msg = (f"   🔹 {stock_name} | {status_icon}\n"
                           f"      - 현재가: {curr_price:,.0f}원 (평단: {buy_price:,.0f}원)\n"
                           f"      - 수익금: {int(profit_amt):+,}원 ({profit_rate:+.2f}%) | 총액: {curr_price * buy_qty:,.0f}원")
                    
                    self.add_log(msg, log_type)
                else:
                    self.add_log(f"   🔹 {stock_name} - 데이터 수신 대기중...", "warning")
                time.sleep(0.05) 

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton and event.modifiers() == Qt.ControlModifier: 
            self.show_algorithm_menu(event.globalPos())
        elif event.button() == Qt.LeftButton: 
            self._isDragging = True
            self._startPos = event.globalPos() - self.frameGeometry().topLeft()

    def show_algorithm_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet("QMenu { background-color: rgb(30, 40, 60); color: white; font-size: 14px; border: 1px solid Silver; } QMenu::item { padding: 10px 25px; } QMenu::item:selected { background-color: rgb(80, 120, 160); }")
        
        act_collect = menu.addAction("📡 Data Collector (1000종목 수집기 실행)")
        act_train = menu.addAction("🧠 Jubby AI Trainer (AI 학습기 실행)")
        act_strategy = menu.addAction("📊 Strategy (전략 엔진 점검)")
        
        menu.addSeparator() 
        act_save_log = menu.addAction("💾 현재 로그 텍스트로 저장 (Save Log)") 

        action = menu.exec_(pos)
        
        if action == act_collect: 
            self.start_data_collector()
        elif action == act_train: 
            self.start_ai_trainer()
        elif action == act_strategy: 
            self.add_log("📊 [Strategy] 15개 다차원 전략 엔진(Strategy.py)이 메인 루프에 정상 연결되어 있습니다.", "success")
        elif action == act_save_log: 
            self.save_manual_log()

    def save_manual_log(self):
        try:
            text = self.txtLog.toPlainText()
            os.makedirs("Logs", exist_ok=True)
            filename = f"Logs/Manual_Log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt" 
            with open(filename, "w", encoding="utf-8") as f: 
                f.write(text)
            self.add_log(f"✅ [저장 성공] 현재 로그가 {filename} 로 캡처되었습니다.", "success")
        except Exception as e:
            self.add_log(f"🚨 [저장 실패] 오류 발생: {e}", "error")

    def start_data_collector(self):
        try:
            if hasattr(self, 'collector_worker') and self.collector_worker.isRunning(): 
                self.add_log("⚠️ 이미 데이터 수집이 진행 중입니다!", "warning")
                return
            
            self.add_log("🚀 거래대금 상위 1000종목 핫플레이스 수집을 백그라운드에서 실행합니다. (1~2시간 소요)", "info")
            
            app_key = getattr(self.api_manager, 'app_key', getattr(self.api_manager, 'APP_KEY', "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"))
            app_secret = getattr(self.api_manager, 'app_secret', getattr(self.api_manager, 'APP_SECRET', "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="))
            account_no = getattr(self.api_manager, 'account_no', getattr(self.api_manager, 'ACCOUNT_NO', "50172151"))
            is_mock = getattr(self.api_manager, 'is_mock', getattr(self.api_manager, 'IS_MOCK', True))

            self.collector_worker = DataCollectorWorker(app_key, app_secret, account_no, is_mock)
            self.collector_worker.sig_log.connect(self.add_log)
            self.collector_worker.start()
        except Exception as e: 
            self.add_log(f"🚨 수집기 실행 준비 중 오류: {e}", "error")

    def start_ai_trainer(self):
        if hasattr(self, 'trainer_worker') and self.trainer_worker.isRunning(): self.add_log("⚠️ 이미 AI 학습이 진행 중입니다!", "warning"); return
        self.add_log("🚀 AI 학습기(Jubby_AI_Trainer.py)를 백그라운드에서 실행합니다...", "info")
        self.trainer_worker = AITrainerWorker(); self.trainer_worker.sig_log.connect(self.add_log); self.trainer_worker.start()
        
    def mouseMoveEvent(self, event):
        if hasattr(self, '_isDragging') and self._isDragging: self.move(event.globalPos() - self._startPos)
    def mouseReleaseEvent(self, event): self._isDragging = False

    def emergency_sell_event(self):
        try:
            selected_ranges = self.tbAccount.selectedRanges() 
            if not selected_ranges: self.add_log("⚠️ 매도할 종목을 'Account 표'에서 클릭한 후 단축키를 눌러주세요.", "warning"); return
            row = selected_ranges[0].topRow(); item = self.tbAccount.item(row, 0)
            if item is None: return
            code = item.text().strip() 
            if code == "-" or not code: return
            if code in self.my_holdings:
                qty = self.my_holdings[code]['qty']; stock_name = self.DYNAMIC_STOCK_DICT.get(code, code)
                self.add_log(f"🚨 [{stock_name}] 비상 탈출 시작! 수량: {qty}주 | 시장가 매도 진행", "send")
                if self.api_manager.sell(code, qty):
                    del self.my_holdings[code]; self.tbAccount.removeRow(row)
                    if hasattr(self, 'trade_worker'): self.trade_worker.sig_order_append.emit({'종목코드': code, '종목명': stock_name, '주문종류': '비상(SELL_LOSS)', '주문가격': '시장가', '주문수량': qty, '체결수량': qty, '주문시간': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '상태': '비상청산완료'})
                    self.add_log(f"✅ [비상 탈출 성공] {stock_name} 전량 매도 완료", "sell"); self.btnDataSendClickEvent()
                else: self.add_log(f"❌ [비상 탈출 실패] 한투 서버가 잔고를 찾지 못함. (코드: {code})", "error")
            else: self.add_log(f"⚠️ 보유 목록에 해당 종목이 없습니다: {code}", "warning")
        except Exception as e: self.add_log(f"🚨 시스템 오류: {e}", "error")

    def btnAutoTradingSwitch(self):
        if not self.trade_worker.is_running: 
            self.trade_worker.start(); self.btnAutoDataTest.setText("자동 매매 중단 (STOP)"); self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 [주삐 엔진] 1분 단위 감시망 가동! 잠시 후 첫 브리핑이 시작됩니다.", "success")
            self.send_kakao_msg("🤖 [주삐 알림] 자동매매 감시망 가동을 시작합니다!") 
        else: 
            self.trade_worker.is_running = False; self.trade_worker.quit(); self.btnAutoDataTest.setText("자동 매매 가동 (GO)"); self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 [주삐 엔진] 감시망을 거둡니다. 푹 쉬세요!", "warning")
            self.send_kakao_msg("🛑 [주삐 알림] 자동매매를 종료합니다. 수고하셨습니다!") 

    # =========================================================================
    # 💡 [핵심 추가] 15개 지표 계산 및 확률 추론을 모두 AI 전략 엔진에 위임합니다!
    # =========================================================================
    def get_ai_probability(self, code):
        df = self.api_manager.fetch_minute_data(code) 
        if df is None or len(df) < 30: return 0.0, 0, None 
        
        # Strategy 엔진을 통해 15개 퀀트 지표를 완벽하게 계산합니다.
        df = self.strategy_engine.calculate_indicators(df)
        curr_price = df.iloc[-1]['close'] 
        
        prob = 0.0
        # AI 뇌가 탑재되어 있다면 확률을 물어봅니다.
        if self.strategy_engine.ai_model is not None:
            features = self.strategy_engine.get_ai_features(df)
            if features is not None:
                prob = self.strategy_engine.ai_model.predict_proba(features)[0][1]
                
        return prob, curr_price, df

    @QtCore.pyqtSlot(object) 
    def update_account_table_slot(self, df): self.update_table(self.tbAccount, df)
    @QtCore.pyqtSlot(object) 
    def update_strategy_table_slot(self, df): self.update_table(self.tbStrategy, df)
    @QtCore.pyqtSlot(str, str) 
    def add_log(self, text, log_type="info"):
        color = {"info": "white", "success": "lime", "warning": "yellow", "error": "red", "send": "cyan", "recv": "orange", "buy": "#4B9CFF", "sell": "#FF4B4B"}.get(log_type, "white")
        html_message = f'<span style="color:{color}">{datetime.now().strftime("[%H:%M:%S]")} {text}</span>'
        QtCore.QTimer.singleShot(0, lambda: self._safe_append_log(html_message))

    def _safe_append_log(self, html_msg):
        self.txtLog.appendHtml(html_msg); self.txtLog.verticalScrollBar().setValue(self.txtLog.verticalScrollBar().maximum())

    def _setup_table(self, table, columns): table.setColumnCount(len(columns)); table.setHorizontalHeaderLabels(columns); self.style_table(table)
    def style_table(self, table): table.setFont(QtGui.QFont("Noto Sans KR", 12)); table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch); table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows); table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection); table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers); table.setStyleSheet("QTableWidget { background-color: rgb(50,80,110); color: Black; selection-background-color: rgb(80, 120, 160); } QHeaderView::section { background-color: rgb(40,60,90); color: Black; font-weight: bold; }")
    def _create_nav_button(self, text, x_pos): btn = QtWidgets.QPushButton(text, self.centralwidget); btn.setGeometry(x_pos, 5, 300, 40); btn.setStyleSheet("background-color: rgb(5,5,15); color: Silver;"); btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor)); btn.installEventFilter(self); return btn
    def eventFilter(self, source, event):
        if event.type() == QtCore.QEvent.Enter: source.setStyleSheet("background-color: rgb(5,5,10); color: Lime;")
        elif event.type() == QtCore.QEvent.Leave: source.setStyleSheet("background-color: rgb(5,5,10); color: Silver;")
        return super().eventFilter(source, event)
    def btnCloseClickEvent(self): QtWidgets.QApplication.quit()          
    def btnDataCreatClickEvent(self):
        if hasattr(self, 'mock_data_timer') and self.mock_data_timer.isActive(): self.mock_data_timer.stop(); self.btnDataCreatTest.setText("데이터 자동생성 시작"); self.btnDataCreatTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;"); self.add_log("🛑 실시간 가짜 데이터 전송을 멈춥니다.", "warning")
        else:
            if not hasattr(self, 'mock_data_timer'): self.mock_data_timer = QtCore.QTimer(self); self.mock_data_timer.timeout.connect(self.generate_and_send_mock_data)
            self.mock_data_timer.start(1000); self.btnDataCreatTest.setText("데이터 자동생성 중지 (STOP)"); self.btnDataCreatTest.setStyleSheet("background-color: rgb(10, 70, 10); color: Lime; font-weight: bold;"); self.add_log("🚀 1초마다 가짜 데이터를 C#으로 연속 발사합니다!", "success")
    def generate_and_send_mock_data(self): TradeData.market.generate_mock_data(); TradeData.account.generate_mock_data(); TradeData.order.generate_mock_data(); TradeData.strategy.generate_mock_data(); self.update_table(self.tbMarket, TradeData.market.df); self.update_table(self.tbAccount, TradeData.account.df); self.update_table(self.tbOrder, TradeData.order.df); self.update_table(self.tbStrategy, TradeData.strategy.df); self.btnDataSendClickEvent()
    
    def update_table(self, tableWidget, df):
        tableWidget.setUpdatesEnabled(False); current_row_count = tableWidget.rowCount(); new_row_count = len(df)                    
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
    
    def btnConnectedClickEvent(self):
        if TcpJsonClient.Isconnected: 
            self.client.close()
            TcpJsonClient.Isconnected = False
            self.btnConnected.setText("통신 연결 X")
            self.btnConnected.setStyleSheet("color: Silver;")
            self.add_log("🔌 [시스템] C# 프로그램과의 통신 연결을 수동으로 해제했습니다.", "warning")
        else:
            self.add_log("🔄 [시스템] C# 프로그램과 연결을 시도합니다...", "info")
            self.client.connect()
            if TcpJsonClient.Isconnected: 
                self.btnConnected.setText("통신 연결 O")
                self.btnConnected.setStyleSheet("color: Lime;")
                self.add_log("✅ [시스템] C# 프로그램과 성공적으로 연결되었습니다!", "success")
                self.btnDataSendClickEvent() 
            else:
                self.add_log("❌ [시스템] C# 프로그램 연결에 실패했습니다. 서버가 열려있는지 확인하세요.", "error")