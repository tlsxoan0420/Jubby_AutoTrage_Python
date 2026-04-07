import json
import time
import websocket # 🚨 CMD에서 pip install websocket-client 필수
import threading
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from COMMON.Flag import SystemConfig
from COMMON.DB_Manager import JubbyDB_Manager
from COMMON.KIS_Manager import KIS_API

# =====================================================================
# 📡 [실전용] 한투 실시간 웹소켓 체결 수신 스레드
# =====================================================================
class RealWebSocketWorker(QThread):
    sig_execution_msg = pyqtSignal(str, str) # Ticker 창에 텍스트 띄우기용 (메시지, 타입)
    sig_real_execution = pyqtSignal(dict)    # 메인 UI(FormMain)로 데이터 넘기기용

    def __init__(self, main_ui=None):
        super().__init__()
        self.main_ui = main_ui
        self.is_running = True
        self.db = JubbyDB_Manager()
        self.ws = None

        # 1. DB에서 한투 API 키 및 HTS 아이디 가져오기
        self.app_key = self.db.get_shared_setting("KIS_API", "APP_KEY", "")
        self.app_secret = self.db.get_shared_setting("KIS_API", "APP_SECRET", "")
        
        # 🔥 [필수] 웹소켓 체결통보는 'HTS 로그인 아이디'가 꼭 필요합니다.
        self.hts_id = self.db.get_shared_setting("KIS_API", "HTS_ID", "HTS아이디입력") 
        
        is_mock_str = self.db.get_shared_setting("KIS_API", "IS_MOCK", "TRUE")
        self.is_mock = True if is_mock_str.upper() == "TRUE" else False
        
        # 2. 웹소켓 전용 접속키(Approval Key) 발급
        self.api = KIS_API(self.app_key, self.app_secret, "00000000", self.is_mock)
        self.approval_key = self.api.get_approval_key()

    def run(self):
        if not self.approval_key:
            self.sig_execution_msg.emit("🚨 접속키 발급 실패. 웹소켓을 켤 수 없습니다.", "error")
            return

        if self.hts_id == "HTS아이디입력" or not self.hts_id:
            self.sig_execution_msg.emit("🚨 DB의 SharedSettings에 HTS_ID를 등록해주세요!", "error")
            return

        # 3. 실전/모의 서버 주소 세팅
        ws_url = "ws://ops.koreainvestment.com:31000" if self.is_mock else "ws://ops.koreainvestment.com:21000"
        self.sig_execution_msg.emit(f"📡 한투 체결 서버 접속 중... ({'모의' if self.is_mock else '실전'})", "info")

        # 국내 주식 체결통보 TR_ID
        target_tr_id = "H0STCNI9" if self.is_mock else "H0STCNI0"

        # [FormTicker.py 수정 부분 - on_message 내부]
        def on_message(ws, message):
            if message in ["0", "1"]: return
            
            if "|" in message:
                parts = message.split("|")
                if len(parts) >= 4:
                    tr_id_recv = parts[1]
                    
                    # ---------------------------------------------------------
                    # 🟢 1. [복구 완료] 기존 체결 통보 (H0STCNI0 / H0STCNI9) 파싱 로직
                    # ---------------------------------------------------------
                    if tr_id_recv in ["H0STCNI0", "H0STCNI9"]:
                        content = parts[3].split('^')
                        if len(content) < 12: return
                        
                        try:
                            exec_data = {
                                "주문번호": content[1], 
                                "종목코드": content[3], 
                                "체결수량": int(content[5]), 
                                "체결가": float(content[6]), 
                                "체결시간": f"{content[7][:2]}:{content[7][2:4]}:{content[7][4:6]}"
                            }
                            self.sig_real_execution.emit(exec_data)
                            self.sig_execution_msg.emit(f"💰 [체결] {content[3]} | {exec_data['체결수량']}주 @ {exec_data['체결가']:,.0f}원", "success")
                        except: pass
                        
                    # ---------------------------------------------------------
                    # 🚀 2. [수정 완료] 실시간 호가 잔량 (H0STASP0) 하드코딩 제거
                    # ---------------------------------------------------------
                    elif tr_id_recv == "H0STASP0":
                        content = parts[3].split('^')
                        if len(content) >= 74: # 한투 웹소켓 호가 데이터 규격
                            try:
                                symbol = content[0] # 🔥 0번에 진짜 종목 코드가 들어옵니다!
                                
                                # 총 매도호가 잔량(Total Ask) = 43번째 인덱스
                                # 총 매수호가 잔량(Total Bid) = 73번째 인덱스
                                total_ask_size = float(content[43])
                                total_bid_size = float(content[73])
                                
                                # ⚡ DB의 MarketStatus 테이블에 0.1초 단위로 잔량 업데이트
                                conn = self.db._get_connection(self.db.shared_db_path)
                                conn.execute("""
                                    UPDATE MarketStatus 
                                    SET ask_size = ?, bid_size = ? 
                                    WHERE symbol = ?
                                """, (total_ask_size, total_bid_size, symbol))
                                conn.commit()
                                conn.close()
                            except Exception as e:
                                pass
                                
                    # ---------------------------------------------------------
                    # 🚀 3. [신규 추가] 실시간 체결가/현재가 (H0STCNT0) 0초 딜레이 수신
                    # ---------------------------------------------------------
                    elif tr_id_recv == "H0STCNT0":
                        content = parts[3].split('^')
                        if len(content) >= 3:
                            try:
                                symbol = content[0] 
                                curr_price = float(content[2])
                                
                                # API 통신 없이 메인 엔진이 바로 읽어다 쓸 수 있도록 DB에 꽂아줍니다.
                                conn = self.db._get_connection(self.db.shared_db_path)
                                conn.execute("""
                                    UPDATE MarketStatus 
                                    SET last_price = ? 
                                    WHERE symbol = ?
                                """, (curr_price, symbol))
                                conn.commit()
                                conn.close()
                            except: pass
            else:
                # JSON 응답 (최초 접속 성공 등) 처리
                try:
                    res = json.loads(message)
                    msg1 = res.get('body', {}).get('msg1', '')
                    if msg1:
                        self.sig_execution_msg.emit(f"✅ {msg1}", "success")
                    # PINGPONG 처리 (연결 유지)
                    if res.get("header", {}).get("tr_id") == "PINGPONG":
                        ws.send(message)
                except: pass

        def on_error(ws, error):
            self.sig_execution_msg.emit(f"🚨 웹소켓 오류: {error}", "error")

        def on_close(ws, close_status_code, close_msg):
            self.sig_execution_msg.emit("🔌 웹소켓 연결이 종료되었습니다.", "warning")

        def on_open(ws):
            self.sig_execution_msg.emit("🌐 실시간 체결 서버 연결 성공!", "success")
            
            # 한투 서버에 '내 계좌의 체결 내역을 실시간으로 보내달라'고 구독(Subscribe) 요청
            subscribe_msg = {
                "header": {
                    "approval_key": self.approval_key,
                    "custtype": "P",
                    "tr_type": "1",
                    "content-type": "utf-8"
                },
                "body": {
                    "input": {
                        "tr_id": target_tr_id,
                        "tr_key": self.hts_id  
                    }
                }
            }
            ws.send(json.dumps(subscribe_msg))
            self.sig_execution_msg.emit(f"📡 [{self.hts_id}] 계좌 실시간 감시 시작!", "info")

            # -------------------------------------------------------------
            # 🚀 [추가] AI가 선정한 종목들의 호가(H0STASP0) & 현재가(H0STCNT0) 구독!
            # -------------------------------------------------------------
            if self.main_ui and hasattr(self.main_ui, 'DYNAMIC_STOCK_DICT'):
                target_stocks = list(self.main_ui.DYNAMIC_STOCK_DICT.keys())
                for code in target_stocks:
                    # 📊 1. 호가창 잔량 구독
                    ws.send(json.dumps({"header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"}, "body": {"input": {"tr_id": "H0STASP0", "tr_key": code}}}))
                    time.sleep(0.05) 
                    # ⚡ 2. 실시간 현재가(체결가) 구독
                    ws.send(json.dumps({"header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"}, "body": {"input": {"tr_id": "H0STCNT0", "tr_key": code}}}))
                    time.sleep(0.05)
                self.sig_execution_msg.emit(f"📊 {len(target_stocks)}개 종목 실시간 0초 딜레이 감시 시작!", "info")

        # 웹소켓 실행 (ping 설정 제거로 안정성 확보)
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            ws_url, 
            on_open=on_open, 
            on_message=on_message, 
            on_error=on_error, 
            on_close=on_close
        )
        
        while self.is_running:
            self.ws.run_forever() # 괄호 안을 비워야 KIS 자체 핑퐁만 사용합니다.
            if not self.is_running: break
            time.sleep(3) # 끊겼을 경우 3초 후 재연결 시도

    def stop(self):
        self.is_running = False
        if self.ws: self.ws.close()
        self.quit(); self.wait()

    # -----------------------------------------------------------------
    # 📡 [신규 추가] 실시간 가격/호가 수신 요청 (수익률 0% 방지용)
    # -----------------------------------------------------------------
    def subscribe_stock_realtime(self, code):
        """ 새 종목을 사자마자 한투 서버에 '실시간 가격 좀 줘!'라고 요청하는 함수 """
        if not self.ws or not self.ws.sock or not self.ws.sock.connected:
            return
            
        # 1. 실시간 현재가(H0STCNT0) 구독 요청
        cnt_msg = {
            "header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
            "body": {"input": {"tr_id": "H0STCNT0", "tr_key": code}}
        }
        self.ws.send(json.dumps(cnt_msg))
        
        # 2. 실시간 호가잔량(H0STASP0) 구독 요청 (2차 방어막용)
        asp_msg = {
            "header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
            "body": {"input": {"tr_id": "H0STASP0", "tr_key": code}}
        }
        time.sleep(0.05) # 서버 과부하 방지 딜레이
        self.ws.send(json.dumps(asp_msg))
        
        self.sig_execution_msg.emit(f"📡 [{code}] 실시간 수익률 추적 모드 가동!", "info")

# =====================================================================
# 🖥️ 체결 수신기 미니 윈도우 UI 클래스
# =====================================================================
class FormTicker(QtWidgets.QWidget):
    def __init__(self, main_ui=None):
        super().__init__()
        self.main_ui = main_ui
        self.db = JubbyDB_Manager() # DB 매니저 장착
        
        self.setWindowTitle("⚡ 주삐 실시간 체결 Ticker")
        self.setFixedSize(340, 600) 
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        self.lbl_title = QtWidgets.QLabel("📡 실시간 체결 알림")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setStyleSheet("font-weight: bold; font-size: 14px; padding: 8px; background-color: #2b2b2b; color: white; border-radius: 5px;")
        layout.addWidget(self.lbl_title)
        
        self.lst_ticker = QtWidgets.QListWidget()
        self.lst_ticker.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: 'Consolas'; font-size: 11px; border: 1px solid #3c3c3c;")
        layout.addWidget(self.lst_ticker)
        
        self.ws_worker = RealWebSocketWorker(main_ui=self.main_ui)
        self.ws_worker.sig_execution_msg.connect(self.add_ticker_log)
        self.ws_worker.sig_real_execution.connect(self.update_main_ui_order)
        self.ws_worker.start()

        # =============================================================
        # ⭐ [핵심 추가 1] Ticker 창 잠금 및 마우스 드래그 상태 관리 변수
        # =============================================================
        self.is_locked = True       # 창이 켜질 때 기본적으로 이동 못하게 꽉 잠가둡니다.
        self._isDragging = False    # 현재 마우스로 창을 끌고(드래그) 있는지 확인하는 스위치
        self._startPos = QtCore.QPoint(0, 0) # 마우스를 클릭한 위치 저장용

    # =============================================================
    # ⭐ [핵심 추가 2] 마우스 클릭 이벤트 (잠금 해제 및 이동 준비)
    # =============================================================
    def mousePressEvent(self, event):
        # 1. 키보드의 'Ctrl' 키와 마우스의 '우클릭'을 동시에 눌렀는지 검사합니다.
        if event.modifiers() == Qt.ControlModifier and event.button() == Qt.RightButton:
            # 잠겨있으면 풀고, 풀려있으면 잠그는 스위치 역할 (상태 반전)
            self.is_locked = not self.is_locked
            
            # 상태에 따라 Ticker 창 리스트에 메세지를 띄워 사용자에게 알려줍니다.
            if self.is_locked:
                self.add_ticker_log("🔒 Ticker 창이 잠겼습니다. (이동 불가)", "warning")
            else:
                self.add_ticker_log("🔓 Ticker 창 잠금이 해제되었습니다. (이동 가능)", "success")
            
            event.accept() # 이벤트를 처리했으니 파이썬에게 작업 끝났다고 알림
            return

        # 2. 잠금이 풀려있는(False) 상태에서 마우스 '좌클릭'을 했을 때 창을 이동할 준비를 합니다.
        if event.button() == Qt.LeftButton and not self.is_locked:
            self._isDragging = True
            # 내가 윈도우 창의 어느 부분을 잡고 끌려는지 마우스 포인터의 갭(차이)을 계산해 둡니다.
            self._startPos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    # =============================================================
    # ⭐ [핵심 추가 3] 마우스 이동 이벤트 (실제로 창을 끌고 다님)
    # =============================================================
    def mouseMoveEvent(self, event):
        # 좌클릭을 누른 채로 드래그 중이고, 잠금이 풀려있을 때만 창이 마우스를 따라갑니다.
        if self._isDragging and event.buttons() == Qt.LeftButton and not self.is_locked:
            self.move(event.globalPos() - self._startPos) # 창 좌표 이동
            event.accept()

    # =============================================================
    # ⭐ [핵심 추가 4] 마우스 떼기 이벤트 (드래그 종료)
    # =============================================================
    def mouseReleaseEvent(self, event):
        # 마우스에서 손을 떼면 드래그 상태를 해제하여 멈춥니다.
        self._isDragging = False

    # =============================================================
    # ⭐ [핵심 추가 5] 창 닫기(X버튼) 방어막 (프로그램 재시작 에러 원인 해결)
    # =============================================================
    def closeEvent(self, event):
        # 수동으로 X 버튼을 눌러 창을 닫으면, 완전히 파괴(Destroy)되어 메인 엔진과 꼬입니다.
        # 따라서 파괴하지 않고 투명 망토를 씌워 '숨김(Hide)' 처리만 합니다.
        self.hide() 
        event.ignore() # X버튼의 원래 기능(프로그램 강제 종료)을 씹어버립니다.

    # (이하 기존 함수들 그대로 유지)
    @QtCore.pyqtSlot(str, str)
    def add_ticker_log(self, msg, msg_type="info"):
        if not msg.startswith("["):
            now_time = time.strftime("%H:%M:%S")
            msg = f"[{now_time}] {msg}"

        item = QtWidgets.QListWidgetItem(msg)
        
        if msg_type == "buy": 
            item.setForeground(QtGui.QColor("#FF4500")) 
            item.setFont(QtGui.QFont("Consolas", 11, QtGui.QFont.Bold))
        elif msg_type == "sell": 
            item.setForeground(QtGui.QColor("#00BFFF")) 
            item.setFont(QtGui.QFont("Consolas", 11, QtGui.QFont.Bold))
        elif msg_type == "success": 
            item.setForeground(QtGui.QColor("lime")) 
        elif msg_type == "error": 
            item.setForeground(QtGui.QColor("red"))
        elif msg_type == "warning": # 잠금 메세지용 노란색 추가
            item.setForeground(QtGui.QColor("yellow"))
        else: 
            item.setForeground(QtGui.QColor("#A0A0A0")) 
            
        self.lst_ticker.addItem(item)
        self.lst_ticker.scrollToBottom()

    def update_main_ui_order(self, exec_data):
        if not self.main_ui: return
        
        target_ono = str(exec_data.get('주문번호'))  # 서버에서 온 체결 주문번호
        target_symbol = exec_data.get('종목코드')
        filled_qty = int(exec_data.get('체결수량', 0))
        real_price = exec_data.get('체결가', 0)

        # 1. 메인 UI의 tbOrder(주문내역 표)를 가져옵니다.
        table = self.main_ui.tbOrder
        
        # 2. 표의 전체 헤더 이름을 읽어서 각 칸의 위치를 정확히 파악합니다.
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        try:
            ono_col = headers.index('주문번호')
            stat_col = headers.index('상태')
            qty_col = headers.index('체결수량')
            price_col = headers.index('주문가격')
        except ValueError:
            return # 헤더 이름이 안 맞으면 중단

        # 3. 표를 아래에서 위로 훑으면서 해당 주문번호를 찾습니다.
        for row in range(table.rowCount() - 1, -1, -1):
            ono_item = table.item(row, ono_col)
            if ono_item and ono_item.text() == target_ono:
                status_item = table.item(row, stat_col)
                
                # 4. '미체결' 상태인 녀석을 찾아 '체결완료' 도장을 쾅 찍어줍니다.
                if status_item and status_item.text() == "미체결":
                    status_item.setText("체결완료")
                    status_item.setForeground(QtGui.QColor("lime")) # 연두색 변경
                    
                    table.item(row, qty_col).setText(str(filled_qty))     # 체결수량 업데이트
                    table.item(row, price_col).setText(f"{real_price:,.0f}") # 체결가 업데이트
                    
                    # ⭐ [가장 중요] 체결이 확인되었으니, 이 종목의 실시간 현재가 수신을 시작합니다!
                    # 그래야 AutoTradeWorker가 실시간 가격을 보고 수익률을 계산합니다.
                    self.ws_worker.subscribe_stock_realtime(target_symbol)
                    break
                
    def snap_to_main(self):
        if not self.main_ui: return
        main_geo = self.main_ui.geometry()
        new_x = main_geo.right() + 5 
        new_y = main_geo.top()
        self.move(new_x, new_y)