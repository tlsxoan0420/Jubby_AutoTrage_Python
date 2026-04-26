from datetime import datetime
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
                    # 🚀 [치명적 버그 수정] 한투 규격에 맞게 인덱스 번호를 완전히 맞췄습니다!
                    if len(content) < 15: return
                    try:
                        ccld_yn = content[13].strip() 
                        if ccld_yn != '1': return # '1'(체결)일 때만 반응합니다.
                        
                        # 🚀 [버그 완벽 수정 1: 체결 지연 해결]
                        # KIS 서버가 부여한 주문번호(예: 0000029486)에서 앞의 0을 지워버리면,
                        # DB에 저장된 원본(0000029486)과 매칭되지 않아 즉각적인 '체결완료' 업데이트가 누락됩니다.
                        # 따라서 .lstrip('0')을 삭제하고 원본 그대로 사용합니다!
                        order_no = content[2].strip()
                        
                        exec_data = {
                            "주문번호": order_no, 
                            "종목코드": content[8].strip(), # 🚀 3 -> 8 로 수정
                            "체결수량": int(content[9]),    # 🚀 5 -> 9 로 수정
                            "체결가": float(content[10]),   # 🚀 6 -> 10 으로 수정
                            "체결시간": f"{content[11][:2]}:{content[11][2:4]}:{content[11][4:6]}" if len(content[11]) >= 6 else content[11]
                        }
                        self.sig_real_execution.emit(exec_data)
                    except: pass
                    
                # 2. 실시간 현재가 및 체결강도 DB 저장 (H0STCNT0)
                elif tr_id_recv == "H0STCNT0":
                    content = parts[3].split('^')
                    if len(content) >= 23:
                        try:
                            symbol = content[0]
                            curr_price = float(content[2])
                            vol_power = float(content[22]) 
                            
                            query = """
                                INSERT INTO MarketStatus (symbol, last_price, vol_power)
                                VALUES (?, ?, ?)
                                ON CONFLICT(symbol) DO UPDATE SET
                                last_price = excluded.last_price,
                                vol_power = excluded.vol_power
                            """
                            # 🚀 [버그 완벽 수정] 팅김 방지! ws_conn.execute 직접 호출 대신, 
                            # DB가 잠겨있을 때 자동으로 대기했다가 처리해주는 만능 래퍼 함수 사용!
                            self.db.execute_with_retry(
                                self.db.shared_db_path, query, (symbol, curr_price, vol_power)
                            )
                        except: pass
                    elif len(content) >= 3:
                        try:
                            symbol = content[0]; curr_price = float(content[2])
                            query = """
                                INSERT INTO MarketStatus (symbol, last_price)
                                VALUES (?, ?)
                                ON CONFLICT(symbol) DO UPDATE SET
                                last_price = excluded.last_price
                            """
                            # 🚀 [수정] 여기도 동일하게 안전망 적용
                            self.db.execute_with_retry(
                                self.db.shared_db_path, query, (symbol, curr_price)
                            )
                        except: pass
                        
                # 3. 실시간 호가 잔량 DB 저장 (H0STASP0)
                elif tr_id_recv == "H0STASP0":
                    content = parts[3].split('^')
                    if len(content) >= 74:
                        try:
                            symbol = content[0]
                            total_ask_size = float(content[43]); total_bid_size = float(content[73])
                            
                            # 🚀 [수정] 무방비 UPDATE 대신 방어막 적용
                            query = "UPDATE MarketStatus SET ask_size = ?, bid_size = ? WHERE symbol = ?"
                            self.db.execute_with_retry(
                                self.db.shared_db_path, query, (total_ask_size, total_bid_size, symbol)
                            )
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

            # 🚨 [수정 전] 무조건 바구니에 밀어넣음 (바구니가 꽉 차면 여기서 프로그램이 영원히 멈춤/데드락)
            # self.msg_queue.put(message)

            try:
                # put_nowait은 대기하지 않고 즉시 넣습니다.
                self.msg_queue.put_nowait(message)
            except queue.Full:
                # 바구니가 꽉 찼다면? (큐 처리 속도보다 데이터 들어오는 속도가 빠를 때)
                try:
                    # 🛡️ [수정] 여러 스레드가 동시에 버리려고 할 때 발생하는 Empty 에러까지 안전하게 무시합니다.
                    self.msg_queue.get_nowait()          # 1. 젤 오래된 데이터 1개를 버림
                    self.msg_queue.put_nowait(message)   # 2. 방금 들어온 따끈따끈한 새 데이터를 넣음
                except queue.Empty:
                    pass
                except queue.Full:
                    pass

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
            
            # 🚀 [안정성 개선] 웹소켓이 끊기고 다시 연결을 시도하기 전, 접속키(Approval Key)를 새로 발급받습니다.
            self.sig_execution_msg.emit("🔄 웹소켓 재연결 시도 중... 접속키 갱신", "warning")
            time.sleep(3) # 증권사 서버 폭주 방지를 위해 3초 대기
            
            # 새로운 키를 발급받아 교체해줍니다. (토큰 만료로 인한 튕김 방지)
            new_key = self.api.get_approval_key()
            if new_key:
                self.approval_key = new_key

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

    def unsubscribe_stock_realtime(self, code):
        """ [추가] 매도 완료된 종목의 실시간 추적을 해제하여 40개 한도 꽉 참을 방지합니다. """
        if not self.ws or not self.ws.sock or not self.ws.sock.connected: return
        
        # 🔥 tr_type "2"가 바로 '구독 해제(Unsubscribe)' 명령입니다.
        self.ws.send(json.dumps({"header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "2", "content-type": "utf-8"},
                                 "body": {"input": {"tr_id": "H0STCNT0", "tr_key": code}}}))
        self.ws.send(json.dumps({"header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "2", "content-type": "utf-8"},
                                 "body": {"input": {"tr_id": "H0STASP0", "tr_key": code}}}))
        
        if code in self.tracked_symbols:
            self.tracked_symbols.remove(code)
        self.sig_execution_msg.emit(f"🔌 [{code}] 매도 완료! 실시간 시세 추적 해제 (웹소켓 트래픽 확보)", "warning")

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
        
        # 🚨 [수정 전] 무한정 쌓이는 바구니 (메모리 폭발 위험)
        # self.msg_queue = queue.Queue()

        # 💡 [수정 후] 1000개까지만 담는 바구니 (약 1초~2초 분량의 최신 데이터만 유지)
        self.msg_queue = queue.Queue(maxsize=1000)

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
        """ [최종 완성본] 무한 렉, DB 충돌 및 프로그램 강제종료 완벽 해결 버전 """
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

        # 🌟 1. 상태 판별 (취소인지, 체결인지, 부분체결인지 완벽 판별)
        db_status = "체결완료"
        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            # 기존 DB에 저장되어 있던 진짜 총 주문량과 체결량을 가져옵니다.
            cursor = conn.execute("SELECT quantity, filled_quantity FROM TradeHistory WHERE order_no = ?", (target_ono,))
            row = cursor.fetchone()
            
            if row:
                total_qty = int(row[0])
                prev_filled = int(row[1] if row[1] else 0)
                
                if is_cancel:
                    # 🚀 [버그 완벽 수정 1] 취소 알림이 온 경우!
                    # 기존에 체결된 게 1개라도 있다면 "부분체결/잔여취소", 아예 0개면 "주문취소"로 명확히 나눕니다.
                    if prev_filled > 0:
                        db_status = "부분체결/잔여취소"
                    else:
                        db_status = "주문취소"
                        
                    # 🚨 덮어쓰기 금지! 취소 알림의 수량(보통 남은 수량)을 무시하고, 기존 체결량을 그대로 유지합니다.
                    filled_qty = prev_filled 
                else:
                    # 🚀 [기존 수정 유지] 체결 알림이 온 경우 누적 합산!
                    new_filled_qty = prev_filled + filled_qty 
                    if new_filled_qty < total_qty:
                        db_status = "부분체결"
                    else:
                        db_status = "체결완료"
                    filled_qty = new_filled_qty 
        except: pass
        finally:
            if 'conn' in locals() and conn: conn.close()

        # 🌟 2. [가장 중요] DB에 상태를 쓰고 반드시 'commit(도장)'을 찍습니다.
        try:
            # 🔥 [DB 락 완벽 방어] FormTicker에서도 무조건 execute_with_retry를 써서 락(Lock)을 방지합니다.
            query = "UPDATE TradeHistory SET Status = ?, filled_quantity = ?, price = ? WHERE order_no = ?"
            rowcount = self.db.execute_with_retry(self.db.shared_db_path, query, (db_status, filled_qty, real_price, target_ono))
            
            # 🚀 [핵심 방어막] API 응답(미체결 저장)보다 웹소켓(체결 알림)이 0.1초 먼저 도착한 초희귀 케이스!
            if rowcount == 0 and not is_cancel and not is_detective:
                time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                short_time_str = datetime.now().strftime("%H:%M:%S")
                
                insert_query = '''INSERT INTO TradeHistory 
                    (time, symbol, symbol_name, type, price, quantity, order_no, Status, filled_quantity, order_price, order_time, order_yield) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'''
                
                self.db.execute_with_retry(
                    self.db.shared_db_path, 
                    insert_query, 
                    (time_str, target_symbol, "-", "알수없음", real_price, filled_qty, target_ono, db_status, filled_qty, real_price, short_time_str, "0.00%")
                )
                
                self.add_ticker_log(f"⚡ [초고속 체결] API 응답보다 웹소켓 체결이 빨라 선기록을 진행했습니다.", "warning")

        except Exception as e: 
            self.add_ticker_log(f"🚨 Ticker DB 업데이트 오류: {e}", "error")
        finally:
            if 'conn' in locals() and conn: conn.close()

        # =========================================================================
        # 🌟 3. [GUI 튕김 방지 완벽 적용] 화면을 직접 보지 않고 DB에서 정보 꺼내오기
        # =========================================================================
        # ❌ 일꾼이 UI(table)를 직접 만지면 프로그램이 튕깁니다! 화면 조작 코드 전부 삭제됨.
        # ✅ 대신, 방금 전 DB에 저장된 종목명과 주문 종류를 안전하게 읽어옵니다.
        order_type = "알수없음"
        stock_name = target_symbol

        try:
            conn = self.db._get_connection(self.db.shared_db_path)
            cursor = conn.execute("SELECT type, symbol_name FROM TradeHistory WHERE order_no = ?", (target_ono,))
            row = cursor.fetchone()
            if row:
                order_type = row[0] # 예: "SELL" 또는 "BUY"
                stock_name = row[1] # 예: "삼성전자"
        except: pass
        finally:
            if 'conn' in locals() and conn: conn.close()

        # 🚀 [완벽 복구 & 렉 방지] 사장님(Main UI)에게 표 새로고침을 요청합니다.
        # 단, 렉을 방지하기 위해 1초에 한 번만 호출되도록 방어막(Throttle)을 칩니다.
        if self.main_ui:
            now = time.time()
            # 마지막으로 새로고침을 요청한 지 1초가 지났을 때만 실행 (렉 방지)
            if not hasattr(self, 'last_refresh_time') or (now - self.last_refresh_time) > 1.0:
                self.last_refresh_time = now
                QtCore.QMetaObject.invokeMethod(self.main_ui, "refresh_order_table", QtCore.Qt.QueuedConnection)
                
                # 체결이 완료되었다면 메인 스레드에게 "데이터 C#으로 쏴라!" 라고 버튼 클릭 신호도 보냅니다.
                if db_status == "체결완료" or is_cancel:
                    QtCore.QMetaObject.invokeMethod(self.main_ui, "btnDataSendClickEvent", QtCore.Qt.QueuedConnection)
        
        # 🌟 4. 안전하게 가져온 정보로 로그 출력 및 웹소켓 구독 시작
        if is_cancel:
            self.add_ticker_log(f"🗑️ [취소완료] {stock_name} | 30초 경과 주문 정리됨", "warning")
        else:
            prefix = "🕵️‍♂️ [누락복구]" if is_detective else "💰 [체결알림]"
            log_icon = "🔵" if "BUY" in order_type or "매수" in order_type or "불타기" in order_type else "🔴"
            self.add_ticker_log(f"{prefix} {log_icon} {stock_name} | {db_status} | {real_price:,.0f}원 | {filled_qty}주", "success")
        
        if db_status == "체결완료" and not is_cancel:
            if target_symbol not in self.ws_worker.tracked_symbols:
                self.ws_worker.subscribe_stock_realtime(target_symbol)
                self.ws_worker.tracked_symbols.add(target_symbol)
            
            # 🔥 [잔고 완벽 동기화] 체결 완료 시, 탐정을 기다리지 않고 즉시 HTS 실제 잔고를 새로고침합니다!
            if self.main_ui:
                QtCore.QMetaObject.invokeMethod(self.main_ui, "load_real_holdings", QtCore.Qt.QueuedConnection)
                
    def snap_to_main(self):
        if not self.main_ui: return
        main_geo = self.main_ui.geometry()
        self.move(main_geo.right() + 5, main_geo.top())