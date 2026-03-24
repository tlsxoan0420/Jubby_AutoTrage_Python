import socket
import json
import struct
import threading
import time
import zlib
from datetime import datetime

# 💡 PyQt5의 pyqtSignal을 사용하기 위해 QObject를 상속받는 시그널 전용 클래스를 만듭니다.
try:
    from PyQt5.QtCore import pyqtSignal, QObject
    class ClientSignals(QObject):
        # C#에서 LOGIN_SUCCESS 명령이 오면 발동할 시그널
        sig_login_success = pyqtSignal()
        # 그 외에 텍스트나 데이터를 받을 때 쓸 시그널
        sig_message_received = pyqtSignal(dict)
except ImportError:
    ClientSignals = None

class TcpJsonClient:
    """
    Python → C# 통신용 TCP JSON 클라이언트
    기능:
    - 자동 재연결 방지 최적화
    - heartbeat 자동 전송
    - C# 서버로부터 데이터 수신 (Receive) 기능 추가! ⭐
    - 대량 데이터 송신 시 안정적 전송
    """
    
    Isconnected = False

    def __init__(self, host="127.0.0.1", port=9001,
                 use_compression=True,
                 heartbeat_interval=5):
        self.host = host
        self.port = port

        self.sock = None           
        self.lock = threading.Lock() 

        self.use_compression = use_compression
        self.heartbeat_interval = heartbeat_interval
        self._stop = False
        
        # UI 연동을 위한 시그널 객체 생성
        self.signals = ClientSignals() if ClientSignals else None

        # Heartbeat 스레드 실행
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._hb_thread.start()

        # 🟢 C#에서 오는 데이터를 받기 위한 수신 스레드 실행
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    # ------------------------------
    # TCP 서버(C#)에 연결
    # ------------------------------
    def connect(self):
        if self.sock is not None:
            print("[CLIENT] 이미 C# 서버에 연결되어 있습니다.")
            return

        start_time = time.time()  
        timeout = 3              # [수정] 3초로 단축 (UI가 먹통되는 현상 방지)

        while not self._stop:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                TcpJsonClient.Isconnected = False 
                print("[CLIENT] Connection timeout: 3 Sec passed. Stop trying.")
                return 

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((self.host, self.port))

                self.sock = s
                print("[CLIENT] Connected to C# server.")
                TcpJsonClient.Isconnected = True  
                return

            except Exception as e:
                print(f"[CLIENT] Connect failed: {e}. Retry in 1 sec...")
                time.sleep(1)

    # ------------------------------
    # 연결 종료
    # ------------------------------
    def close(self):
        self._stop = True
        TcpJsonClient.Isconnected = False  
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
                self.sock = None

    # ------------------------------
    # 메시지를 실제 TCP로 송신 (중복된 코드 깔끔하게 정리 완료!)
    # ------------------------------
    def _send_raw(self, payload: dict, compress_override=None):
        with self.lock:
            if self.sock is None:
                return

            try:
                # JSON 문자열 → UTF-8 bytes
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

                # 압축 여부 결정
                compressed = self.use_compression if compress_override is None else compress_override
                if compressed:
                    body = zlib.compress(body, wbits=-zlib.MAX_WBITS)

                # 헤더 구성 [1byte version][1byte flags][4byte length]
                version = 1
                flags = 0x01 if compressed else 0x00
                length = len(body)

                header = struct.pack("!BBI", version, flags, length)

                # 실제 송신
                self.sock.sendall(header + body)

            except Exception as e:
                print(f"[CLIENT] Send failed: {e}. Connection lost.")
                try:
                    self.sock.close()
                except:
                    pass

                self.sock = None
                TcpJsonClient.Isconnected = False  
                # (오류 무한루프 방지를 위해 자동 재연결(self.connect)은 빼는 것이 좋습니다)

    # ------------------------------
    # 🟢 [핵심 추가] C#에서 보낸 메시지를 수신하는 함수
    # ------------------------------
    def _receive_loop(self):
        while not self._stop:
            if self.sock is None or not TcpJsonClient.Isconnected:
                time.sleep(1)
                continue
                
            try:
                # 1. 헤더 (6바이트) 읽기
                header_data = self._recv_all(6)
                if not header_data:
                    self._handle_disconnect()
                    continue
                    
                version, flags, length = struct.unpack("!BBI", header_data)
                is_compressed = (flags & 0x01) != 0
                
                # 2. 바디(데이터 본문) 읽기
                body_data = self._recv_all(length)
                if not body_data:
                    self._handle_disconnect()
                    continue
                
                # 3. 압축 해제 및 JSON 파싱
                if is_compressed:
                    body_data = zlib.decompress(body_data, wbits=-zlib.MAX_WBITS)
                    
                json_str = body_data.decode("utf-8")
                payload = json.loads(json_str)
                
                # 4. 수신된 명령(Command) 처리
                self._process_received_payload(payload)
                
            except Exception as e:
                print(f"[CLIENT] Receive Error: {e}")
                self._handle_disconnect()
                time.sleep(1)

    def _recv_all(self, count):
        """정확히 count 바이트만큼 소켓에서 읽어옵니다."""
        buf = bytearray()
        while len(buf) < count:
            try:
                packet = self.sock.recv(count - len(buf))
                if not packet:
                    return None # 연결 끊김
                buf.extend(packet)
            except:
                return None
        return buf
        
    def _handle_disconnect(self):
        """수신 에러 발생 시 연결 초기화"""
        TcpJsonClient.Isconnected = False
        if self.sock:
            try: self.sock.close()
            except: pass
            self.sock = None

    def _process_received_payload(self, payload):
        """수신된 JSON 딕셔너리를 분석하여 명령을 수행합니다."""
        # 예시: C#에서 { "command": "LOGIN_SUCCESS" } 라고 보냈다고 가정
        command = payload.get("command", "")
        
        if command == "LOGIN_SUCCESS":
            print("🔓 [CLIENT] C#으로부터 로그인 성공 신호를 수신했습니다!")
            if self.signals:
                self.signals.sig_login_success.emit()
        else:
            if self.signals:
                self.signals.sig_message_received.emit(payload)


    # ------------------------------
    # JSON 메시지 포맷으로 전송
    # ------------------------------
    def send_message(self, msg_type: str, payload: dict = None, compress_override=None):
        msg = {
            "msg_type": msg_type,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
            "payload": payload
        }
        self._send_raw(msg, compress_override=compress_override)

    def send_data(self, price: float, order: str, extra: dict = None):
        payload = {"price": price, "order": order}
        if extra: payload.update(extra)
        self.send_message("data", payload)

    def send_log(self, text: str):
        self.send_message("log", {"text": text}, compress_override=False)

    # ------------------------------
    # HEARTBEAT 자동 전송 스레드
    # ------------------------------
    def _heartbeat_loop(self):
        while not self._stop:
            time.sleep(self.heartbeat_interval)
            try:
                if self.sock is not None and TcpJsonClient.Isconnected:
                    self.send_message("heartbeat", {"source": "python"}, compress_override=False)
            except:
                pass