from PyQt5 import QtWidgets, uic, QtCore, QtGui
from PyQt5.QtCore import Qt
import sys
import pandas as pd
import numpy as np
import random
import joblib # AI 뇌(pkl)를 불러오기 위한 도구
import os
from datetime import datetime

# [경로 설정] 프로젝트 내 공용 모듈 불러오기
from COMMON.Flag import TradeData            # 데이터 저장소
from COM.TcpJsonClient import TcpJsonClient  # C# 전송용 클라이언트
from COMMON.KIS_Manager import KIS_Manager   # 증권사 API 매니저

class FormMain(QtWidgets.QMainWindow):
    """
    주삐 AI 자동매매의 메인 컨트롤 타워입니다.
    9시 정각에 '자동매매 시작' 버튼을 누르면 1분 단위 감시 루프가 가동됩니다.
    """
    def __init__(self):
        super().__init__()
        
        # 1. 화면 구성 및 위젯 생성
        self.initUI()

        # 2. [두뇌 이식] 학습시켜 만든 AI 모델(pkl)을 불러옵니다.
        # 파일 경로는 프로젝트 최상위 폴더 기준입니다.
        try:
            # os.path.dirname을 이용해 정확한 경로 탐색 (최상위 폴더의 pkl 파일)
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(root, "jubby_brain.pkl")
            self.model = joblib.load(model_path)
            self.add_log("🧠 AI 두뇌(jubby_brain.pkl) 이식 완료!", "success")
        except Exception as e:
            self.add_log(f"⚠️ AI 뇌를 찾을 수 없습니다: {e}", "error")

        # 3. [매니저 고용] KIS API와 통신할 매니저 생성 및 접속
        self.api_manager = KIS_Manager(ui_main=self)
        self.api_manager.start_api()

        # 4. [자동매매 타이머] 1분마다 시장을 감시할 비서(Timer) 설정
        self.auto_timer = QtCore.QTimer(self)
        self.auto_timer.timeout.connect(self.auto_trading_loop) # 1분마다 실행될 함수 연결
        self.is_auto_trading = False # 현재 자동매매 가동 여부
        self.is_holding = False      # 현재 주식을 들고 있는지 여부

        # 드래그 이동 변수
        self._isDragging = False
        self._startPos = QtCore.QPoint()

    def initUI(self):
        """UI 초기 설정 및 표/버튼 배치"""
        uic.loadUi("GUI/Main.ui", self)
        self.client = TcpJsonClient(host="127.0.0.1", port=9001)

        # 창 스타일 (테두리 제거 및 다크 배경)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setGeometry(0, 0, 1920, 1080)
        self.centralwidget.setStyleSheet("background-color: rgb(5,5,15);")

        # ---------------------------------------------------------
        # 표 위젯 직접 생성 (AttributeError 방지)
        # ---------------------------------------------------------
        self.tbMarket = QtWidgets.QTableWidget(self.centralwidget)
        self.tbMarket.setGeometry(5, 50, 1420, 240)
        self._setup_table(self.tbMarket, TradeData.market.df.columns)

        self.tbAccount = QtWidgets.QTableWidget(self.centralwidget)
        self.tbAccount.setGeometry(5, 295, 1420, 240)
        self._setup_table(self.tbAccount, TradeData.account.df.columns)

        self.tbOrder = QtWidgets.QTableWidget(self.centralwidget)
        self.tbOrder.setGeometry(5, 540, 1420, 240)
        self._setup_table(self.tbOrder, TradeData.order.df.columns)

        self.tbStrategy = QtWidgets.QTableWidget(self.centralwidget)
        self.tbStrategy.setGeometry(5, 785, 1420, 240)
        self._setup_table(self.tbStrategy, TradeData.strategy.df.columns)

        self.txtLog = QtWidgets.QPlainTextEdit(self.centralwidget)
        self.txtLog.setGeometry(1430, 95, 485, 930)
        self.txtLog.setReadOnly(True)
        self.txtLog.setStyleSheet("background-color: rgb(20, 30, 45); color: white; font-family: Consolas; font-size: 13px;")

        # ---------------------------------------------------------
        # 메뉴 버튼 생성 및 연결
        # ---------------------------------------------------------
        self.btnDataCreatTest = self._create_nav_button("데이터 생성 테스트", 5)
        self.btnDataSendTest = self._create_nav_button("C# 데이터 전송", 310)
        self.btnSimulDataTest = self._create_nav_button("계좌 잔고 조회", 615)
        
        # ✨ [핵심 버튼] 이 버튼이 9시 정각에 누를 '자동매매 엔진' 스위치입니다.
        self.btnAutoDataTest = self._create_nav_button("자동 매매 가동 (GO)", 920)
        
        self.btnDataClearTest = self._create_nav_button("화면 데이터 초기화", 1225)
        
        self.btnClose = QtWidgets.QPushButton(" X ", self.centralwidget)
        self.btnClose.setGeometry(1875, 5, 40, 40)
        self.btnClose.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")

        self.btnConnected = QtWidgets.QPushButton("통신 연결 X", self.centralwidget)
        self.btnConnected.setGeometry(1430, 50, 485, 40)
        self.btnConnected.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")

        # 이벤트 연결
        self.btnDataCreatTest.clicked.connect(self.btnDataCreatClickEvent)
        self.btnDataSendTest.clicked.connect(self.btnDataSendClickEvent)
        self.btnSimulDataTest.clicked.connect(self.btnSimulTestClickEvent)
        self.btnAutoDataTest.clicked.connect(self.btnAutoTradingSwitch) # 자동매매 스위치 연결
        self.btnDataClearTest.clicked.connect(self.btnDataClearClickEvent)
        self.btnClose.clicked.connect(self.btnCloseClickEvent)
        self.btnConnected.clicked.connect(self.btnConnectedClickEvent)

    # ---------------------------------------------------------
    # 🎯 [핵심 로직 1] 자동매매 엔진 스위치 (9시 정각에 클릭!)
    # ---------------------------------------------------------
    def btnAutoTradingSwitch(self):
        """버튼을 누를 때마다 자동매매 타이머를 켜거나 끕니다."""
        if not self.is_auto_trading:
            # 가동 시작
            self.is_auto_trading = True
            self.auto_timer.start(60000) # 60,000ms = 1분마다 루프 실행
            self.btnAutoDataTest.setText("자동 매매 중단 (STOP)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 [주삐 엔진] 가동 시작! 1분 단위 시장 감시 모드에 진입합니다.", "success")
            
            # 시작하자마자 첫 분석 실행
            self.auto_trading_loop()
        else:
            # 가동 중단
            self.is_auto_trading = False
            self.auto_timer.stop()
            self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 [주삐 엔진] 가동을 중단합니다. 모든 감시가 멈췄습니다.", "warning")

    # ---------------------------------------------------------
    # 🎯 [핵심 로직 2] 1분 단위 무한 루프 (AI의 판단과 주문)
    # ---------------------------------------------------------
    def auto_trading_loop(self):
        """1분마다 호출되어 시세를 분석하고 AI의 조언에 따라 매수/매도합니다."""
        target_code = "005930" # 감시 대상 (삼성전자)
        
        self.add_log(f"🔍 [감시 중] {target_code} 실시간 데이터를 분석합니다...", "info")

        # 1. KIS 매니저를 통해 최신 1분봉 데이터 30개를 가져옵니다.
        df = self.api_manager.fetch_minute_data(target_code)
        if df is None or len(df) < 20:
            self.add_log("⚠️ 시세 데이터를 가져오지 못했습니다. 다음 1분에 재시도합니다.", "warning")
            return

        # 2. [전처리] AI가 공부할 때 썼던 보조지표를 똑같이 계산합니다.
        df['return'] = df['close'].pct_change()
        df['vol_change'] = df['volume'].pct_change()
        # RSI
        delta = df['close'].diff()
        up, down = delta.copy(), delta.copy()
        up[up < 0] = 0; down[down > 0] = 0
        df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.abs().ewm(com=13).mean())))
        # MACD & 볼린저 밴드
        df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        df['MA20'] = df['close'].rolling(20).mean()
        df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
        
        # 마지막 행(현재 시점) 데이터만 추출
        curr = df.iloc[-1]

        # 3. [AI 판독] 뇌(Model)에게 물어봅니다.
        features = ['return', 'vol_change', 'RSI', 'MACD', 'BB_Lower']
        # 무한대나 빈값 방지 처리
        X = curr[features].fillna(0).replace([np.inf, -np.inf], 0).values.reshape(1, -1)
        
        # AI가 "지금 사면 오를 확률"을 계산 (0.0 ~ 1.0)
        prob = self.model.predict_proba(X)[0][1]

        # 4. [최종 판단] 매수/매도 결정
        # AI 확신이 80% 이상이고, RSI가 35 이하(과매도 바닥)일 때!
        if not self.is_holding:
            self.add_log(f"🧐 [AI 리포트] 상승확률: {prob:.2f} / RSI: {curr['RSI']:.1f}", "info")
            if prob > 0.8 and curr['RSI'] < 35:
                self.add_log(f"🔥 [AI 승인] 강력한 반등 신호 포착! {target_code} 시장가 매수!", "success")
                success = self.api_manager.buy_market_price(target_code, 1)
                if success: self.is_holding = True
        else:
            # (들고 있을 때의 익절/손절 로직은 여기에 추가 가능)
            self.add_log(f"持有 중... 현재 AI 확신도: {prob:.2f}", "info")

        # 5. [동기화] 현재 분석된 데이터를 C#으로도 보냅니다.
        self.btnDataSendClickEvent()

    # ---------------------------------------------------------
    # 🎨 보조 함수들 (스타일링, 로그, 데이터 관리)
    # ---------------------------------------------------------
    def add_log(self, text, log_type="info"):
        color = {"info": "white", "success": "lime", "warning": "yellow", "error": "red", "send": "cyan", "recv": "orange"}.get(log_type, "white")
        now = datetime.now().strftime("[%H:%M:%S]")
        self.txtLog.appendHtml(f'<span style="color:{color}">{now} {text}</span>')
        self.txtLog.verticalScrollBar().setValue(self.txtLog.verticalScrollBar().maximum())

    def _setup_table(self, table, columns):
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        self.style_table(table)

    def style_table(self, table):
        table.setFont(QtGui.QFont("Noto Sans KR", 12))
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        table.setStyleSheet("QTableWidget { background-color: rgb(50,80,110); color: Black; } QHeaderView::section { background-color: rgb(40,60,90); color: Black; font-weight: bold; }")

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

    def btnDataCreatClickEvent(self):
        # 테스트 데이터 생성 로직
        TradeData.market.update_df()
        self.update_table(self.tbMarket, TradeData.market.df)
        self.add_log("시뮬레이션 데이터 생성 완료", "success")

    def btnDataSendClickEvent(self):
        """표의 데이터를 C#으로 쏩니다."""
        if TcpJsonClient.Isconnected:
            self.client.send_message("market", TradeData.market_dict())
            self.add_log("C# 서버로 최신 시세/AI 분석 데이터 송신 완료", "send")

    def update_table(self, table, df):
        table.clearContents()
        table.setRowCount(len(df))
        for i in range(len(df)):
            for j in range(len(df.columns)):
                item = QtWidgets.QTableWidgetItem(str(df.iloc[i, j]))
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                table.setItem(i, j, item)

    def btnDataClearClickEvent(self):
        self.add_log("화면 데이터를 초기화합니다.", "warning")
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