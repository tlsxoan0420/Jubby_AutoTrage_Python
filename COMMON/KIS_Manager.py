import requests    # REST API 통신용 (토큰, 주문, 잔고)
import json        # 데이터 변환용
import asyncio     # 비동기 처리용 (웹소켓)
import websockets  # 웹소켓 통신용 (실시간 시세)
import threading   # 백그라운드 작업용 (UI 멈춤 방지)
import pandas as pd # 데이터 정리용 (차트 분석)

# =====================================================================
# [1] KIS_API 클래스 : 증권사 서버와 직접 통신하는 '실무자'입니다.
# =====================================================================
class KIS_API:
    def __init__(self, app_key, app_secret, account_no, is_mock=True):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.is_mock = is_mock
        
        # 접속 서버 URL 설정 (모의투자/실전투자 구분)
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
        self.access_token = ""

    def get_access_token(self):
        """🔑 REST API 접근용 통행증(Token) 발급 - 유효시간 24시간"""
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        
        res = requests.post(url, headers=headers, data=json.dumps(body))
        if res.status_code == 200:
            self.access_token = res.json().get("access_token")
            return self.access_token
        return None

    def get_approval_key(self):
        """🔑 실시간 시세(Websocket) 접속용 승인키 발급"""
        url = f"{self.base_url}/oauth2/Approval"
        headers = {"content-type": "application/json; utf-8"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.app_secret}
        
        res = requests.post(url, headers=headers, data=json.dumps(body))
        return res.json().get("approval_key") if res.status_code == 200 else None

    def fetch_minute_data(self, stock_code):
        """📈 AI 분석용 1분봉 데이터 수집 (최근 30분치)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "tr_id": "FHKST03010200", # 국내주식 분봉 조회 TR
            "custtype": "P"
        }
        params = {
            "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_HOUR_1": "", "FID_PW_DATA_INCU_YN": "Y" # 현재 시간 기준 데이터 포함
        }
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200 and res.json()['rt_cd'] == '0':
            df = pd.DataFrame(res.json()['output2'])
            # 필요한 데이터만 골라내기
            df = df[['stck_bsop_date', 'stck_cntg_hour', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_prpr', 'cntg_vol']]
            df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
            df = df.apply(pd.to_numeric)
            return df.iloc[::-1].reset_index(drop=True) # 과거에서 현재 순으로 정렬
        return None

    def get_account_balance(self):
        """💰 계좌 내 주문 가능 현금(예수금) 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "tr_id": "VTTC8908R" if self.is_mock else "TTTC8908R", 
            "custtype": "P"
        }
        params = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": "", 
            "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
        }
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200:
            data = res.json()
            if data['rt_cd'] == '0':
                return int(data['output']['ord_psbl_cash'])
        return None

    def order_stock(self, stock_code, qty, is_buy=True):
        """🛒 시장가 주문 실행 (매수/매도)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = ("VTTC0802U" if is_buy else "VTTC0801U") if self.is_mock else ("TTTC0802U" if is_buy else "TTTC0801U")
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        body = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": stock_code,
            "ORD_DVSN": "01", "ORD_QTY": str(qty), "ORD_UNPR": "0" # 시장가는 가격 0 설정
        }
        res = requests.post(url, headers=headers, data=json.dumps(body))
        return res.status_code == 200 and res.json()['rt_cd'] == '0'


# =====================================================================
# [2] KIS_WebSocket 클래스 : 실시간 주가 감시 'CCTV'입니다.
# =====================================================================
class KIS_WebSocket:
    def __init__(self, approval_key, ui_main=None, is_mock=True):
        self.approval_key = approval_key
        self.ui = ui_main
        self.url = "ws://ops.koreainvestment.com:31000" if is_mock else "ws://ops.koreainvestment.com:21000"

    async def connect_and_subscribe(self, stock_code="005930"):
        """실시간 시세 서버 연결 및 구독"""
        try:
            async with websockets.connect(self.url, ping_interval=None) as websocket:
                self._log("📡 실시간 웹소켓 서버 연결 성공", "success")
                req_data = {
                    "header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                    "body": {"input": {"tr_id": "H0STCNT0", "tr_key": stock_code}}
                }
                await websocket.send(json.dumps(req_data))
                while True:
                    await websocket.recv() # 데이터 수신 로직 (장중에 데이터가 쏟아집니다)
        except Exception as e:
            self._log(f"⚠️ 웹소켓 중단: {e}", "error")

    def _log(self, msg, type):
        if self.ui: self.ui.add_log(msg, type)
        else: print(f"[{type}] {msg}")


# =====================================================================
# [3] KIS_Manager 클래스 : UI(FormMain)의 명령을 수행하는 '총괄 관리자'
# =====================================================================
class KIS_Manager:
    def __init__(self, ui_main=None):
        self.ui = ui_main 
        # ⚠️ 본인의 정보로 반드시 확인하세요!
        self.app_key = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
        self.app_secret = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
        self.account_no = "50172151"
        
        self.api = KIS_API(self.app_key, self.app_secret, self.account_no, is_mock=True)

    def start_api(self):
        """전체 시스템 초기화 (통행증 발급 + 웹소켓 가동)"""
        self._log("🎫 KIS API 접속 준비 시작...", "info")
        self.api.get_access_token()
        approval_key = self.api.get_approval_key()
        
        if approval_key:
            self._log("🚀 실시간 감시 스레드 출발!", "success")
            threading.Thread(target=self._run_websocket, args=(approval_key,), daemon=True).start()
        else:
            self._log("❌ 초기화 실패", "error")

    def _run_websocket(self, approval_key):
        ws = KIS_WebSocket(approval_key, ui_main=self.ui, is_mock=True)
        asyncio.run(ws.connect_and_subscribe("005930"))

    def _log(self, msg, type):
        """UI가 있으면 로그창에, 없으면 터미널에 출력"""
        if self.ui: self.ui.add_log(msg, type)
        else: print(f"[{type}] {msg}")

    # ---------------------------------------------------------
    # ✨ [핵심 수정] FormMain.py의 버튼들이 찾는 함수 이름들입니다.
    # ---------------------------------------------------------
    def check_my_balance(self):
        """UI의 '잔고 조회' 버튼이 호출하는 함수"""
        self._log("💰 예수금을 확인하고 있습니다...", "send")
        cash = self.api.get_account_balance()
        if cash is not None:
            self._log(f"✅ 현재 예수금: {cash:,}원", "success")
        else:
            self._log("❌ 잔고 조회 실패", "error")
        return cash

    def buy_market_price(self, stock_code, qty):
        """UI의 '삼성 1주 매수' 버튼이 호출하는 함수"""
        self._log(f"🛒 [{stock_code}] {qty}주 매수 주문 전송 중...", "send")
        success = self.api.order_stock(stock_code, qty, is_buy=True)
        if success:
            self._log(f"✅ 주문 접수 완료!", "success")
        else:
            self._log("❌ 주문 실패 (장외 시간 등)", "error")
        return success

    # --- 실전 매매 로봇(Auto_Traider.py)이 사용하는 함수들 ---
    def fetch_minute_data(self, code): return self.api.fetch_minute_data(code)
    def buy(self, code, qty): return self.api.order_stock(code, qty, is_buy=True)
    def sell(self, code, qty): return self.api.order_stock(code, qty, is_buy=False)
    def get_balance(self): return self.api.get_account_balance()