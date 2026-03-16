# =====================================================================
# [1] 필요한 '마법 도구'들을 창고에서 꺼내옵니다.
# =====================================================================
from PyQt5 import QtWidgets, uic, QtCore, QtGui  # 화면을 그리고 단축키를 만드는 도구
from PyQt5.QtCore import Qt, QThread, pyqtSignal # 💡 [중요] 렉 방지용 '일꾼(Thread)'과 연락용 '무전기(Signal)'
import sys
import pandas as pd        # 표(Table) 데이터를 엑셀처럼 다루는 도구
import numpy as np         # AI 계산을 위한 수학 도구
import random
import joblib              # 우리가 만든 'AI 뇌(pkl)'를 깨우는 도구
import os                  # 파일 경로를 찾는 도구
import time                # "잠깐 쉬어!" 라고 명령하는 도구
from datetime import datetime # "지금 몇 시야?" 시계를 보는 도구

# [경로 설정] 우리가 직접 만든 부품들을 가져옵니다.
from COMMON.Flag import TradeData            # 💡 C#과 통신할 때 쓰는 '진짜 데이터 바구니'
from COM.TcpJsonClient import TcpJsonClient  # 완성된 데이터를 C#으로 쏴주는 '통신병'
from COMMON.KIS_Manager import KIS_Manager   # 증권사 서버와 대화하는 '영업 매니저'


# ✨ [종목 번역 사전]
STOCK_DICT = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "005380": "현대차", "000270": "기아", "068270": "셀트리온",
    "005490": "POSCO홀딩스", "035420": "NAVER", "035720": "카카오",
    "000810": "삼성화재", "051910": "LG화학", "105560": "KB금융",
    "012330": "현대모비스", "032830": "삼성생명", "055550": "신한지주",
    "003550": "LG", "000100": "유한양행", "033780": "KT&G",
    "009150": "삼성전기", "015760": "한국전력"
}

# =====================================================================
# ⚙️ [핵심 부품] 렉 방지용 백그라운드 일꾼 (AutoTradeWorker)
# =====================================================================
class AutoTradeWorker(QThread):
    sig_log = pyqtSignal(str, str)        # 로그창에 글씨 써달라는 무전
    sig_account_df = pyqtSignal(object)   # 계좌 표 그려달라는 무전
    sig_strategy_df = pyqtSignal(object)  # 전략 표 그려달라는 무전
    sig_sync_cs = pyqtSignal()            # C#으로 데이터 쏴달라는 무전

    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window   
        self.is_running = False 

    def run(self):
        self.is_running = True
        while self.is_running:
            self.process_trading() 
            # 1초씩 60번 쉬면서 대장 눈치 보기
            for _ in range(60):
                if not self.is_running: break 
                time.sleep(1)

    def process_trading(self):
        now = datetime.now() 
        
        # 🚨 [시간 규칙 1] 오후 3시 20분 무조건 강제 청산
        if now.hour == 15 and now.minute >= 20:
            if len(self.mw.my_holdings) > 0: 
                self.sig_log.emit("⏰ [장 마감 임박] 오후 3시 20분입니다! 전 종목 강제 청산 시작!", "error")
                for code, info in list(self.mw.my_holdings.items()):
                    self.mw.api_manager.sell(code, info['qty'])
                    del self.mw.my_holdings[code] 
                self.sig_log.emit("✅ 강제 청산 완료. 내일 기분 좋게 다시 만나요!", "success")
                
                empty_df = pd.DataFrame(columns=['종목코드','종목명','보유수량','평균매입가','평가손익','주문가능금액'])
                self.sig_account_df.emit(empty_df)
                self.sig_sync_cs.emit()
            return 

        # 💰 [철칙 설정] 안정형 단타 모드의 규칙들
        MAX_STOCKS = 10     
        TAKE_PROFIT = 3.0   # +3.0% 익절
        STOP_LOSS = -2.0    # 👩‍🏫 -2.0% 손절 (요청하신 대로 설정한 비율!)
        SCAN_POOL = list(STOCK_DICT.keys()) 

        # ---------------------------------------------------------
        # 🚨 STEP 0: 기존 주식 수익률 감시 및 기계적 매도 처리!
        # ---------------------------------------------------------
        account_rows = [] 
        
        if len(self.mw.my_holdings) > 0: 
            sold_codes = [] 
            
            for code, info in self.mw.my_holdings.items():
                buy_price = info['price'] 
                buy_qty = info['qty']     
                
                df = self.mw.api_manager.fetch_minute_data(code)
                if df is None: continue 
                curr_price = df.iloc[-1]['close'] 
                
                profit_rate = ((curr_price - buy_price) / buy_price) * 100
                stock_name = STOCK_DICT.get(code, f"알수없음_{code}")

                # 💡 [매도 판단 방아쇠] - 👩‍🏫 여기서 문제 1, 2번을 완벽히 해결했습니다!
                is_sell = False
                status_msg = ""

                if profit_rate >= TAKE_PROFIT:     # 익절 라인
                    is_sell = True
                    status_msg = f"📈 기계적 익절 (+{profit_rate:.2f}%)"
                elif profit_rate <= STOP_LOSS:     # 손절 라인
                    is_sell = True
                    status_msg = f"📉 기계적 손절 ({profit_rate:.2f}%)"
                
                # ❌ [삭제된 부분 설명] 
                # 예전에는 여기서 "AI 상승확률이 낮으면 중간에 팔아버리는" 코드가 있었습니다.
                # 회원님 요청에 따라 그 부분을 완전 삭제했습니다!
                # 이제 무조건 설정한 수익률(TAKE_PROFIT)이나 하락률(STOP_LOSS)에 도달해야만 기계처럼 팝니다.

                if is_sell:
                    success = self.mw.api_manager.sell(code, buy_qty) 
                    if success: 
                        sold_codes.append(code) 
                        self.sig_log.emit(f"====================================", "warning")
                        self.sig_log.emit(f"{status_msg} -> [{stock_name}] 매도 실행!", "warning")
                        self.sig_log.emit(f"====================================", "warning")
                else:
                    account_rows.append({
                        '종목코드': code, '종목명': stock_name, '보유수량': buy_qty, 
                        '평균매입가': f"{buy_price:,.0f}", '평가손익': f"{profit_rate:.2f}%", '주문가능금액': 0
                    })
                        
            for code in sold_codes:
                del self.mw.my_holdings[code]

        if now.hour >= 15:
            self.sig_log.emit("⏰ 오후 3시가 넘었습니다. 쇼핑(매수)은 멈추고 감시만 합니다.", "info")
            self._update_account_ui(account_rows) 
            return 

        # ---------------------------------------------------------
        # 🔍 STEP 1: 지갑 빈자리 파악 & 💰 완벽한 N빵 자금 배분!
        # ---------------------------------------------------------
        current_count = len(self.mw.my_holdings) 
        needed_count = MAX_STOCKS - current_count 
        
        my_cash = self.mw.api_manager.get_balance() or 0
        cash_str = f"{my_cash:,}" 
        
        self._update_account_ui(account_rows, cash_str)

        if needed_count <= 0: 
            self.sig_log.emit(f"✅ 포트폴리오 꽉 참 ({MAX_STOCKS}/10). 수익률 감시 중...", "info")
            return 
            
        BUDGET_PER_STOCK = my_cash // needed_count

        self.sig_log.emit(f"🔎 빈자리 {needed_count}개. 타겟 스캔... (종목당 {BUDGET_PER_STOCK:,}원 배분)", "info")

        if BUDGET_PER_STOCK < 10000:
            self.sig_log.emit("⚠️ 현금이 너무 부족합니다. 추가 매수를 중단합니다.", "error")
            return

        candidates = [] 
        for code in SCAN_POOL:
            if code in self.mw.my_holdings: continue 
            prob, curr_price = self.mw.get_ai_probability(code)
            if prob >= 0.6: 
                candidates.append({'code': code, 'prob': prob, 'price': curr_price})
            time.sleep(0.2) 
        
        candidates = sorted(candidates, key=lambda x: x['prob'], reverse=True)

        strategy_rows = []
        for target in candidates[:10]: 
            stock_name = STOCK_DICT.get(target['code'], "알수없음")
            strategy_rows.append({
                '종목코드': target['code'], '종목명': stock_name, 'MA_5': 0, 'MA_20': 0, 'RSI': 0, 
                'MACD': f"{target['prob']*100:.1f}%", '전략신호': "BUY 🟢" if target['prob'] >= 0.6 else "WAIT 🟡" 
            })
            
        if strategy_rows:
            self.sig_strategy_df.emit(pd.DataFrame(strategy_rows))
        else:
            self.sig_strategy_df.emit(pd.DataFrame(columns=['종목코드','종목명','MA_5','MA_20','RSI','MACD','전략신호']))

        # ---------------------------------------------------------
        # 🛒 STEP 2: 상위 랭커 야무지게 매수!
        # ---------------------------------------------------------
        if not candidates:
            self.sig_log.emit("🤔 상승 확률 60% 이상인 꿀벌 종목이 없네요. 관망합니다.", "info")
            return

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
                    self.sig_log.emit(f"🛒 [AI 매수] {stock_name} (상승확률: {target['prob']*100:.1f}%)", "info")
                    self.sig_log.emit(f"💸 {buy_qty}주 ({curr_price * buy_qty:,}원어치) 매수 완료!", "success")

        self.sig_sync_cs.emit()

    def _update_account_ui(self, account_rows, cash_str="0"):
        if len(account_rows) > 0:
            for row in account_rows: row['주문가능금액'] = "" 
            account_rows[0]['주문가능금액'] = cash_str      
            self.sig_account_df.emit(pd.DataFrame(account_rows))
        else:
            empty_df = pd.DataFrame(columns=['종목코드','종목명','보유수량','평균매입가','평가손익','주문가능금액'])
            self.sig_account_df.emit(empty_df)
        self.sig_sync_cs.emit()


# =====================================================================
# 🖥️ 메인 UI 클래스 (FormMain) - 지휘통제실
# =====================================================================
class FormMain(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.initUI() 

        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(root, "jubby_brain.pkl")
            self.model = joblib.load(model_path)
            self.add_log("🧠 AI 두뇌(jubby_brain.pkl) 이식 완료!", "success")
        except Exception as e:
            self.add_log(f"⚠️ AI 뇌 로드 실패 (추후 실제 모델 필요): {e}", "warning")

        self.api_manager = KIS_Manager(ui_main=self)
        self.api_manager.start_api() 

        self.my_holdings = {} 
        self.trade_worker = AutoTradeWorker(main_window=self)
        
        self.trade_worker.sig_log.connect(self.add_log)                                
        self.trade_worker.sig_account_df.connect(self.update_account_table_slot)       
        self.trade_worker.sig_strategy_df.connect(self.update_strategy_table_slot)     
        self.trade_worker.sig_sync_cs.connect(self.btnDataSendClickEvent)              

        self._isDragging = False
        self._startPos = QtCore.QPoint()

        # 💡 [문제 3 해결을 위한 핵심 부품 추가!] 1초마다 C#에 데이터를 쏴줄 '타이머 일꾼' 고용
        self.mock_data_timer = QtCore.QTimer(self)
        self.mock_data_timer.setInterval(1000) # 1000ms = 1초마다 실행하라는 뜻
        self.mock_data_timer.timeout.connect(self.generate_and_send_mock_data) # 시간이 될 때마다 이 함수 실행!

        self.load_real_holdings()


    def load_real_holdings(self):
        try:
            self.my_holdings = self.api_manager.get_real_holdings()
            self.add_log(f"💼 [잔고 동기화] {len(self.my_holdings)}개 종목 로드 완료. (이어달리기 준비 끝!)", "success")
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
        
        self.txtLog.mousePressEvent = self.custom_log_mouse_press

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

    def custom_log_mouse_press(self, event):
        if event.button() == Qt.LeftButton and event.modifiers() == Qt.ControlModifier:
            text = self.txtLog.toPlainText() 
            if not text.strip(): return 
            os.makedirs("Logs", exist_ok=True) 
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S") 
            filename = f"Logs/Manual_Log_{now_str}.txt" 
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            self.add_log(f"💾 [저장 성공] 현재 로그가 {filename} 로 캡처되었습니다.", "success")
        else:
            QtWidgets.QPlainTextEdit.mousePressEvent(self.txtLog, event)

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
                self.add_log(f"🚨 [비상 탈출] {stock_name} {qty}주 수동 매도 완료!", "error")
                self.btnDataSendClickEvent()   
        else:
            self.add_log(f"⚠️ 이미 팔았거나 지갑에 없는 종목입니다: {code}", "error")

    def btnAutoTradingSwitch(self):
        if not self.trade_worker.is_running: 
            self.trade_worker.start() 
            self.btnAutoDataTest.setText("자동 매매 중단 (STOP)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 [주삐 엔진] 1분 단위 스레드 가동! (기존 주식 감시부터 시작합니다)", "success")
        else: 
            self.trade_worker.is_running = False 
            self.trade_worker.quit() 
            self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 [주삐 엔진] 감시를 멈춥니다.", "warning")

    def get_ai_probability(self, code):
        df = self.api_manager.fetch_minute_data(code) 
        if df is None or len(df) < 30: return 0.0, 0 

        df['return'] = df['close'].pct_change()
        df['vol_change'] = df['volume'].pct_change()
        delta = df['close'].diff()
        up, down = delta.copy(), delta.copy()
        up[up < 0] = 0; down[down > 0] = 0
        df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.abs().ewm(com=13).mean())))
        df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        df['MA20'] = df['close'].rolling(20).mean()
        df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
        
        curr = df.iloc[-1].fillna(0).replace([np.inf, -np.inf], 0)
        curr_price = curr['close'] 
        
        features = ['return', 'vol_change', 'RSI', 'MACD', 'BB_Lower']
        X = curr[features].values.reshape(1, -1)
        # 만약 모델이 아직 없으면 임시로 랜덤 확률 부여 (테스트용)
        if hasattr(self, 'model'):
            prob = self.model.predict_proba(X)[0][1] 
        else:
            prob = random.uniform(0.1, 0.9)
        
        return prob, curr_price 

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
        color = {"info": "white", "success": "lime", "warning": "yellow", 
                 "error": "red", "send": "cyan", "recv": "orange"}.get(log_type, "white")
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

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._isDragging = True
            self._startPos = event.globalPos() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, event):
        if self._isDragging: self.move(event.globalPos() - self._startPos)
    def mouseReleaseEvent(self, event): self._isDragging = False

    def btnSimulTestClickEvent(self): self.api_manager.check_my_balance() 
    def btnCloseClickEvent(self): QtWidgets.QApplication.quit()          

    # =================================================================
    # 🎲 [문제 3번 해결!] 1초마다 C#에 연속으로 데이터 쏘는 스위치
    # =================================================================
    def btnDataCreatClickEvent(self):
        """이 버튼을 누르면 1초 간격으로 계속해서 난수 데이터를 생성하고 C#에 보냅니다!"""
        if self.mock_data_timer.isActive():
            # 타이머가 돌고 있으면? 멈춥니다!
            self.mock_data_timer.stop()
            self.btnDataCreatTest.setText("데이터 자동생성 시작")
            self.btnDataCreatTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 실시간 가짜 데이터 전송을 멈춥니다.", "warning")
        else:
            # 타이머가 멈춰있으면? 시작합니다!
            self.mock_data_timer.start()
            self.btnDataCreatTest.setText("데이터 자동생성 중지 (STOP)")
            self.btnDataCreatTest.setStyleSheet("background-color: rgb(10, 70, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 1초마다 가짜 데이터를 C#으로 연속 발사합니다! (C# 차트가 부드럽게 움직일 거예요)", "success")

    def generate_and_send_mock_data(self):
        """👩‍🏫 QTimer가 1초(1000ms)마다 백그라운드에서 자동으로 이 함수를 호출합니다!"""
        # 1. 4개 표의 가짜 데이터를 갱신합니다.
        TradeData.market.generate_mock_data()
        TradeData.account.generate_mock_data()
        TradeData.order.generate_mock_data()
        TradeData.strategy.generate_mock_data()
        
        # 2. 파이썬 화면(UI)의 표를 부드럽게 업데이트합니다.
        self.update_table(self.tbMarket, TradeData.market.df)
        self.update_table(self.tbAccount, TradeData.account.df)
        self.update_table(self.tbOrder, TradeData.order.df)
        self.update_table(self.tbStrategy, TradeData.strategy.df)
        
        # 3. 방금 만든 따끈따끈한 데이터를 C#에 통째로 전송합니다!
        self.btnDataSendClickEvent()


    @QtCore.pyqtSlot() 
    def btnDataSendClickEvent(self):
        """C# 화면에 표 데이터를 싹 다 전송합니다."""
        if TcpJsonClient.Isconnected:
            self.client.send_message("market", TradeData.market_dict())
            self.client.send_message("account", TradeData.account_dict())
            self.client.send_message("strategy", TradeData.strategy_dict())

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