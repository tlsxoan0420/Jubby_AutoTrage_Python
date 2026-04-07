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
        self.hts_id = self.db.get_shared_setting("KIS_API", "HTS_ID", "") 
        
        is_mock_str = self.db.get_shared_setting("KIS_API", "IS_MOCK", "TRUE")
        self.is_mock = True if is_mock_str.upper() == "TRUE" else False
        
        # 2. 웹소켓 전용 접속키(Approval Key) 발급
        self.api = KIS_API(self.app_key, self.app_secret, "00000000", self.is_mock)
        self.approval_key = self.api.get_approval_key()

    def run(self):
        if not self.approval_key:
            self.sig_execution_msg.emit("🚨 접속키 발급 실패. 웹소켓을 켤 수 없습니다.", "error")
            return

        if not self.hts_id or self.hts_id == "HTS아이디입력":
            self.sig_execution_msg.emit("🚨 DB에 HTS_ID를 등록해주세요! (체결수신 필수)", "error")
            return

        ws_url = "ws://ops.koreainvestment.com:31000" if self.is_mock else "ws://ops.koreainvestment.com:21000"
        self.sig_execution_msg.emit(f"📡 한투 서버 접속 중... ({'모의' if self.is_mock else '실전'})", "info")

        # 실시간 데이터 수신 시 처리부
        def on_message(ws, message):
            if message in ["0", "1"]: return # 하트비트 무시
            
            if "|" in message:
                parts = message.split("|")
                if len(parts) >= 4:
                    tr_id_recv = parts[1]
                    
                    # ---------------------------------------------------------
                    # 🟢 1. 내 계좌 체결 통보 수신 (H0STCNI0 / H0STCNI9)
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
                            # UI 업데이트 신호 쏘기 (FormMain으로 데이터 전송)
                            self.sig_real_execution.emit(exec_data)
                            # 🔥 상세 로그는 표에서 종목명을 찾은 뒤 update_main_ui_order 함수에서 출력하도록 위임합니다!
                        except Exception as e: pass
                        
                    # ---------------------------------------------------------
                    # 🚀 2. 실시간 현재가/체결가 수신 (H0STCNT0) -> 수익률 갱신의 핵심!
                    # ---------------------------------------------------------
                    elif tr_id_recv == "H0STCNT0":
                        content = parts[3].split('^')
                        if len(content) >= 3:
                            try:
                                symbol = content[0] 
                                curr_price = float(content[2])
                                
                                # DB에 현재가를 직접 업데이트 (AutoTradeWorker가 이 값을 보고 수익률 계산함)
                                conn = self.db._get_connection(self.db.shared_db_path)
                                conn.execute("UPDATE MarketStatus SET last_price = ? WHERE symbol = ?", (curr_price, symbol))
                                conn.close() # 🔥 오토커밋 모드이므로 무조건 commit() 삭제!
                            except: pass

                    # ---------------------------------------------------------
                    # 🚀 3. 실시간 호가 잔량 수신 (H0STASP0) -> 2차 방어막용
                    # ---------------------------------------------------------
                    elif tr_id_recv == "H0STASP0":
                        content = parts[3].split('^')
                        if len(content) >= 74:
                            try:
                                symbol = content[0]
                                total_ask_size = float(content[43])
                                total_bid_size = float(content[73])
                                
                                conn = self.db._get_connection(self.db.shared_db_path)
                                conn.execute("UPDATE MarketStatus SET ask_size = ?, bid_size = ? WHERE symbol = ?", 
                                            (total_ask_size, total_bid_size, symbol))
                                conn.close() # 🔥 여기도 commit() 무조건 삭제!
                            except: pass
            else:
                # 시스템 메시지 처리 (JSON)
                try:
                    res = json.loads(message)
                    if res.get("header", {}).get("tr_id") == "PINGPONG": ws.send(message)
                    msg1 = res.get('body', {}).get('msg1', '')
                    if msg1: self.sig_execution_msg.emit(f"✅ {msg1}", "success")
                except: pass

        def on_open(ws):
            self.sig_execution_msg.emit("🌐 실시간 서버 접속 완료!", "success")
            
            # 1. 계좌 체결 감시 구독 시작
            tr_id = "H0STCNI9" if self.is_mock else "H0STCNI0"
            sub_msg = {"header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                       "body": {"input": {"tr_id": tr_id, "tr_key": self.hts_id}}}
            ws.send(json.dumps(sub_msg))
            
            # 2. 기존 감시 종목들도 즉시 실시간 추적 시작
            if self.main_ui and hasattr(self.main_ui, 'DYNAMIC_STOCK_DICT'):
                for code in self.main_ui.DYNAMIC_STOCK_DICT.keys():
                    self.subscribe_stock_realtime(code)

        # 웹소켓 앱 구동
        self.ws = websocket.WebSocketApp(
            ws_url, on_open=on_open, on_message=on_message, 
            on_error=lambda w, e: self.sig_execution_msg.emit(f"🚨 웹소켓 오류: {e}", "error"),
            on_close=lambda w, c, m: self.sig_execution_msg.emit("🔌 웹소켓 연결 종료", "warning")
        )
        
        while self.is_running:
            self.ws.run_forever()
            if not self.is_running: break
            time.sleep(3) # 자동 재연결

    def stop(self):
        self.is_running = False
        if self.ws: self.ws.close()
        self.quit(); self.wait()

    def subscribe_stock_realtime(self, code):
        """ [중요] 특정 종목을 실시간 감시 리스트에 추가합니다 (수익률 업데이트용) """
        if not self.ws or not self.ws.sock or not self.ws.sock.connected: return
        
        # 현재가 구독 (H0STCNT0)
        self.ws.send(json.dumps({"header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                                 "body": {"input": {"tr_id": "H0STCNT0", "tr_key": code}}}))
        # 호가잔량 구독 (H0STASP0)
        self.ws.send(json.dumps({"header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                                 "body": {"input": {"tr_id": "H0STASP0", "tr_key": code}}}))
        
        self.sig_execution_msg.emit(f"📡 [{code}] 실시간 시세 추적 가동!", "info")

# =====================================================================
# 🖥️ Ticker UI 메인 윈도우
# =====================================================================
class FormTicker(QtWidgets.QWidget):
    def __init__(self, main_ui=None):
        super().__init__()
        self.main_ui = main_ui
        self.db = JubbyDB_Manager()
        
        self.setWindowTitle("⚡ 주삐 실시간 Ticker")
        self.setFixedSize(340, 600) 
        self.setWindowFlags(Qt.Window | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        
        layout = QtWidgets.QVBoxLayout(self)
        self.lst_ticker = QtWidgets.QListWidget()
        self.lst_ticker.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: 'Consolas'; font-size: 11px;")
        layout.addWidget(self.lst_ticker)
        
        self.ws_worker = RealWebSocketWorker(main_ui=self.main_ui)
        self.ws_worker.sig_execution_msg.connect(self.add_ticker_log)
        self.ws_worker.sig_real_execution.connect(self.update_main_ui_order)
        self.ws_worker.start()

        self.is_locked = True  
        self._isDragging = False 

    def mousePressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.button() == Qt.RightButton:
            self.is_locked = not self.is_locked
            self.add_ticker_log("🔓 Ticker 잠금 해제" if not self.is_locked else "🔒 Ticker 잠김", "warning")
            event.accept(); return
        if event.button() == Qt.LeftButton and not self.is_locked:
            self._isDragging = True
            self._startPos = event.globalPos() - self.frameGeometry().topLeft(); event.accept()

    def mouseMoveEvent(self, event):
        if self._isDragging and not self.is_locked:
            self.move(event.globalPos() - self._startPos); event.accept()

    def mouseReleaseEvent(self, event): self._isDragging = False

    def closeEvent(self, event): self.hide(); event.ignore()

    @QtCore.pyqtSlot(str, str)
    def add_ticker_log(self, msg, msg_type="info"):
        item = QtWidgets.QListWidgetItem(f"[{time.strftime('%H:%M:%S')}] {msg}")
        colors = {"buy": "#FF4500", "sell": "#00BFFF", "success": "lime", "error": "red", "warning": "yellow"}
        item.setForeground(QtGui.QColor(colors.get(msg_type, "#A0A0A0")))
        self.lst_ticker.addItem(item); self.lst_ticker.scrollToBottom()

    def update_main_ui_order(self, exec_data):
        """ [가장 중요] 한투 체결 통보를 메인 UI 표에 즉시 반영합니다. """
        if not self.main_ui: return
        
        target_ono = str(exec_data.get('주문번호')) 
        target_symbol = exec_data.get('종목코드')
        filled_qty = int(exec_data.get('체결수량', 0))
        real_price = exec_data.get('체결가', 0)

        # 메인 UI의 주문 내역 표 가져오기
        table = self.main_ui.tbOrder
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        
        try:
            # 헤더 이름을 기준으로 컬럼 위치를 찾습니다 (유연한 대응)
            ono_col = headers.index('주문번호')
            stat_col = headers.index('상태')
            qty_col = headers.index('체결수량')
            price_col = headers.index('주문가격')
        except: return

        # 표를 거꾸로 뒤져서 내 주문번호와 맞는 줄을 찾습니다.
        for row in range(table.rowCount() - 1, -1, -1):
            ono_item = table.item(row, ono_col)
            if ono_item and ono_item.text() == target_ono:
                status_item = table.item(row, stat_col)
                
                if status_item and status_item.text() == "미체결":
                    status_item.setText("체결완료")
                    status_item.setForeground(QtGui.QColor("lime")) 
                    
                    table.item(row, qty_col).setText(str(filled_qty))
                    table.item(row, price_col).setText(f"{real_price:,.0f}")
                    
                    # 🚀 [추가] 표에서 데이터를 읽어와 아주 상세하고 예쁜 Ticker 한글 로그를 띄웁니다!
                    order_type = table.item(row, headers.index('주문종류')).text()
                    stock_name = table.item(row, headers.index('종목명')).text()
                    
                    # 🔥 탐정이 잡아낸 건지, 진짜 웹소켓이 온 건지 접두사로 구분!
                    prefix = "🕵️‍♂️ [누락복구]" if exec_data.get('is_detective') else "💰 [체결완료]"
                    log_icon = "🔵" if "매수" in order_type or "불타기" in order_type else "🔴"
                    
                    self.add_ticker_log(f"{prefix} {log_icon} {stock_name} | {order_type} | {real_price:,.0f}원 | {filled_qty}주", "success")
                    
                    # ⭐ 체결 즉시 실시간 수익률 계산을 위해 시세 추적을 시작합니다!
                    self.ws_worker.subscribe_stock_realtime(target_symbol)

                    # 🔥 [C# UI 완벽 동기화 추가]
                    # DB의 TradeHistory 상태를 업데이트해야 C# 화면에서도 즉각 '체결완료'가 뜹니다!
                    try:
                        conn = self.db._get_connection(self.db.shared_db_path)
                        conn.execute("UPDATE TradeHistory SET Status = '체결완료', filled_quantity = ?, price = ? WHERE order_no = ?", (filled_qty, real_price, target_ono))
                        conn.close()
                    except Exception as e:
                        print(f"TradeHistory DB 업데이트 에러: {e}")
                        
                    break
                
    def snap_to_main(self):
        if not self.main_ui: return
        main_geo = self.main_ui.geometry()
        self.move(main_geo.right() + 5, main_geo.top())