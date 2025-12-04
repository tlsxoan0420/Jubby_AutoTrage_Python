from PyQt5 import QtWidgets, uic ,QtCore, QtGui
import sys
import pandas as pd
import random
from COMMON.Flag import TradeData
from COM.TcpJsonClient import TcpJsonClient 
class FormMain(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):

        # -----------------------
        # UI 파일 로드
        uic.loadUi("GUI/Main.ui", self)
        # UI 파일 로드
        # -----------------------

        # -----------------------
        # TCP JSON 클라이언트 생성
        self.client = TcpJsonClient(host="127.0.0.1", port=9001)
        # TCP JSON 클라이언트 생성
        # -----------------------


        # -----------------------
        # FomMain 기본 창 설정
        self.setWindowTitle('Main Form')
        self.setGeometry(0, 0, 1920, 1080)

        # -----------------------
        # Form Frameless 설정(창 테두리 제거)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        # Form Frameless 설정(창 테두리 제거)
        # -----------------------

        # -----------------------
        # RGB 배경색 적용 (centralwidget 기준)
        self.centralwidget.setStyleSheet("background-color: rgb(5,5,15);")
        # RGB 배경색 적용 (centralwidget 기준)
        # -----------------------

        # -----------------------
        # 데이터 생성 테스트 버튼 생성
        self.btnDataCreatTest = QtWidgets.QPushButton("데이터 생성 테스트 버튼", self.centralwidget)
        self.btnDataCreatTest.setGeometry(5, 5, 300, 40)  # 위치와 크기
        self.btnDataCreatTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
        self.btnDataCreatTest.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        # 데이터 생성 테스트 버튼 생성
        # -----------------------

        # -----------------------
        # 데이터 송신 테스트 버튼 생성
        self.btnDataSendTest = QtWidgets.QPushButton("데이터 송신 테스트 버튼", self.centralwidget)
        self.btnDataSendTest.setGeometry(310, 5, 300, 40)  # 위치와 크기
        self.btnDataSendTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
        self.btnDataSendTest.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        
        # -----------------------
        # 모의 주식 테스트 버튼 생성
        self.btnSimulDataTest = QtWidgets.QPushButton("모의 주식 테스트 버튼", self.centralwidget)
        self.btnSimulDataTest.setGeometry(615, 5, 300, 40)  # 위치와 크기
        self.btnSimulDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
        self.btnSimulDataTest.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

        # -----------------------
        # 자동 매매 테스트 버튼 생성
        self.btnAutoDataTest = QtWidgets.QPushButton("자동 매매 테스트 버튼", self.centralwidget)
        self.btnAutoDataTest.setGeometry(920, 5, 300, 40)  # 위치와 크기
        self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
        self.btnAutoDataTest.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        # 자동 매매 테스트 버튼 생성
        # -----------------------

        # -----------------------
        # 데이터 초기화 버튼 생성
        self.btnDataClearTest = QtWidgets.QPushButton("데이터 초기화 버튼", self.centralwidget)
        self.btnDataClearTest.setGeometry(1225, 5, 300, 40)  # 위치와 크기
        self.btnDataClearTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
        self.btnDataClearTest.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        # 데이터 초기화 버튼 생성
        # -----------------------

        # -----------------------
        # 종료 버튼 생성
        self.btnClose = QtWidgets.QPushButton(" X ", self.centralwidget)
        self.btnClose.setGeometry(1875, 5, 40, 40)  # 위치와 크기
        self.btnClose.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")
        self.btnClose.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        # 종료 버튼 생성
        # -----------------------

        # -----------------------
        # 통신 상태 확인 및 통신 연결 버튼 생성
        self.btnConnected = QtWidgets.QPushButton("통신 연결 X", self.centralwidget)
        self.btnConnected.setGeometry(1430, 50, 485, 40)  # 위치와 크기
        self.btnConnected.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")
        self.btnConnected.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        # 통신 상태 확인 및 통신 연결 버튼생성
        # -----------------------

        # -----------------------
        # 버튼 클릭 이벤트 연결
        self.btnDataCreatTest.clicked.connect(self.btnDataCreatClickEvent)
        self.btnDataSendTest.clicked.connect(self.btnDataSendClickEvent)
        self.btnSimulDataTest.clicked.connect(self.btnSimulTestClickEvent)
        self.btnAutoDataTest.clicked.connect(self.btnAutoTestClickEvent)
        self.btnDataClearTest.clicked.connect(self.btnDataClearClickEvent)
        self.btnClose.clicked.connect(self.btnCloseClickEvent)
        self.btnConnected.clicked.connect(self.btnConnectedClickEvent)
        # 버튼 클릭 이벤트 연결
        # -----------------------

                # -----------------------
        # 버튼 마우스 이벤트 연결
        buttons = [self.btnDataCreatTest, self.btnDataSendTest, self.btnSimulDataTest,
                   self.btnAutoDataTest, self.btnDataClearTest, self.btnConnected]
        for btn in buttons:
            btn.setStyleSheet("background-color: rgb(5, 5, 15); color: Silver;")
            btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            btn.installEventFilter(self)  # 호버 이벤트 연결
        # 버튼 마우스 이벤트 연결
        # -----------------------

        # -----------------------
        # Market Table 생성
        self.tbMarket = QtWidgets.QTableWidget(self.centralwidget)
        self.tbMarket.setGeometry(5, 50, 1420, 240)  # 위치와 크기
        self.tbMarket.setColumnCount(len(TradeData.market.df.columns))
        self.tbMarket.setHorizontalHeaderLabels(TradeData.market.df.columns)
        self.tbMarket.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.style_table(self.tbMarket)
        # Market Table 생성
        # -----------------------
        
        # -----------------------
        # Account Table 생성
        self.tbAccount = QtWidgets.QTableWidget(self.centralwidget)
        self.tbAccount.setGeometry(5, 295, 1420, 240)
        self.tbAccount.setColumnCount(len(TradeData.account.df.columns))
        self.tbAccount.setHorizontalHeaderLabels(TradeData.account.df.columns)
        self.tbAccount.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.style_table(self.tbAccount)
        # Account Table 생성
        # -----------------------

                # -----------------------
        # Order Table 생성
        self.tbOrder = QtWidgets.QTableWidget(self.centralwidget)
        self.tbOrder.setGeometry(5, 540, 1420, 240)
        self.tbOrder.setColumnCount(len(TradeData.order.df.columns))
        self.tbOrder.setHorizontalHeaderLabels(TradeData.order.df.columns)
        self.tbOrder.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbOrder.setStyleSheet("color: Black; background-color: rgb(50, 80, 110);")
        self.style_table(self.tbOrder)
        # Order Table 생성
        # -----------------------

                # -----------------------
        # Strategy Table 생성
        self.tbStrategy = QtWidgets.QTableWidget(self.centralwidget)
        self.tbStrategy.setGeometry(5, 785, 1420, 240)
        self.tbStrategy.setColumnCount(len(TradeData.strategy.df.columns))
        self.tbStrategy.setHorizontalHeaderLabels(TradeData.strategy.df.columns)
        self.tbStrategy.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.tbStrategy.setStyleSheet("color: Black; background-color: rgb(50, 80, 110);")
        self.style_table(self.tbStrategy)
        # Strategy Table 생성
        # -----------------------

        # -----------------------
        # 로그 창 추가
        self.txtLog = QtWidgets.QPlainTextEdit(self.centralwidget)
        self.txtLog.setGeometry(1430, 95, 485, 930)
        self.txtLog.setReadOnly(True)
        self.txtLog.setStyleSheet("""
            QPlainTextEdit {
                background-color: rgb(20, 30, 45);
                color: white;
                border: 1px solid rgb(90,90,90);
                font-family: Consolas;
                font-size: 15px;
            }
        """)
        # 로그 창 추가
        # -----------------------

    # -----------------------
    # 버튼 클릭 이벤트
    def btnDataCreatClickEvent(self):
        print("데이터 생성 테스트 버튼 클릭")
        self.DataCreat()
        self.update_table(self.tbMarket, TradeData.market.df)
        self.update_table(self.tbAccount, TradeData.account.df)
        self.update_table(self.tbOrder, TradeData.order.df)
        self.update_table(self.tbStrategy, TradeData.strategy.df)

    def btnDataSendClickEvent(self):
        print("데이터 송신 테스트 버튼 클릭")

    def btnSimulTestClickEvent(self):
        print("모의 주식 테스트 버튼 클릭")

    def btnAutoTestClickEvent(self):
        print("자동 매매 테스트 버튼 클릭")

    def btnDataClearClickEvent(self):
        print("데이터 초기화 테스트 버튼 클릭")
        self.clear_all_data()

    def btnCloseClickEvent(self):
        print("종료 버튼 클릭")      
        QtWidgets.QApplication.quit()
        print("주삐를 종료합니당")      

    def btnConnectedClickEvent(self):
        try:
            self.client.connect()
            print("✔ Python → C# 연결 성공")
            self.btnConnected.setText("통신 연결 O")
            self.btnConnected.setStyleSheet("color: Lime;")
        except Exception as e:
            print(f"연결 실패: {e}")
            self.btnConnected.setText("통신 연결")
            self.btnConnected.setStyleSheet("color: Silver;")
    # 버튼 클릭 이벤트
    # -----------------------

    # -----------------------
    # 공통 호버 이벤트 처리
    def eventFilter(self, source, event):
        hover_buttons = [self.btnDataCreatTest, self.btnDataSendTest,
                         self.btnSimulDataTest, self.btnAutoDataTest, self.btnDataClearTest, self.btnConnected]

        if source in hover_buttons:
            if event.type() == QtCore.QEvent.Enter:
                source.setStyleSheet("background-color: rgb(5,5,10); color: Lime;")
            elif event.type() == QtCore.QEvent.Leave:
                source.setStyleSheet("background-color: rgb(5,5,10); color: Silver;")

        return super().eventFilter(source, event)
    # 공통 호버 이벤트 처리
    # -----------------------

    # -----------------------
    # 데이터 생성 함수 #
    def DataCreat(self):
                # ------------------------
        # Market 데이터 생성
        TradeData.market.last_price = round(random.uniform(100, 1000), 2)
        TradeData.market.open_price = round(random.uniform(100, 1000), 2)
        TradeData.market.high_price = round(random.uniform(100, 1000), 2)
        TradeData.market.low_price = round(random.uniform(100, 1000), 2)
        TradeData.market.bid_price = round(random.uniform(100, 1000), 2)
        TradeData.market.ask_price = round(random.uniform(100, 1000), 2)
        TradeData.market.bid_size = random.randint(1, 100)
        TradeData.market.ask_size = random.randint(1, 100)
        TradeData.market.volume = random.randint(1000, 10000)

        # Market 데이터 생성
        # ------------------------

        # ------------------------
        # Account 데이터 생성
        TradeData.account.symbol = "AAPL"
        TradeData.account.quantity = random.randint(0, 50)
        TradeData.account.avg_price = round(random.uniform(100, 1000), 2)
        TradeData.account.pnl = round(random.uniform(-500, 500), 2)
        TradeData.account.available_cash = round(random.uniform(1000, 10000), 2)
        # Account 데이터 생성
        # ------------------------

        # ------------------------
        # Order 데이터 생성
        TradeData.order.order_id = random.randint(1000, 9999)
        TradeData.order.order_type = "BUY"
        TradeData.order.order_price = round(random.uniform(100, 1000), 2)
        TradeData.order.order_quantity = random.randint(1, 50)
        TradeData.order.filled_quantity = random.randint(0, TradeData.order.order_quantity)
        TradeData.order.order_time = "12:00:00"
        TradeData.order.order_status = "FILLED"
        # Order 데이터 생성
        # ------------------------

        # ------------------------
        # Strategy 데이터 생성
        TradeData.strategy.symbol = "AAPL"
        TradeData.strategy.ma_5 = round(random.uniform(100, 1000), 2)
        TradeData.strategy.ma_20 = round(random.uniform(100, 1000), 2)
        TradeData.strategy.rsi = round(random.uniform(0, 100), 2)
        TradeData.strategy.macd = round(random.uniform(-10, 10), 2)
        TradeData.strategy.signal = random.choice(["BUY", "SELL", "None"])

        # Strategy 데이터 생성
        # ------------------------

        # ------------------------
        # DataFrame 업데이트 #
        TradeData.market.update_df() 
        TradeData.account.update_df() 
        TradeData.order.update_df() 
        TradeData.strategy.update_df() 
        # DataFrame 업데이트 #
        # ------------------------

        print("테스트 데이터 생성 완료")
        print("Market DF:\n", TradeData.market.df)
        print("Account DF:\n", TradeData.account.df)
        print("Order DF:\n", TradeData.order.df)
        print("Strategy DF:\n", TradeData.strategy.df)
    # 데이터 생성 함수
    # -----------------------

    # -----------------------
    # 데이터 표 추가 함수
    def update_table(self, tableWidget, df):
        tableWidget.clearContents()
        tableWidget.setRowCount(0)

        tableWidget.setRowCount(len(df))
        tableWidget.setColumnCount(len(df.columns))
        tableWidget.setHorizontalHeaderLabels(df.columns)

        for i in range(len(df)):
            for j, col in enumerate(df.columns):
                item = QtWidgets.QTableWidgetItem(str(df.iloc[i, j]))

                item.setTextAlignment(QtCore.Qt.AlignCenter) # 가운데 정렬

                tableWidget.setItem(i, j, item)

        tableWidget.scrollToBottom() # 자동스크롤
        print("테스트 표 추가 완료")
    # 데이터 표 추가 함수
    # -----------------------

    # -----------------------
    # 표 스타일 지정
    def style_table(self, tableWidget):

        # 글꼴 적용 
        tableWidget.setFont(QtGui.QFont("Noto Sans KR", 20))
        tableWidget.horizontalHeader().setFont(QtGui.QFont("Noto Sans KR", 21, QtGui.QFont.Bold))

        # 헤더 크기 자동 분배
        header = tableWidget.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        # 행/열 크기 조정
        tableWidget.verticalHeader().setDefaultSectionSize(35)   # 행 높이
        tableWidget.horizontalHeader().setFixedHeight(40)        # 열 제목 높이

        tableWidget.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)  # 편집 금지
        tableWidget.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)   # 선택 자체 금지
        tableWidget.setFocusPolicy(QtCore.Qt.NoFocus)                           # 포커스 제거

        # 테이블 스타일 시트
        tableWidget.setStyleSheet("""
            QTableWidget {
                background-color: rgb(50,80,110);
                color: Black;
                gridline-color: rgb(140,140,140);
                font-size: 20px;
            }
            QHeaderView::section {
                background-color: rgb(40,60,90);
                color: Black;
                font-family: "Noto Sans KR";
                font-weight: bold;
                font-size: 15px;   
                border: 1px solid rgb(150,150,150);
            }
        """)
        # background-color = 테이블 전체 배경색
        # Color : 텍스트 색
        # gridLine-Color = 셀 사이에 있는 격자선의 색
    # 표 스타일 지정
    # -----------------------

    # -----------------------
    # 데이터 초기화
    def clear_all_data(self):
        # --- Market 초기화 ---
        TradeData.market.last_price = 0
        TradeData.market.open_price = 0
        TradeData.market.high_price = 0
        TradeData.market.low_price = 0
        TradeData.market.bid_price = 0
        TradeData.market.ask_price = 0
        TradeData.market.bid_size = 0
        TradeData.market.ask_size = 0
        TradeData.market.volume = 0
        TradeData.market.df = TradeData.market.df.iloc[0:0]  # 행 전체 삭제

        # --- Account 초기화 ---
        TradeData.account.symbol = ""
        TradeData.account.quantity = 0
        TradeData.account.avg_price = 0
        TradeData.account.pnl = 0
        TradeData.account.available_cash = 0
        TradeData.account.df = TradeData.account.df.iloc[0:0]

        # --- Order 초기화 ---
        TradeData.order.order_id = ""
        TradeData.order.order_type = ""
        TradeData.order.order_price = 0
        TradeData.order.order_quantity = 0
        TradeData.order.filled_quantity = 0
        TradeData.order.order_time = ""
        TradeData.order.order_status = ""
        TradeData.order.df = TradeData.order.df.iloc[0:0]

        # --- Strategy 초기화 ---
        TradeData.strategy.symbol = ""
        TradeData.strategy.ma_5 = 0
        TradeData.strategy.ma_20 = 0
        TradeData.strategy.rsi = 0
        TradeData.strategy.macd = 0
        TradeData.strategy.signal = ""
        TradeData.strategy.df = TradeData.strategy.df.iloc[0:0]

        # --- UI 테이블 비우기 ---
        self.tbMarket.clearContents()
        self.tbMarket.setRowCount(0)

        self.tbAccount.clearContents()
        self.tbAccount.setRowCount(0)

        self.tbOrder.clearContents()
        self.tbOrder.setRowCount(0)

        self.tbStrategy.clearContents()
        self.tbStrategy.setRowCount(0)

        print("모든 데이터 및 표가 완전히 초기화되었습니다.")
    # 데이터 초기화
    # -----------------------

    # -----------------------
    # 로그 데이터 추가
    def add_log(self, text, log_type="info"):
        # 색상 세팅
        color = {
            "info": "white",
            "success": "lime",
            "warning": "yellow",
            "error": "red",
            "send": "cyan",
            "recv": "orange"
        }.get(log_type, "white")

        # 시간 스탬프
        from datetime import datetime
        now = datetime.now().strftime("[%H:%M:%S]")

        # HTML 색 지정
        log_message = f'<span style="color:{color}">{now} {text}</span>'

        # 로그 추가
        self.txtLog.appendHtml(log_message)

        # 자동 스크롤
        self.txtLog.verticalScrollBar().setValue(
            self.txtLog.verticalScrollBar().maximum())
    # 로그 데이터 추가
    # -----------------------

