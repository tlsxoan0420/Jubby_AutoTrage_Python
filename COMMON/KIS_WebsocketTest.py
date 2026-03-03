import asyncio
import websockets
import json
import sys
import os

# COM 폴더의 모듈을 가져오기 위한 경로 설정
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from COM.TcpJsonClient import TcpJsonClient  # ✨ C# 통신 클라이언트 임포트

class KIS_WebSocket:
    def __init__(self, approval_key, tcp_client=None, is_mock=True):
        self.approval_key = approval_key
        self.tcp_client = tcp_client  # ✨ C# 통신 클라이언트 객체 받기
        
        # 웹소켓 접속 URL (모의투자 / 실전투자 분기)
        if is_mock:
            self.url = "ws://ops.koreainvestment.com:31000/tryitout/H0STCNT0"
        else:
            self.url = "ws://ops.koreainvestment.com:21000/tryitout/H0STCNT0"

    async def connect_and_subscribe(self, stock_code="005930"):
        async with websockets.connect(self.url, ping_interval=None) as websocket:
            print("[✅ 연결 성공] 한국투자증권 실시간 웹소켓 서버에 접속했습니다.")
            
            # 구독 요청 데이터 조립
            req_data = {
                "header": {
                    "approval_key": self.approval_key,
                    "custtype": "P",
                    "tr_type": "1",
                    "content-type": "utf-8"
                },
                "body": {
                    "input": {
                        "tr_id": "H0STCNT0",
                        "tr_key": stock_code
                    }
                }
            }
            
            await websocket.send(json.dumps(req_data))
            print(f"[요청 완료] {stock_code} 실시간 데이터 구독을 시작합니다...\n")
            
            # 실시간 데이터 무한 수신 루프
            while True:
                try:
                    data = await websocket.recv()
                    
                    if data[0] == '0' or data[0] == '1': 
                        parts = data.split('|')
                        if len(parts) >= 4:
                            real_data = parts[3].split('^')
                            if len(real_data) > 2:
                                current_price = real_data[2] # 현재 체결가
                                volume = real_data[12]       # 체결 거래량
                                print(f"[🔥 실시간 체결] 종목: {stock_code} | 현재가: {current_price}원 | 체결량: {volume}주")
                                
                                # ✨ C# UI로 실시간 체결가 전송 ✨
                                if self.tcp_client and TcpJsonClient.Isconnected:
                                    self.tcp_client.send_data(
                                        price=float(current_price), 
                                        order="WAIT", 
                                        extra={"code": stock_code, "volume": volume}
                                    )
                    else:
                        print(f"[시스템 메시지] {data}")
                        # PINGPONG 메시지도 C# UI 로그창으로 보내서 생존 확인 ✨
                        if "PINGPONG" in data and self.tcp_client and TcpJsonClient.Isconnected:
                            self.tcp_client.send_log("KIS 서버와 정상 통신 중 (PINGPONG)")
                            
                except Exception as e:
                    print(f"[❌ 에러 발생] 웹소켓 연결 끊김: {e}")
                    if self.tcp_client and TcpJsonClient.Isconnected:
                        self.tcp_client.send_log(f"웹소켓 끊김: {e}")
                    break

# ==========================================
# 통합 테스트 실행 (C# 통신 + KIS 웹소켓)
# ==========================================
if __name__ == "__main__":
    MY_APPROVAL_KEY = "74d0d2ac-6400-49d2-b028-216fe0b722eb"
    
    # 1. C# 통신 클라이언트 실행 (포트 9001)
    print("C# UI(서버) 접속을 시도합니다...")
    my_tcp_client = TcpJsonClient(host="127.0.0.1", port=9001)
    my_tcp_client.connect() # C# 켜질 때까지 백그라운드에서 접속 시도함
    
    # 2. 웹소켓 클래스 생성 시 C# 클라이언트 객체 전달
    kis_ws = KIS_WebSocket(MY_APPROVAL_KEY, tcp_client=my_tcp_client, is_mock=True)
    
    # 3. 비동기 이벤트 루프 실행 (삼성전자 테스트)
    asyncio.run(kis_ws.connect_and_subscribe("005930"))