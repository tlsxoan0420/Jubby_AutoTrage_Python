import socket
import json
import struct
import threading
import time
import zlib
from datetime import datetime

class TcpJsonClient:
    """
    Python → C# 통신용 TCP JSON 클라이언트
    기능:
    - 자동 재연결
    - heartbeat 자동 전송
    - JSON 메시지를 C# 서버 프로토콜 형식(헤더 + 데이터)으로 전송
    - 대량 데이터 송신 시 안정적 전송
    """

    Isconnected = False;

    def __init__(self, host="127.0.0.1", port=9001,
                 use_compression=True,
                 heartbeat_interval=5):
        self.host = host
        self.port = port

        self.sock = None           # 실제 TCP 소켓
        self.lock = threading.Lock()  # send 시 스레드 충돌 방지용

        # 압축 사용 여부 (큰 JSON 전송 시 효율적)
        self.use_compression = use_compression

        # Heartbeat 주기 (초)
        self.heartbeat_interval = heartbeat_interval
        self._stop = False

        # Heartbeat 스레드 실행
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._hb_thread.start()

    # ------------------------------
    # TCP 서버(C#)에 연결
    # ------------------------------
    def connect(self):
    # C# TCP 서버에 자동 연결 시도 (실패 시 재시도), 30초 지나면 중단 #
        start_time = time.time()  # 시작 시간 기록
        timeout = 30              # 제한 시간(초)

        while not self._stop:
            # 1) 1분 초과 체크
            elapsed = time.time() - start_time
            if elapsed > timeout:
                self._stop = True
                print("[CLIENT] Connection timeout: 30 Sec passed. Stop trying.")
                return  # 그냥 종료하거나 self._stop = True로 바꿔도 됨

            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect((self.host, self.port))

                self.sock = s
                print("[CLIENT] Connected to C# server.")
                TcpJsonClient.Isconnected = True  # 연결 성공
                return

            except Exception as e:
                print(f"[CLIENT] Connect failed: {e}. Retry in 1 sec...")
                time.sleep(1)

    # ------------------------------
    # 연결 종료
    # ------------------------------
    def close(self):
        self._stop = True
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
                self.sock = None

    # ------------------------------
    # 메시지를 실제 TCP로 송신
    # ------------------------------
    def _send_raw(self, payload: dict, compress_override=None):
        """
        payload: JSON(dict)
        compress_override: True/False/None
        """
        with self.lock:
            # 연결 안되어 있으면 자동 연결
            if self.sock is None:
                self.connect()

            if self.sock is None:
                return

            try:
                # JSON 문자열 → UTF-8 bytes
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

                # 압축 여부 결정
                compressed = self.use_compression if compress_override is None else compress_override
                if compressed:
                    body = zlib.compress(body, wbits=-zlib.MAX_WBITS)

                # 헤더 구성
                # [1byte version][1byte flags][4byte length]
                version = 1
                flags = 0x01 if compressed else 0x00
                length = len(body)

                header = struct.pack("!BBI", version, flags, length)

                # 실제 송신
                self.sock.sendall(header + body)

            except Exception as e:
                print(f"[CLIENT] Send failed: {e}. Reconnecting...")
                try:
                    self.sock.close()
                except:
                    pass

                self.sock = None
                self.connect()

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

    # ------------------------------
    # 실제 데이터(예: price/order) 전송
    # ------------------------------
    def send_data(self, price: float, order: str, extra: dict = None):
        """C#에서 MsgType == "data" 로 처리됨"""
        payload = {"price": price, "order": order}
        if extra:
            payload.update(extra)

        self.send_message("data", payload)

    # ------------------------------
    # 로그(문자열) 전송
    # ------------------------------
    def send_log(self, text: str):
        self.send_message("log", {"text": text}, compress_override=False)

    # ------------------------------
    # HEARTBEAT 자동 전송 스레드
    # ------------------------------
    def _heartbeat_loop(self):
        while not self._stop:
            time.sleep(self.heartbeat_interval)
            try:
                # C#에서 Heartbeat는 MsgType=="heartbeat" 로 처리됨
                self.send_message("heartbeat", {"source": "python"}, compress_override=False)
            except:
                pass
