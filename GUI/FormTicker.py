import json
import time
import websocket # 🚨 CMD에서 pip install websocket-client 필수
import threading
import queue     # 👈 [추가] 바구니 역할을 할 모듈
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtCore import Qt, QThread, pyqtSignal

from COMMON.Flag import SystemConfig
from COMMON.DB_Manager import JubbyDB_Manager
from COMMON.KIS_Manager import KIS_API

# =====================================================================
# 👨‍🔧 [신규 추가] 데이터 처리 전담 스레드 (Consumer)
# =====================================================================
class MessageProcessorWorker(QThread):
    sig_execution_msg = pyqtSignal(str, str) # Ticker 창에 텍스트 띄우기용
    sig_real_execution = pyqtSignal(dict)    # 메인 UI로 데이터 넘기기용

    def __init__(self, msg_queue, main_ui=None):
        super().__init__()
        self.msg_queue = msg_queue
        self.main_ui = main_ui
        self.is_running = True
        self.db = JubbyDB_Manager()
        self.ws_conn = None

    def run(self):
        # 🔥 스레드가 시작될 때 자기만의 DB 연결 고속도로를 뚫습니다.
        self.ws_conn = self.db._get_connection(self.db.shared_db_path)
        
        while self.is_running:
            try:
                # 1. 바구니(Queue)에서 메시지를 꺼냅니다. (데이터 없으면 최대 1초 대기)
                raw_message = self.msg_queue.get(timeout=1.0)
                
                # 2. 메시지 파싱 및 DB 저장
                self.process_message(raw_message)
                
                # 3. 작업 완료 처리
                self.msg_queue.task_done()
            except queue.Empty:
                continue 
            except Exception as e:
                pass

    def process_message(self, message):
        if message in ["0", "1"]: return 
        
        if "|" in message:
            parts = message.split("|")
            if len(parts) >= 4:
                tr_id_recv = parts[1]
                
                # 1. 내 계좌 체결 통보 파싱 (H0STCNI0 / H0STCNI9)
                if tr_id_recv in ["H0STCNI0", "H0STCNI9"]:
                    content = parts[3].split('^')
                    if len(content) < 12: return
                    try:
                        exec_data = {
                            "주문번호": content[1], "종목코드": content[3], 
                            "체결수량": int(content[5]), "체결가": float(content[6]), 
                            "체결시간": f"{content[7][:2]}:{content[7][2:4]}:{content[7][4:6]}"
                        }
                        self.sig_real_execution.emit(exec_data)
                    except: pass
                    
                # 2. 실시간 현재가 DB 저장 (H0STCNT0)
                elif tr_id_recv == "H0STCNT0":
                    content = parts[3].split('^')
                    if len(content) >= 3:
                        try:
                            symbol = content[0]; curr_price = float(content[2])
                            self.ws_conn.execute("UPDATE MarketStatus SET last_price = ? WHERE symbol = ?", (curr_price, symbol))
                        except: pass 

                # 3. 실시간 호가 잔량 DB 저장 (H0STASP0)
                elif tr_id_recv == "H0STASP0":
                    content = parts[3].split('^')
                    if len(content) >= 74:
                        try:
                            symbol = content[0]
                            total_ask_size = float(content[43]); total_bid_size = float(content[73])
                            self.ws_conn.execute("UPDATE MarketStatus SET ask_size = ?, bid_size = ? WHERE symbol = ?", 
                                        (total_ask_size, total_bid_size, symbol))
                        except: pass
        else:
            # 4. 시스템 메시지 처리
            try:
                res = json.loads(message)
                msg1 = res.get('body', {}).get('msg1', '')
                if msg1: self.sig_execution_msg.emit(f"✅ {msg1}", "success")
            except: pass

    def stop(self):
        self.is_running = False
        if self.ws_conn:
            try: self.ws_conn.close()
            except: pass
        self.quit()
        self.wait()

# =====================================================================
# 📡 [실전용] 한투 실시간 웹소켓 체결 수신 스레드
# =====================================================================
class RealWebSocketWorker(QThread):
    sig_execution_msg = pyqtSignal(str, str) # Ticker 창에 텍스트 띄우기용 (메시지, 타입)
    sig_real_execution = pyqtSignal(dict)    # 메인 UI(FormMain)로 데이터 넘기기용

    def __init__(self, msg_queue, main_ui=None):
        super().__init__()
        self.msg_queue = msg_queue # 👈 바구니 연결
        self.main_ui = main_ui
        self.is_running = True
        self.db = JubbyDB_Manager()
        self.ws = None
        self.tracked_symbols = set()

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

        # 🔥 [핵심 추가] 웹소켓이 살아있는 동안 평생 재사용할 전용 DB 고속도로 개통!
        self.ws_conn = self.db._get_connection(self.db.shared_db_path)

        # 실시간 데이터 수신 시 처리부
        def on_message(ws, message):
            if message in ["0", "1"]: return 

            # 🏓 핑퐁(PINGPONG) 메시지는 즉시 웹소켓으로 응답해야 연결이 유지됩니다!
            if "PINGPONG" in message:
                try:
                    res = json.loads(message)
                    if res.get("header", {}).get("tr_id") == "PINGPONG":
                        ws.send(message)
                        return
                except: pass

            # 🚀 [극한의 다이어트] 그 외의 모든 메시지는 파싱 없이 바구니에 던지고 즉시 끝냅니다!
            self.msg_queue.put(message)

        def on_open(ws):
            self.sig_execution_msg.emit("🌐 실시간 서버 접속 완료!", "success")
            
            # 1. 계좌 체결 감시 구독 시작
            tr_id = "H0STCNI9" if self.is_mock else "H0STCNI0"
            sub_msg = {"header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                       "body": {"input": {"tr_id": tr_id, "tr_key": self.hts_id}}}
            ws.send(json.dumps(sub_msg))
            
            # 🚀 [완벽 수정] 전체 명단(2500개)이 아니라, '현재 내 계좌에 있는 종목'만 조용히 구독합니다!
            if self.main_ui and hasattr(self.main_ui, 'my_holdings'):
                for code in list(self.main_ui.my_holdings.keys()):
                    if code not in self.tracked_symbols:
                        self.subscribe_stock_realtime(code)
                        self.tracked_symbols.add(code)

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
        if self.ws: 
            self.ws.close()
        
        # 🚨 웹소켓 스레드는 이제 DB를 안 쓰므로 ws_conn.close() 관련 코드는 전부 삭제합니다!
        
        self.quit()
        self.wait()

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
        
        # 🧺 두 스레드가 데이터를 주고받을 안전한 바구니 생성
        self.msg_queue = queue.Queue()

        # 👨‍🔧 1. 처리 전담 스레드 생성 및 시작 (Consumer)
        self.msg_processor = MessageProcessorWorker(self.msg_queue, main_ui=self.main_ui)
        self.msg_processor.sig_execution_msg.connect(self.add_ticker_log)
        self.msg_processor.sig_real_execution.connect(self.update_main_ui_order)
        self.msg_processor.start()

        # 📡 2. 수신 전담 스레드 생성 및 시작 (Producer) -> 바구니를 건네줍니다
        self.ws_worker = RealWebSocketWorker(self.msg_queue, main_ui=self.main_ui)
        self.ws_worker.sig_execution_msg.connect(self.add_ticker_log)
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

        # 🔥 [새로 추가] 화면에 띄움과 동시에 TickerLogs 테이블에도 저장합니다!
        try:
            # self.db가 FormMain에 선언되어 있으므로 이를 사용합니다.
            self.db.insert_ticker_log(msg_type.upper(), msg)
        except Exception as e:
            # DB 저장에 실패하더라도 화면 표시는 문제없이 넘어가도록 예외 처리
            print(f"Ticker DB 저장 실패: {e}")

    def update_main_ui_order(self, exec_data):
        """ [최종 완성본] 무한 렉 및 DB 충돌 완벽 해결 버전 """
        if not self.main_ui: return
        
        target_ono = str(exec_data.get('주문번호')) 
        target_symbol = exec_data.get('종목코드')
        filled_qty = int(exec_data.get('체결수량', 0))
        real_price = exec_data.get('체결가', 0)
        
        is_cancel = exec_data.get('is_cancel', False)
        is_detective = exec_data.get('is_detective', False)

        # 🚨 [치명적 버그 수정] 한투 서버의 '주문 접수' 알림(0주 체결)을 무시합니다.
        # 이걸 무시하지 않으면 0주 체결인데 표에서는 '체결완료'로 덮어씌워져서 앱이랑 달라집니다!
        if filled_qty == 0 and not is_cancel:
            return

        # 🌟 1. 상태 판별 (취소인지, 체결인지, 부분체결인지)
        db_status = "체결완료"
        if is_cancel:
            db_status = "주문취소"
        else:
            try:
                conn = self.db._get_connection(self.db.shared_db_path)
                cursor = conn.execute("SELECT quantity FROM TradeHistory WHERE order_no = ?", (target_ono,))
                row = cursor.fetchone()
                if row and 0 < filled_qty < int(row[0]):
                    db_status = "부분체결"
            except: pass
            finally:
                if 'conn' in locals() and conn: conn.close()

        # 🌟 2. [가장 중요] DB에 상태를 쓰고 반드시 'commit(도장)'을 찍습니다.
        # 이 도장을 찍어야 '탐정'이 DB를 보고 "아, 처리됐구나" 하고 멈춥니다!
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            conn.execute("UPDATE TradeHistory SET Status = ?, filled_quantity = ?, price = ? WHERE order_no = ?", 
                         (db_status, filled_qty, real_price, target_ono))
            conn.commit() # 🔥 필수! 이게 없으면 탐정이 5초마다 계속 신호를 보내서 렉이 걸립니다.
        except: pass
        finally:
            if 'conn' in locals() and conn: conn.close()

        # 🌟 3. UI(표) 업데이트 로직
        table = self.main_ui.tbOrder
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        try:
            ono_col = headers.index('주문번호'); stat_col = headers.index('상태')
            qty_col = headers.index('체결수량'); price_col = headers.index('주문가격')
        except: return

        for row in range(table.rowCount() - 1, -1, -1):
            ono_item = table.item(row, ono_col)
            if ono_item and ono_item.text() == target_ono:
                status_item = table.item(row, stat_col)
                if status_item and status_item.text() == db_status: break 

                if status_item and status_item.text() in ["미체결", "부분체결"]:
                    # 🚀 [완벽 수정 2] 일꾼이 UI를 직접 만지면 프로그램이 팅깁니다! 강제 조작 코드 삭제!
                    # DB에 값은 이미 써뒀으니, 메인 UI한테 "안전하게 표 다시 그려!"라고 지시만 내리고 빠집니다.
                    if self.main_ui:
                        QtCore.QMetaObject.invokeMethod(self.main_ui, "refresh_order_table", QtCore.Qt.QueuedConnection)
                    
                    order_type = table.item(row, headers.index('주문종류')).text()
                    stock_name = table.item(row, headers.index('종목명')).text()
                    
                    # (아래 로그 출력과 구독 코드는 기존과 완벽히 동일하게 유지)
                    if is_cancel:
                        self.add_ticker_log(f"🗑️ [취소완료] {stock_name} | 30초 경과 주문 정리됨", "warning")
                    else:
                        prefix = "🕵️‍♂️ [누락복구]" if is_detective else "💰 [체결알림]"
                        log_icon = "🔵" if "매수" in order_type or "불타기" in order_type else "🔴"
                        self.add_ticker_log(f"{prefix} {log_icon} {stock_name} | {db_status} | {real_price:,.0f}원 | {filled_qty}주", "success")
                    
                    if db_status == "체결완료" and not is_cancel:
                        if target_symbol not in self.ws_worker.tracked_symbols:
                            self.ws_worker.subscribe_stock_realtime(target_symbol)
                            self.ws_worker.tracked_symbols.add(target_symbol)
                    break
                
    def snap_to_main(self):
        if not self.main_ui: return
        main_geo = self.main_ui.geometry()
        self.move(main_geo.right() + 5, main_geo.top())