import socket
import json
import struct
import threading
import time
import zlib
from datetime import datetime

class TcpJsonClient:
    def __init__(self, host="127.0.0.1", port=9001, use_compression=True):
        self.host = host
        self.port = port
        self.use_compression = use_compression
        
        self.sock = None
        self.lock = threading.Lock()
        self.is_connected = False
        self._stop = False
        
        # 1. 백그라운드 자동 연결 스레드 가동 (C# 서버와 연결을 담당)
        threading.Thread(target=self._connect_loop, daemon=True).start()
        
        # 🚀 [핵심 수정 추가] C# 서버가 통신을 끊지 않도록 10초마다 생존 신고(Heartbeat)를 하는 스레드 가동!
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _connect_loop(self):
        """서버가 꺼져있어도 죽지 않고 무한 재연결을 시도합니다."""
        while not self._stop:
            if self.sock is None:
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.connect((self.host, self.port))
                    self.sock = s
                    self.is_connected = True
                    print(f"✅ C# 차트 서버({self.port}번 포트) 실시간 렌더링 통신 연결 완료!")
                except Exception:
                    self.is_connected = False
            time.sleep(1.0) # 1초마다 연결 상태 확인

    # 🚀 [핵심 수정 추가] 생존 신고 발송 로직
    def _heartbeat_loop(self):
        """
        C# 서버의 TcpJsonServer는 50초 동안 아무 메시지도 오지 않으면 연결을 강제로 끊습니다.
        이를 방지하기 위해 10초마다 의미 없는(하지만 연결 유지용인) 'heartbeat' 메시지를 발송합니다.
        """
        while not self._stop:
            time.sleep(10.0) # 10초 대기
            if self.is_connected and self.sock:
                # C#은 MsgType이 "heartbeat"인 것을 받으면 LastHeartbeatTime을 갱신하고 연결을 유지합니다.
                self.send_message("heartbeat", {"status": "alive"})

    def send_message(self, msg_type, payload):
        """C#의 JubbyDataManager가 파싱할 수 있는 규격으로 발사합니다."""
        # 연결이 끊겨있거나 소켓이 없다면 발송 취소
        if not self.is_connected or self.sock is None:
            return
            
        # 여러 스레드가 동시에 데이터를 보낼 때 데이터가 섞이는 것을 방지(Lock)
        with self.lock:
            try:
                # 1. C# JsonMessage 모델 규격에 맞춘 JSON 패킹
                msg = {
                    "msg_type": msg_type,
                    "timestamp": datetime.now().isoformat(),
                    "payload": payload
                }
                
                # 파이썬 딕셔너리를 JSON 문자열로 바꾼 뒤 byte 형태로 인코딩
                body = json.dumps(msg, ensure_ascii=False).encode('utf-8')
                flags = 0x00
                
                # 2. C#의 DeflateStream이 읽을 수 있는 Raw 압축 모드
                # (데이터 크기를 줄여서 통신 속도를 극대화합니다)
                if self.use_compression:
                    flags = 0x01
                    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
                    body = compressor.compress(body) + compressor.flush()
                    
                # 3. [1byte 버전][1byte 압축플래그][4byte 길이] 헤더 조립
                # C# 서버는 이 헤더를 보고 본문(body)이 얼만큼의 크기인지 미리 파악합니다.
                header = struct.pack("!BBI", 1, flags, len(body))
                
                # 4. 빛의 속도로 발사! (헤더 + 본문)
                self.sock.sendall(header + body)
                
            except Exception as e:
                # 통신 에러 발생 시 소켓을 닫아 다음 루프(_connect_loop)에서 자동으로 재연결하게 함
                try: self.sock.close()
                except: pass
                self.sock = None
                self.is_connected = False