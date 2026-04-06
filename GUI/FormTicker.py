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

    def __init__(self):
        super().__init__()
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

        def on_message(ws, message):
            # 기본 응답 처리
            if message in ["0", "1"]: return
            
            # 실시간 데이터 파싱 (파이프 '|' 구분자)
            if "|" in message:
                parts = message.split("|")
                if len(parts) >= 4:
                    tr_id_recv = parts[1]
                    # 체결통보 TR_ID 확인
                    if tr_id_recv in ["H0STCNI0", "H0STCNI9"]:
                        # 상세 데이터 파싱 (캐럿 '^' 구분자)
                        content = parts[3].split('^')
                        if len(content) < 12: return
                        
                        try:
                            order_no = content[2].strip()     # 주문번호 (ODNO)
                            side_code = content[4].strip()    # 02:매수, 01:매도
                            symbol = content[7].strip()       # 종목코드
                            if symbol.startswith('A'): symbol = symbol[1:]

                            filled_qty = int(content[10]) if content[10] else 0      # 이번 체결 수량
                            filled_price = float(content[11]) if content[11] else 0.0 # 체결 단가
                            
                            # 🚀 [Ticker 로그 강화] 체결 수량이 있을 때만 로그 남김
                            if filled_qty > 0:
                                side = "매수" if side_code == "02" else "매도"
                                now = time.strftime("%H:%M:%S")
                                
                                # 시각적인 효과를 위한 아이콘 추가
                                icon = "🔥" if side == "매수" else "📉"
                                msg = f"[{now}] {icon} [{side} 완료] {symbol} | {filled_qty}주 | {filled_price:,.0f}원"
                                self.sig_execution_msg.emit(msg, "buy" if side=="매수" else "sell")
                                
                                # 메인 UI 동기화를 위해 모든 핵심 데이터 전송
                                self.sig_real_execution.emit({
                                    '주문번호': order_no, 
                                    '종목코드': symbol, 
                                    '체결수량': filled_qty,
                                    '체결가': filled_price,
                                    '체결시간': now
                                })
                        except Exception as e:
                            print(f"Ticker Parsing Error: {e}")
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
        
        # 🌟 진짜 웹소켓 스레드 실행
        self.ws_worker = RealWebSocketWorker()
        self.ws_worker.sig_execution_msg.connect(self.add_ticker_log)
        self.ws_worker.sig_real_execution.connect(self.update_main_ui_order)
        self.ws_worker.start()

    @QtCore.pyqtSlot(str, str)
    def add_ticker_log(self, msg, msg_type="info"):
        """ Ticker 창에 컬러 로그를 추가합니다. """
        # 시간 자동 추가 (이미 있으면 패스)
        if not msg.startswith("["):
            now_time = time.strftime("%H:%M:%S")
            msg = f"[{now_time}] {msg}"

        item = QtWidgets.QListWidgetItem(msg)
        
        # 🎨 매수/매도 성격에 따른 강렬한 색상 부여
        if msg_type == "buy": 
            item.setForeground(QtGui.QColor("#FF4500")) # OrangeRed (매수)
            item.setFont(QtGui.QFont("Consolas", 11, QtGui.QFont.Bold))
        elif msg_type == "sell": 
            item.setForeground(QtGui.QColor("#00BFFF")) # DeepSkyBlue (매도)
            item.setFont(QtGui.QFont("Consolas", 11, QtGui.QFont.Bold))
        elif msg_type == "success": 
            item.setForeground(QtGui.QColor("lime")) 
        elif msg_type == "error": 
            item.setForeground(QtGui.QColor("red"))
        else: 
            item.setForeground(QtGui.QColor("#A0A0A0")) # 기본 회색
            
        self.lst_ticker.addItem(item)
        self.lst_ticker.scrollToBottom()

    def update_main_ui_order(self, exec_data):
        """ [상급 노하우] 주문번호 기반 DB 동기화 및 메인 UI 표 색상 변경 """
        if not self.main_ui: return
        
        target_ono = str(exec_data.get('주문번호')) 
        target_symbol = exec_data.get('종목코드')
        filled_qty = int(exec_data.get('체결수량', 0))
        real_price = exec_data.get('체결가', 0)
        real_time = exec_data.get('체결시간', time.strftime("%H:%M:%S"))

        # -------------------------------------------------------------
        # 🛡️ [네트워크 지연 방어] 리트라이 로직 (DB에 주문이 먼저 쌓일 때까지 대기)
        # -------------------------------------------------------------
        found_in_db = False
        for attempt in range(5): # 0.1초씩 최대 0.5초 대기
            conn = self.db._get_connection(self.db.shared_db_path)
            try:
                # 🚀 핵심: 주문번호(ODNO)로 '미체결' 건을 정확히 찾아냅니다.
                cursor = conn.execute("SELECT id FROM TradeHistory WHERE order_no = ? AND Status = '미체결'", (target_ono,))
                row_db = cursor.fetchone()
                
                if row_db:
                    # 🎯 찾았다! 상태를 '체결완료'로 바꾸고 실제 체결 가격과 시간으로 덮어씁니다.
                    conn.execute("""
                        UPDATE TradeHistory 
                        SET Status = '체결완료', filled_quantity = ?, order_price = ?, order_time = ?
                        WHERE id = ?
                    """, (filled_qty, real_price, real_time, row_db[0]))
                    conn.commit()
                    found_in_db = True
                    break 
            except: pass
            finally: conn.close()
            
            if not found_in_db: time.sleep(0.1) 

        # -------------------------------------------------------------
        # 2. PyQt 메인 UI 테이블(tbOrder) 실시간 연두색 업데이트
        # -------------------------------------------------------------
        table = self.main_ui.tbOrder
        headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
        
        try:
            stat_col = headers.index('상태')
            qty_col = headers.index('체결수량')
            price_col = headers.index('주문가격')
            ono_col = headers.index('주문번호') if '주문번호' in headers else -1
        except: return

        # 거꾸로 순회하며 해당 주문번호를 찾아 업데이트
        for row in range(table.rowCount() - 1, -1, -1):
            is_match = False
            if ono_col != -1:
                ono_item = table.item(row, ono_col)
                if ono_item and ono_item.text() == target_ono: is_match = True
            else:
                # 주문번호 열이 없는 경우 종목코드로 백업 매칭
                sym_item = table.item(row, headers.index('종목코드'))
                if sym_item and sym_item.text() == target_symbol: is_match = True

            if is_match:
                status_item = table.item(row, stat_col)
                # '미체결' 상태일 때만 연두색으로 변경 (중복 업데이트 방지)
                if status_item and status_item.text() == "미체결":
                    status_item.setText("체결완료")
                    status_item.setForeground(QtGui.QColor("lime")) # 갓벽한 연두색!
                    
                    # 실제 체결 수량과 가격으로 UI 덮어쓰기
                    table.item(row, qty_col).setText(str(filled_qty))
                    table.item(row, price_col).setText(f"{real_price:,.0f}")
                    break
                
    def snap_to_main(self):
        """ 메인 윈도우의 오른쪽 옆구리에 딱 붙게 위치를 조정합니다. """
        if not self.main_ui: return
        
        # 1. 메인 윈도우의 현재 위치와 크기를 가져옵니다.
        main_geo = self.main_ui.geometry()
        
        # 2. 메인 윈도우의 오른쪽(Right) 좌표 + 여백(5픽셀)에 위치시킵니다.
        # 높이는 메인 윈도우와 똑같은 높이(Top)에 맞춥니다.
        new_x = main_geo.right() + 5 
        new_y = main_geo.top()
        
        self.move(new_x, new_y)