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
        
        # 백그라운드 자동 연결 스레드 가동
        threading.Thread(target=self._connect_loop, daemon=True).start()

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

    def send_message(self, msg_type, payload):
        """C#의 JubbyDataManager가 파싱할 수 있는 규격으로 발사합니다."""
        if not self.is_connected or self.sock is None:
            return
            
        with self.lock:
            try:
                # 1. C# JsonMessage 모델 규격에 맞춘 JSON 패킹
                msg = {
                    "msg_type": msg_type,
                    "timestamp": datetime.now().isoformat(),
                    "payload": payload
                }
                
                body = json.dumps(msg, ensure_ascii=False).encode('utf-8')
                flags = 0x00
                
                # 2. C#의 DeflateStream이 읽을 수 있는 Raw 압축 모드
                if self.use_compression:
                    flags = 0x01
                    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
                    body = compressor.compress(body) + compressor.flush()
                    
                # 3. [1byte 버전][1byte 압축플래그][4byte 길이] 헤더 조립
                header = struct.pack("!BBI", 1, flags, len(body))
                
                # 4. 빛의 속도로 발사!
                self.sock.sendall(header + body)
                
            except Exception as e:
                # 통신 에러 발생 시 소켓을 닫아 다음 루프에서 재연결하게 함
                try: self.sock.close()
                except: pass
                self.sock = None
                self.is_connected = False