import sys
import os                  
import time                
import random              
import joblib              
import pandas as pd        
import numpy as np         
from datetime import datetime 
from PyQt5 import QtWidgets, uic, QtCore, QtGui  
from PyQt5.QtCore import Qt, QThread, pyqtSignal 

from COMMON.Flag import TradeData            
from COM.TcpJsonClient import TcpJsonClient  
from COMMON.KIS_Manager import KIS_Manager   

STOCK_DICT = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "005380": "현대차", "000270": "기아", "068270": "셀트리온",
    "005490": "POSCO홀딩스", "035420": "NAVER", "035720": "카카오",
    "000810": "삼성화재", "051910": "LG화학", "105560": "KB금융",
    "012330": "현대모비스", "032830": "삼성생명", "055550": "신한지주",
    "003550": "LG", "000100": "유한양행", "033780": "KT&G",
    "009150": "삼성전기", "015760": "한국전력"
}

class OutputLogger(QtCore.QObject):
    emit_log = QtCore.pyqtSignal(str)
    def write(self, text):
        if text.strip(): self.emit_log.emit(text.strip())
    def flush(self): pass

class DataCollectorWorker(QThread):
    sig_log = pyqtSignal(str, str)
    def __init__(self, app_key, app_secret, account_no, is_mock):
        super().__init__()
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.is_mock = is_mock

    def run(self):
        try:
            from TRADE.Argorism.Data_Collector import UltraDataCollector
            stock_list = [
                "005930", "000660", "373220", "005380", "000270", "068270", "005490", "035420", "035720", "000810",
                "051910", "105560", "012330", "032830", "055550", "003550", "000100", "033780", "009150", "015760",
                "018260", "011780", "010130", "010950", "323410", "000720", "086790", "034220", "003670", "034730",
                "090430", "096770", "003470", "011070", "006400", "267250", "024110", "005830", "004020", "011170",
                "071050", "000080", "000670", "008770", "007070", "002380", "036570", "009830", "005935", "004170",
                "010120", "000120", "028260", "000150", "011210", "001450", "003490", "030000", "001040", "078930",
                "021240", "023530", "086280", "138040", "005440", "047040", "047050", "009540", "000990", "006800",
                "005387", "001520", "016360", "042700", "000210", "002790", "010620", "000100", "001230", "003000",
                "086520", "091990", "247540", "066970", "293490", "035900", "058470", "253450", "067160", "028300",
                "036830", "039200", "041510", "046890", "066570", "084850", "086900", "131970", "278280", "011200",
                "259960", "032640", "271560", "068240", "112040", "001440", "139480", "052690", "032500", "003160",
                "128940", "006280", "014680", "000240", "214150", "012510", "175330", "042660", "020150", "010140",
                "001800", "010060", "011280", "161890", "004000", "060150", "034020", "042670", "192820", "028050",
                "001430", "051900", "005389", "000030", "012630", "019680", "298050", "029780", "298020", "001120",
                "004990", "316140", "000880", "053280", "011930", "093370", "103140", "002240", "008930", "012450",
                "017800", "005250", "031430", "009240", "000155", "006360", "000270", "011000", "282330", "302440",
                "007310", "241560", "006260", "011790", "272210", "002320", "003230", "014820", "137310", "006840",
                "383220", "000815", "047810", "002960", "064350", "204320", "097950", "069960", "067280", "081660",
                "005850", "000157", "042660", "213420", "138930", "145020", "121440", "352820", "095660", "022100",
                "180640", "007390", "030200", "263750", "111770", "009420", "004490", "008560", "013890", "016380"
            ]
            collector = UltraDataCollector(self.app_key, self.app_secret, self.account_no, self.is_mock, log_callback=self.emit_log)
            collector.run_collection(stock_list)
        except Exception as e:
            self.emit_log(f"🚨 수집기 실행 오류: {e}", "error")

    def emit_log(self, msg, level="info"):
        self.sig_log.emit(msg, level)


class AITrainerWorker(QThread):
    sig_log = pyqtSignal(str, str)
    def run(self):
        try:
            from TRADE.Argorism.Jubby_AI_Trainer import train_jubby_brain
            train_jubby_brain(log_callback=self.emit_log)
        except Exception as e:
            self.emit_log(f"🚨 AI 학습기 실행 오류: {e}", "error")

    def emit_log(self, msg, level="info"):
        self.sig_log.emit(msg, level)


class AutoTradeWorker(QThread):
    sig_log = pyqtSignal(str, str)             
    sig_account_df = pyqtSignal(object)        
    sig_strategy_df = pyqtSignal(object)       
    sig_market_df = pyqtSignal(object)         
    sig_sync_cs = pyqtSignal()                 
    sig_order_append = pyqtSignal(dict)        

    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window   
        self.is_running = False 
        self.cumulative_realized_profit = 0 

    def run(self):
        self.is_running = True
        while self.is_running:
            self.process_trading() 
            for _ in range(60):
                if not self.is_running: break 
                time.sleep(1)

    def execute_guaranteed_sell(self, code, qty, current_price):
        max_retries = 3 
        target_price = current_price
        for attempt in range(max_retries):
            success = self.mw.api_manager.sell(code, qty) 
            if success:
                return True
            target_price = int(target_price * 0.995)
            self.sig_log.emit(f"⚠️ [{code}] 매도 미체결. 호가를 낮춰 재시도... ({attempt+1}/{max_retries})", "warning")
            time.sleep(1.0) 
            
        self.sig_log.emit(f"🚨 [{code}] 3회 매도 실패! 시장가 강제 청산.", "error")
        success = self.mw.api_manager.sell(code, qty) 
        return success

    def process_trading(self):
        now = datetime.now() 
        self.sig_log.emit(f"🔄 [주삐 엔진 가동중] {now.strftime('%H:%M')} - 매도 감시 및 타겟 스캔 중...", "info")

        MAX_STOCKS = 10     
        TAKE_PROFIT = 3.0   
        STOP_LOSS = -2.0    
        SCAN_POOL = list(STOCK_DICT.keys()) 

        account_rows = [] 
        market_rows = []  
        strategy_rows = [] # 💡 [추가] 4번째 탭(Strategy)을 위한 그릇입니다!
        
        total_invested = 0     
        total_current_val = 0  

        # =====================================================================
        # 🔍 1. 보유 종목 스캔 (매도 로직)
        # =====================================================================
        if len(self.mw.my_holdings) > 0: 
            sold_codes = [] 
            hold_status_list = [] 
            
            for code, info in self.mw.my_holdings.items():
                buy_price = info['price'] 
                buy_qty = info['qty']     
                stock_name = STOCK_DICT.get(code, f"알수없음_{code}")
                
                df = self.mw.api_manager.fetch_minute_data(code)
                
                if df is None or len(df) < 30: 
                    hold_status_list.append(f"[{stock_name}: 데이터 수신 대기중⏳]")
                    account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': buy_qty, '평균매입가': f"{buy_price:,.0f}", '평가손익': "확인중", '주문가능금액': 0})
                    continue 
                
                curr_price = df.iloc[-1]['close'] 
                profit_rate = ((curr_price - buy_price) / buy_price) * 100 
                
                total_invested += (buy_price * buy_qty)
                total_current_val += (curr_price * buy_qty)

                curr_open = float(df.iloc[-1].get('open', curr_price))
                curr_high = float(df.iloc[-1].get('high', curr_price))
                curr_low = float(df.iloc[-1].get('low', curr_price))

                # 💡 [표 데이터 삽입] 1. Market 시세 표
                market_rows.append({
                    '종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.0f}",
                    '시가': f"{curr_open:,.0f}", '고가': f"{curr_high:,.0f}", '저가': f"{curr_low:,.0f}",
                    '매수호가': 0, '매도호가': 0, '매수잔량': 0, '매도잔량': 0, '거래량': f"{df.iloc[-1]['volume']:,.0f}"
                })

                # 지표 계산
                df['MA5'] = df['close'].rolling(5).mean()
                df['MA20'] = df['close'].rolling(20).mean()
                delta = df['close'].diff()
                up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
                df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.ewm(com=13).mean())))
                df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
                df['Signal'] = df['MACD'].ewm(span=9).mean()
                
                curr_macd = df.iloc[-1]['MACD']
                curr_signal = df.iloc[-1]['Signal']

                is_sell = False 
                status_msg = "" 

                if now.hour == 15 and now.minute >= 10:
                    is_sell = True
                    status_msg = f"마감 임박 청산"
                elif now.hour == 15 and 0 <= now.minute < 10:
                    if profit_rate >= 0.3:
                        is_sell = True
                        status_msg = f"수수료 방어 마감 익절"
                    elif profit_rate > 0.0 and curr_macd < curr_signal:
                        is_sell = True
                        status_msg = f"마감 전 추세꺾임 탈출"
                    elif profit_rate <= STOP_LOSS:
                        is_sell = True
                        status_msg = f"마감 전 기계적 손절"
                else:
                    if profit_rate >= TAKE_PROFIT:     
                        is_sell = True
                        status_msg = f"기계적 목표가 익절"
                    elif profit_rate <= STOP_LOSS:     
                        is_sell = True
                        status_msg = f"기계적 리스크 손절"
                    elif profit_rate > 2.0 and curr_macd < curr_signal: 
                        is_sell = True
                        status_msg = f"데드크로스 수익보존 탈출"

                if is_sell:
                    success = self.execute_guaranteed_sell(code, buy_qty, curr_price) 
                    if success: 
                        sold_codes.append(code) 
                        realized_profit = (curr_price - buy_price) * buy_qty
                        self.cumulative_realized_profit += realized_profit
                        
                        sell_msg = (f"🔴 [매도 체결 성공] {stock_name} | 매도가: {curr_price:,.0f}원 | "
                                    f"수량: {buy_qty}주 | 실현 손익: {int(realized_profit):,}원 ({profit_rate:.2f}%) | 사유: {status_msg}")
                        self.sig_log.emit(sell_msg, "sell") 
                        
                        # 💡 [표 데이터 삽입] 3. Order 주문 내역 표 (Flag.py 한글명칭에 맞춤)
                        order_info = {
                            '종목코드': code, '종목명': stock_name, '주문종류': '매도(SELL)', 
                            '주문가격': f"{curr_price:,.0f}", '주문수량': buy_qty, '체결수량': buy_qty, 
                            '주문시간': now.strftime("%Y-%m-%d %H:%M:%S"), '상태': '체결완료'
                        }
                        self.sig_order_append.emit(order_info)
                else:
                    # 💡 [표 데이터 삽입] 2. Account 계좌 표
                    account_rows.append({
                        '종목코드': code, '종목명': stock_name, '보유수량': buy_qty, 
                        '평균매입가': f"{buy_price:,.0f}", '평가손익': f"{profit_rate:.2f}%", '주문가능금액': 0
                    })
                    hold_status_list.append(f"[{stock_name}: {profit_rate:.2f}%]") 

                # 💡 [표 데이터 삽입] 4. Strategy 전략 현황 표 (보유 종목도 모니터링!)
                strategy_rows.append({
                    '종목코드': code, '종목명': stock_name, '상승확률': '-', 
                    'MA_5': f"{df.iloc[-1]['MA5']:.0f}", 'MA_20': f"{df.iloc[-1]['MA20']:.0f}", 
                    'RSI': f"{df.iloc[-1]['RSI']:.1f}", 'MACD': f"{curr_macd:.2f}", '전략신호': '보유중'
                })
                    
            for code in sold_codes:
                del self.mw.my_holdings[code]

            if len(hold_status_list) > 0:
                self.sig_log.emit(f"🔒 [매도 보류 현황] 총 {len(hold_status_list)}개 종목 관망 유지", "info")
                for i in range(0, len(hold_status_list), 4):
                    chunk = " / ".join(hold_status_list[i:i+4])
                    self.sig_log.emit(f"   👉 {chunk}", "info")
                
            if total_invested > 0 or self.cumulative_realized_profit != 0:
                total_profit = total_current_val - total_invested 
                total_profit_rate = (total_profit / total_invested) * 100 if total_invested > 0 else 0.0
                pnl_color = "success" if total_profit > 0 else "warning" if total_profit < 0 else "info"
                summary_msg = (f"📊 [현재 계좌 종합] 총 투자금: {int(total_invested):,}원 | "
                               f"현재 평가손익: {int(total_profit):,}원 ({total_profit_rate:.2f}%) | "
                               f"💰 누적 실현손익: {int(self.cumulative_realized_profit):,}원")
                self.sig_log.emit(summary_msg, pnl_color)

        # =====================================================================
        # 🛒 2. 신규 종목 스캔 (매수 로직 및 AI 분석표 삽입)
        # =====================================================================
        current_count = len(self.mw.my_holdings) 
        needed_count = MAX_STOCKS - current_count 
        
        api_cash = self.mw.api_manager.get_balance()
        my_cash = api_cash if api_cash is not None else getattr(self.mw, 'last_known_cash', 0)
        self.mw.last_known_cash = my_cash 
        cash_str = f"{my_cash:,}" 
        
        if now.hour >= 15:
            self.sig_log.emit("⏰ [쇼핑 종료] 오후 3시가 넘었습니다. 신규 매수를 전면 차단합니다.", "error")
        else:
            if needed_count > 0:
                total_asset = my_cash + sum([info['price'] * info['qty'] for info in self.mw.my_holdings.values()])
                BUDGET_PER_STOCK = int(total_asset * 0.1)

                candidates = [] 
                best_prob = 0.0 
                best_stock_name = ""

                # 스캔 대상(관심종목)을 무작위로 10개만 뽑아서 봅니다 (API 과부하 방지)
                scan_targets = random.sample(SCAN_POOL, min(10, len(SCAN_POOL)))

                for code in scan_targets:
                    if code in self.mw.my_holdings: continue 
                    
                    prob, curr_price, df_feat = self.mw.get_ai_probability(code)

                    if prob == -1.0:
                        self.sig_log.emit("🚨 [비상] AI 뇌(pkl)를 찾을 수 없습니다! 랜덤 매수를 차단합니다.", "error")
                        candidates = [] 
                        break 

                    stock_name = STOCK_DICT.get(code, code) 
                    
                    # 💡 [표 데이터 삽입] 1. Market 시세 표 (관심종목 띄우기)
                    market_rows.append({
                        '종목코드': code, '종목명': stock_name, '현재가': f"{curr_price:,.0f}",
                        '시가': f"{curr_price:,.0f}", '고가': f"{curr_price:,.0f}", '저가': f"{curr_price:,.0f}",
                        '매수호가': 0, '매도호가': 0, '매수잔량': 0, '매도잔량': 0, '거래량': '-'
                    })

                    # 💡 [표 데이터 삽입] 4. Strategy 표 (AI 예측값 띄우기!)
                    if df_feat is not None:
                        signal_str = "BUY 🟢" if prob >= 0.6 else "WAIT 🟡"
                        strategy_rows.append({
                            '종목코드': code, '종목명': stock_name, '상승확률': f"{prob*100:.1f}%", 
                            'MA_5': f"{df_feat.iloc[-1]['MA5']:.0f}", 'MA_20': f"{df_feat.iloc[-1]['MA20']:.0f}", 
                            'RSI': f"{df_feat.iloc[-1]['RSI']:.1f}", 'MACD': f"{df_feat.iloc[-1]['MACD']:.2f}", 
                            '전략신호': signal_str
                        })

                    if prob > best_prob:
                        best_prob = prob
                        best_stock_name = stock_name

                    if prob >= 0.6: candidates.append({'code': code, 'prob': prob, 'price': curr_price})
                    time.sleep(0.2) 
                
                if len(candidates) == 0:
                    self.sig_log.emit(f"🤔 [매수 보류] AI 상승확률 60% 통과 종목 없음. (현재 1위: {best_stock_name} {best_prob*100:.1f}%)", "warning")
                else:
                    candidates = sorted(candidates, key=lambda x: x['prob'], reverse=True)

                    for i in range(min(needed_count, len(candidates))):
                        target = candidates[i]
                        code = target['code']
                        curr_price = target['price']
                        stock_name = STOCK_DICT.get(code, code) 
                        buy_qty = int(BUDGET_PER_STOCK / curr_price) 
                        
                        if buy_qty > 0:
                            success = self.mw.api_manager.buy_market_price(code, buy_qty)
                            if success:
                                self.mw.my_holdings[code] = {'price': curr_price, 'qty': buy_qty}
                                buy_msg = (f"🔵 [매수 체결 성공] {stock_name} | 매수가: {curr_price:,.0f}원 | "
                                           f"수량: {buy_qty}주 | 총 체결금액: {curr_price * buy_qty:,.0f}원 | AI 예측확률: {target['prob']*100:.1f}%")
                                self.sig_log.emit(buy_msg, "buy") 
                                
                                # 💡 [표 데이터 삽입] 3. Order 표
                                order_info = {
                                    '종목코드': code, '종목명': stock_name, '주문종류': '매수(BUY)', 
                                    '주문가격': f"{curr_price:,.0f}", '주문수량': buy_qty, '체결수량': buy_qty, 
                                    '주문시간': now.strftime("%Y-%m-%d %H:%M:%S"), '상태': '체결완료'
                                }
                                self.sig_order_append.emit(order_info)

                                # 💡 [표 데이터 삽입] 2. Account 표
                                account_rows.append({
                                    '종목코드': code, '종목명': stock_name, '보유수량': buy_qty, 
                                    '평균매입가': f"{curr_price:,.0f}", '평가손익': "0.00%", '주문가능금액': 0
                                })

        # ---------------------------------------------------------------------
        # 📤 모든 데이터 취합 후 한방에 UI로 발사!
        # ---------------------------------------------------------------------
        if len(account_rows) > 0:
            account_rows[0]['주문가능금액'] = cash_str 
        else:
            account_rows.append({'종목코드': '-', '종목명': '보유종목 없음', '보유수량': 0, '평균매입가': '0', '평가손익': '0.00%', '주문가능금액': cash_str})
        
        self.sig_account_df.emit(pd.DataFrame(account_rows)) 
        
        if len(market_rows) > 0:
            self.sig_market_df.emit(pd.DataFrame(market_rows))
            
        if len(strategy_rows) > 0:
            self.sig_strategy_df.emit(pd.DataFrame(strategy_rows))
            
        self.sig_sync_cs.emit()


# =====================================================================
# 🖥️ 메인 UI 클래스 (FormMain) - 주삐 프로젝트의 지휘통제실!
# =====================================================================
class FormMain(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI() 
        
        self.output_logger = OutputLogger()
        self.output_logger.emit_log.connect(self.sys_print_to_log)
        sys.stdout = self.output_logger 
        sys.stderr = self.output_logger 

        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.dirname(current_dir)
            cwd_dir = os.getcwd()

            MODEL_FILENAME = "jubby_brain.pkl"
            candidate_paths = [
                os.path.join(cwd_dir, MODEL_FILENAME),
                os.path.join(root_dir, MODEL_FILENAME),
                os.path.join(current_dir, MODEL_FILENAME)
            ]

            self.model = None
            for path in candidate_paths:
                if os.path.exists(path):
                    self.model = joblib.load(path)
                    self.add_log(f"✅ [주삐 뇌 이식 성공] AI 모델을 완벽하게 찾아냈습니다! : {path}", "success")
                    break
            
            if self.model is None:
                self.add_log(f"🚨 [경로 오류] 모델 탐색 실패 (1.{candidate_paths[0]} / 2.{candidate_paths[1]})", "error")
                
        except Exception as e:
            self.model = None
            self.add_log(f"🚨 [치명적 오류] AI 모델을 읽는 중 에러 발생: {e}", "error")

        self.api_manager = KIS_Manager(ui_main=self) 
        self.api_manager.start_api() 

        self.my_holdings = {} 
        self.last_known_cash = 0 
        
        self.trade_worker = AutoTradeWorker(main_window=self) 
        
        self.trade_worker.sig_log.connect(self.add_log)                                
        self.trade_worker.sig_account_df.connect(self.update_account_table_slot)       
        self.trade_worker.sig_strategy_df.connect(self.update_strategy_table_slot)     
        self.trade_worker.sig_sync_cs.connect(self.btnDataSendClickEvent) 
        self.trade_worker.sig_order_append.connect(self.append_order_table_slot)            
        self.trade_worker.sig_market_df.connect(self.update_market_table_slot)   

        QtCore.QTimer.singleShot(3000, self.load_real_holdings) 

    @QtCore.pyqtSlot(str)
    def sys_print_to_log(self, text):
        self.add_log(f"🖥️ {text}", "info")

    @QtCore.pyqtSlot(dict)
    def append_order_table_slot(self, order_info):
        new_row = pd.DataFrame([order_info])
        if TradeData.order.df.empty:
            TradeData.order.df = new_row
        else:
            TradeData.order.df = pd.concat([TradeData.order.df, new_row], ignore_index=True)

        MAX_ROWS = 500
        if len(TradeData.order.df) > MAX_ROWS:
            TradeData.order.df = TradeData.order.df.iloc[-MAX_ROWS:].reset_index(drop=True)

        row_idx = self.tbOrder.rowCount()
        self.tbOrder.insertRow(row_idx) 
        
        # 💡 [핵심 수정] Flag.py에 맞춰 8개의 한글 기둥(Columns)을 기준으로 표에 넣습니다!
        cols = list(TradeData.order.df.columns) 
        for col_idx, key in enumerate(cols):
            val = str(order_info.get(key, ''))
            item = QtWidgets.QTableWidgetItem(val)
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.tbOrder.setItem(row_idx, col_idx, item)

        if self.tbOrder.rowCount() > MAX_ROWS:
            self.tbOrder.removeRow(0)
            
        self.tbOrder.scrollToBottom() 
        self.btnDataSendClickEvent()

    @QtCore.pyqtSlot() 
    def btnDataSendClickEvent(self):
        if TcpJsonClient.Isconnected:
            self.client.send_message("market", TradeData.market_dict())
            self.client.send_message("account", TradeData.account_dict())
            self.client.send_message("strategy", TradeData.strategy_dict())
            self.client.send_message("order", TradeData.order_dict())

    @QtCore.pyqtSlot(object) 
    def update_market_table_slot(self, df):
        standard_cols = ['종목코드','종목명','현재가','시가','고가','저가','매수호가','매도호가','매수잔량','매도잔량','거래량']
        if df.empty:
            TradeData.market.df = pd.DataFrame(columns=standard_cols)
            return

        if '종목코드' not in df.columns:
            if 'Symbol' in df.columns:
                df = df.rename(columns={'Symbol': '종목코드', 'Name': '종목명', 'Price': '현재가'})

        for col in standard_cols:
            if col not in df.columns:
                df[col] = 0
                
        TradeData.market.df = df[standard_cols]
        self.update_table(self.tbMarket, TradeData.market.df)

    def load_real_holdings(self):
        try:
            self.my_holdings = self.api_manager.get_real_holdings()
            self.add_log(f"💼 [잔고 동기화] {len(self.my_holdings)}개 종목 로드 완료.", "success")
        except Exception as e:
            self.add_log(f"⚠️ 잔고 로드 에러: {e}", "error")
            return

        my_cash = self.api_manager.get_balance()
        cash_str = f"{my_cash:,}" if my_cash is not None else "0"

        account_rows = []
        is_first = True
        
        for code, info in self.my_holdings.items():
            buy_price = info['price']
            buy_qty = info['qty']
            stock_name = STOCK_DICT.get(code, f"알수없음_{code}")
            
            df = self.api_manager.fetch_minute_data(code)
            pnl_str = "0.00%"
            if df is not None:
                curr_price = df.iloc[-1]['close']
                profit_rate = ((curr_price - buy_price) / buy_price) * 100
                pnl_str = f"{profit_rate:.2f}%"

            account_rows.append({
                '종목코드': code, '종목명': stock_name, '보유수량': buy_qty, 
                '평균매입가': f"{buy_price:,.0f}", '평가손익': pnl_str,
                '주문가능금액': cash_str if is_first else "" 
            })
            is_first = False
            
        if account_rows:
            TradeData.account.df = pd.DataFrame(account_rows)
            QtCore.QTimer.singleShot(500, lambda: self.update_table(self.tbAccount, TradeData.account.df))

    def initUI(self):
        uic.loadUi("GUI/Main.ui", self)
        self.client = TcpJsonClient(host="127.0.0.1", port=9001)

        self.setWindowFlags(QtCore.Qt.FramelessWindowHint) 
        self.setGeometry(0, 0, 1920, 1080) 
        self.centralwidget.setStyleSheet("background-color: rgb(5,5,15);") 

        self.tbMarket = QtWidgets.QTableWidget(self.centralwidget)
        self.tbMarket.setGeometry(5, 50, 1420, 240)
        self._setup_table(self.tbMarket, list(TradeData.market.df.columns))

        self.tbAccount = QtWidgets.QTableWidget(self.centralwidget)
        self.tbAccount.setGeometry(5, 295, 1420, 240)
        self._setup_table(self.tbAccount, list(TradeData.account.df.columns))

        self.tbOrder = QtWidgets.QTableWidget(self.centralwidget)
        self.tbOrder.setGeometry(5, 540, 1420, 240)
        self._setup_table(self.tbOrder, list(TradeData.order.df.columns))

        self.tbStrategy = QtWidgets.QTableWidget(self.centralwidget)
        self.tbStrategy.setGeometry(5, 785, 1420, 240)
        self._setup_table(self.tbStrategy, list(TradeData.strategy.df.columns))

        self.txtLog = QtWidgets.QPlainTextEdit(self.centralwidget)
        self.txtLog.setGeometry(1430, 95, 485, 930)
        self.txtLog.setReadOnly(True) 
        self.txtLog.setStyleSheet("background-color: rgb(20, 30, 45); color: white; font-family: Consolas; font-size: 13px;")

        self.btnDataCreatTest = self._create_nav_button("데이터 자동생성 시작", 5)
        self.btnDataSendTest = self._create_nav_button("C# 데이터 수동전송", 310)
        self.btnSimulDataTest = self._create_nav_button("계좌 잔고 조회", 615)
        self.btnAutoDataTest = self._create_nav_button("자동 매매 가동 (GO)", 920)
        self.btnDataClearTest = self._create_nav_button("화면 데이터 초기화", 1225)
        
        self.btnClose = QtWidgets.QPushButton(" X ", self.centralwidget)
        self.btnClose.setGeometry(1875, 5, 40, 40)
        self.btnClose.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")

        self.btnConnected = QtWidgets.QPushButton("통신 연결 X", self.centralwidget)
        self.btnConnected.setGeometry(1430, 50, 485, 40)
        self.btnConnected.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")

        self.btnDataCreatTest.clicked.connect(self.btnDataCreatClickEvent)
        self.btnDataSendTest.clicked.connect(self.btnDataSendClickEvent)
        self.btnSimulDataTest.clicked.connect(self.btnSimulTestClickEvent)
        self.btnAutoDataTest.clicked.connect(self.btnAutoTradingSwitch)
        self.btnDataClearTest.clicked.connect(self.btnDataClearClickEvent)
        self.btnClose.clicked.connect(self.btnCloseClickEvent)
        self.btnConnected.clicked.connect(self.btnConnectedClickEvent)

        self.shortcut_sell = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Shift+W"), self)
        self.shortcut_sell.activated.connect(self.emergency_sell_event)


    def btnSimulTestClickEvent(self):
        self.add_log("🔄 [수동 조회] 증권사 서버에 계좌 현황을 요청합니다...", "info")
        self.api_manager.check_my_balance() 
        current_cash = self.api_manager.get_balance()
        cash_str = f"{current_cash:,}원" if current_cash is not None else "조회 실패"
        
        if len(self.my_holdings) == 0:
            self.add_log(f"💰 [계좌 잔고 보고] 남은 현금: {cash_str} / 현재 보유 중인 주식이 하나도 없습니다! (텅텅)", "warning")
        else:
            self.add_log(f"💰 [계좌 잔고 보고] 남은 현금: {cash_str} / 총 {len(self.my_holdings)}개 종목 보유 중:", "success")
            for code, info in self.my_holdings.items():
                stock_name = STOCK_DICT.get(code, code)
                buy_price = info['price']
                buy_qty = info['qty']
                total_value = buy_price * buy_qty
                self.add_log(f"   🔹 {stock_name} - {buy_qty}주 (평단가: {buy_price:,.0f}원 / 총액: {total_value:,.0f}원)", "success")
                time.sleep(0.05) 

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton and event.modifiers() == Qt.ControlModifier:
            self.show_algorithm_menu(event.globalPos())
            
        elif event.button() == Qt.LeftButton and event.modifiers() == Qt.ControlModifier:
            text = self.txtLog.toPlainText() 
            if not text.strip(): return 
            os.makedirs("Logs", exist_ok=True) 
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S") 
            filename = f"Logs/Manual_Log_{now_str}.txt" 
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            self.add_log(f"💾 [저장 성공] 현재 로그가 {filename} 로 캡처되었습니다.", "success")
            
        elif event.button() == Qt.LeftButton:
            self._isDragging = True
            self._startPos = event.globalPos() - self.frameGeometry().topLeft()

    def show_algorithm_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: rgb(30, 40, 60); color: white; font-size: 14px; border: 1px solid Silver; }
            QMenu::item { padding: 10px 25px; }
            QMenu::item:selected { background-color: rgb(80, 120, 160); }
        """)
        
        act_collect = menu.addAction("📡 Data Collector (데이터 수집기 실행)")
        act_train = menu.addAction("🧠 Jubby AI Trainer (AI 학습기 실행)")
        act_strategy = menu.addAction("📊 Strategy (전략 엔진 점검)")
        
        action = menu.exec_(pos)
        
        if action == act_collect:
            self.start_data_collector()
        elif action == act_train:
            self.start_ai_trainer()
        elif action == act_strategy:
            self.add_log("📊 [Strategy] 13개 다차원 전략 엔진(Strategy.py)이 메인 루프에 정상 연결되어 있습니다.", "success")

    def start_data_collector(self):
        if hasattr(self, 'collector_worker') and self.collector_worker.isRunning():
            self.add_log("⚠️ 이미 데이터 수집이 진행 중입니다!", "warning")
            return
            
        self.add_log("🚀 데이터 수집기(Data_Collector.py)를 백그라운드에서 실행합니다...", "info")
        self.collector_worker = DataCollectorWorker(
            self.api_manager.APP_KEY, 
            self.api_manager.APP_SECRET, 
            self.api_manager.ACCOUNT_NO, 
            self.api_manager.IS_MOCK
        )
        self.collector_worker.sig_log.connect(self.add_log)
        self.collector_worker.start()

    def start_ai_trainer(self):
        if hasattr(self, 'trainer_worker') and self.trainer_worker.isRunning():
            self.add_log("⚠️ 이미 AI 학습이 진행 중입니다!", "warning")
            return
            
        self.add_log("🚀 AI 학습기(Jubby_AI_Trainer.py)를 백그라운드에서 실행합니다...", "info")
        self.trainer_worker = AITrainerWorker()
        self.trainer_worker.sig_log.connect(self.add_log)
        self.trainer_worker.start()
        
    def mouseMoveEvent(self, event):
        if hasattr(self, '_isDragging') and self._isDragging: 
            self.move(event.globalPos() - self._startPos)
        
    def mouseReleaseEvent(self, event): 
        self._isDragging = False

    def emergency_sell_event(self):
        selected_ranges = self.tbAccount.selectedRanges() 
        if not selected_ranges:
            self.add_log("⚠️ 매도할 종목을 'Account 표'에서 클릭해주세요.", "warning")
            return
            
        row = selected_ranges[0].topRow() 
        item = self.tbAccount.item(row, 0) 
        if item is None: return
        code = item.text() 
        
        if code in self.my_holdings:
            qty = self.my_holdings[code]['qty']
            success = self.api_manager.sell(code, qty) 
            if success:
                del self.my_holdings[code]     
                self.tbAccount.removeRow(row)  
                stock_name = STOCK_DICT.get(code, code)
                
                order_info = {
                    '종목코드': code, '종목명': stock_name, '주문종류': '매도(SELL)', 
                    '주문가격': '-', '주문수량': qty, '체결수량': qty, 
                    '주문시간': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), '상태': '비상청산'
                }
                self.sig_order_append.emit(order_info)
                
                self.add_log(f"🚨 [비상 탈출 수동 매도 완료] {stock_name} {qty}주 청산", "sell")
                self.btnDataSendClickEvent()   
        else:
            self.add_log(f"⚠️ 이미 팔았거나 지갑에 없는 종목입니다: {code}", "error")

    def btnAutoTradingSwitch(self):
        if not self.trade_worker.is_running: 
            self.trade_worker.start() 
            self.btnAutoDataTest.setText("자동 매매 중단 (STOP)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 [주삐 엔진] 1분 단위 감시망 가동! 잠시 후 첫 브리핑이 시작됩니다.", "success")
        else: 
            self.trade_worker.is_running = False 
            self.trade_worker.quit() 
            self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 [주삐 엔진] 감시망을 거둡니다. 푹 쉬세요!", "warning")

    # 💡 [핵심] get_ai_probability가 이제 'AI 확률', '현재가', '계산된 지표 표(df)' 3개를 모두 반환합니다!
    def get_ai_probability(self, code):
        df = self.api_manager.fetch_minute_data(code) 
        if df is None or len(df) < 30: return 0.0, 0, None 

        df['return'] = df['close'].pct_change()
        df['vol_change'] = df['volume'].pct_change()
        
        delta = df['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.ewm(com=13).mean())))
        df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        
        df['MA5'] = df['close'].rolling(5).mean() # 💡 화면에 띄울 MA5 추가
        df['MA20'] = df['close'].rolling(20).mean()
        df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
        df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['MA20']

        df['Disparity_5'] = (df['close'] / df['MA5']) * 100
        df['Disparity_20'] = (df['close'] / df['MA20']) * 100

        df['Vol_MA5'] = df['volume'].rolling(5).mean()
        df['Vol_Energy'] = np.where(df['Vol_MA5'] > 0, df['volume'] / df['Vol_MA5'], 1)

        df['OBV'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        df['OBV_Trend'] = df['OBV'].pct_change()

        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = true_range.rolling(14).mean()

        df['High_Tail'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['Low_Tail'] = df[['open', 'close']].min(axis=1) - df['low']

        curr = df.iloc[-1].replace([np.inf, -np.inf], 0).fillna(0)
        curr_price = curr['close'] 
        
        features = [
            'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 
            'BB_Width', 'Disparity_5', 'Disparity_20', 
            'Vol_Energy', 'OBV_Trend', 
            'ATR', 'High_Tail', 'Low_Tail'
        ]
        X = curr[features].values.reshape(1, -1)
        
        if hasattr(self, 'model') and self.model is not None:
            prob = self.model.predict_proba(X)[0][1] 
        else:
            prob = -1.0 
        
        return prob, curr_price, df

    @QtCore.pyqtSlot(object) 
    def update_account_table_slot(self, df):
        TradeData.account.df = df
        self.update_table(self.tbAccount, df)

    @QtCore.pyqtSlot(object) 
    def update_strategy_table_slot(self, df):
        TradeData.strategy.df = df
        self.update_table(self.tbStrategy, df)

    @QtCore.pyqtSlot(str, str) 
    def add_log(self, text, log_type="info"):
        color = {
            "info": "white", 
            "success": "lime", 
            "warning": "yellow", 
            "error": "red", 
            "send": "cyan", 
            "recv": "orange",
            "buy": "#4B9CFF",   
            "sell": "#FF4B4B"   
        }.get(log_type, "white")
        
        now = datetime.now().strftime("[%H:%M:%S]")
        html_message = f'<span style="color:{color}">{now} {text}</span>'
        
        QtCore.QTimer.singleShot(0, lambda: self._safe_append_log(html_message))

    def _safe_append_log(self, html_msg):
        self.txtLog.appendHtml(html_msg)
        self.txtLog.verticalScrollBar().setValue(self.txtLog.verticalScrollBar().maximum())

    def _setup_table(self, table, columns):
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        self.style_table(table)

    def style_table(self, table):
        table.setFont(QtGui.QFont("Noto Sans KR", 12))
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch) 
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)  
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection) 
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)   
        table.setStyleSheet("""
            QTableWidget { background-color: rgb(50,80,110); color: Black; selection-background-color: rgb(80, 120, 160); } 
            QHeaderView::section { background-color: rgb(40,60,90); color: Black; font-weight: bold; }
        """)

    def _create_nav_button(self, text, x_pos):
        btn = QtWidgets.QPushButton(text, self.centralwidget)
        btn.setGeometry(x_pos, 5, 300, 40)
        btn.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor)) 
        btn.installEventFilter(self) 
        return btn

    def eventFilter(self, source, event):
        if event.type() == QtCore.QEvent.Enter: source.setStyleSheet("background-color: rgb(5,5,10); color: Lime;")
        elif event.type() == QtCore.QEvent.Leave: source.setStyleSheet("background-color: rgb(5,5,10); color: Silver;")
        return super().eventFilter(source, event)

    def btnCloseClickEvent(self): QtWidgets.QApplication.quit()          

    def btnDataCreatClickEvent(self):
        if hasattr(self, 'mock_data_timer') and self.mock_data_timer.isActive():
            self.mock_data_timer.stop()
            self.btnDataCreatTest.setText("데이터 자동생성 시작")
            self.btnDataCreatTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 실시간 가짜 데이터 전송을 멈춥니다.", "warning")
        else:
            if not hasattr(self, 'mock_data_timer'):
                self.mock_data_timer = QtCore.QTimer(self)
                self.mock_data_timer.timeout.connect(self.generate_and_send_mock_data)
            self.mock_data_timer.start(1000)
            self.btnDataCreatTest.setText("데이터 자동생성 중지 (STOP)")
            self.btnDataCreatTest.setStyleSheet("background-color: rgb(10, 70, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 1초마다 가짜 데이터를 C#으로 연속 발사합니다!", "success")

    def generate_and_send_mock_data(self):
        TradeData.market.generate_mock_data()
        TradeData.account.generate_mock_data()
        TradeData.order.generate_mock_data()
        TradeData.strategy.generate_mock_data()
        
        self.update_table(self.tbMarket, TradeData.market.df)
        self.update_table(self.tbAccount, TradeData.account.df)
        self.update_table(self.tbOrder, TradeData.order.df)
        self.update_table(self.tbStrategy, TradeData.strategy.df)
        
        self.btnDataSendClickEvent()

    def update_table(self, tableWidget, df):
        tableWidget.setUpdatesEnabled(False) 

        current_row_count = tableWidget.rowCount() 
        new_row_count = len(df)                    

        if current_row_count < new_row_count:
            for _ in range(new_row_count - current_row_count):
                tableWidget.insertRow(tableWidget.rowCount())
        elif current_row_count > new_row_count:
            for _ in range(current_row_count - new_row_count):
                tableWidget.removeRow(tableWidget.rowCount() - 1)

        for i in range(new_row_count):
            for j, col in enumerate(df.columns):
                val = str(df.iloc[i, j])          
                item = tableWidget.item(i, j)     

                if item is None:
                    item = QtWidgets.QTableWidgetItem(val)
                    item.setTextAlignment(QtCore.Qt.AlignCenter)
                    tableWidget.setItem(i, j, item)
                else:
                    if item.text() != val: 
                        item.setText(val)

        tableWidget.scrollToBottom() 
        tableWidget.setUpdatesEnabled(True) 

    def btnDataClearClickEvent(self):
        self.tbAccount.setRowCount(0)
        self.tbStrategy.setRowCount(0)
        self.tbOrder.setRowCount(0)
        self.tbMarket.setRowCount(0)

    def btnConnectedClickEvent(self):
        if TcpJsonClient.Isconnected:
            self.client.close()
            TcpJsonClient.Isconnected = False
            self.btnConnected.setText("통신 연결 X")
            self.btnConnected.setStyleSheet("color: Silver;")
        else:
            self.client.connect()
            if TcpJsonClient.Isconnected:
                self.btnConnected.setText("통신 연결 O")
                self.btnConnected.setStyleSheet("color: Lime;")