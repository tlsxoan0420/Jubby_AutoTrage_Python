import requests    # REST API 통신용 (토큰, 주문, 잔고 등을 요청할 때 쓰는 인터넷 브라우저 같은 역할)
import json        # 데이터 변환용 (파이썬 데이터를 인터넷이 이해할 수 있게 포장해줌)
import asyncio     # 비동기 처리용 (웹소켓 통신을 위해 사용)
import websockets  # 웹소켓 통신용 (실시간으로 변하는 시세를 1초 단위로 감시할 때 사용)
import threading   # 백그라운드 작업용 (UI가 멈추지 않게 뒤에서 몰래 일하는 일꾼)
import pandas as pd # 데이터 정리용 (가져온 차트 데이터를 예쁜 엑셀 표처럼 정리해줌)

# =====================================================================
# [1] KIS_API 클래스 : 증권사 서버와 '직접' 통신하는 최전선 실무자입니다.
# (얘는 무조건 서버에 요청만 하고 데이터를 받아오는 역할만 합니다.)
# =====================================================================
class KIS_API:
    def __init__(self, app_key, app_secret, account_no, is_mock=True):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.is_mock = is_mock
        
        # 접속할 서버 주소를 정합니다. 모의투자면 테스트 서버, 진짜면 실거래 서버로 갑니다.
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
        self.access_token = ""

    def get_access_token(self):
        """🔑 REST API 접근용 통행증(Token) 발급 - 한 번 발급받으면 24시간 동안 쓸 수 있습니다."""
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        
        res = requests.post(url, headers=headers, data=json.dumps(body))
        if res.status_code == 200:
            self.access_token = res.json().get("access_token")
            return self.access_token
        return None

    def get_approval_key(self):
        """🔑 실시간 시세(Websocket) 접속용 승인키 발급 - 실시간 감시를 위한 또 다른 열쇠입니다."""
        url = f"{self.base_url}/oauth2/Approval"
        headers = {"content-type": "application/json; utf-8"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.app_secret}
        
        res = requests.post(url, headers=headers, data=json.dumps(body))
        return res.json().get("approval_key") if res.status_code == 200 else None

    def fetch_minute_data(self, stock_code):
        """📈 AI 분석용 1분봉 데이터 수집 (AI에게 먹일 최근 30분치 캔들 차트를 가져옵니다)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "tr_id": "FHKST03010200", # "나 국내주식 1분봉 알고 싶어!" 라는 암호(TR 코드)입니다.
            "custtype": "P"
        }
        params = {
            "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_HOUR_1": "", "FID_PW_DATA_INCU_YN": "Y" # Y로 해야 방금 막 그려진 캔들까지 포함해서 줍니다.
        }
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200 and res.json()['rt_cd'] == '0':
            df = pd.DataFrame(res.json()['output2'])
            # 쓸데없는 데이터는 버리고, AI가 필요한 것들(시가, 고가, 저가, 종가, 거래량)만 딱 골라냅니다.
            df = df[['stck_bsop_date', 'stck_cntg_hour', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_prpr', 'cntg_vol']]
            df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
            df = df.apply(pd.to_numeric)
            # 한국투자증권은 최신 캔들을 맨 위에 주니까, 우리가 보기 편하게 옛날->최신 순서로 뒤집어줍니다.
            return df.iloc[::-1].reset_index(drop=True) 
        return None

    def get_account_balance(self):
        """💰 계좌 내 주문 가능 현금(예수금) 조회 - 주삐가 돈을 얼마나 쓸 수 있는지 확인합니다."""
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
                return int(data['output']['ord_psbl_cash']) # 진짜 예수금 숫자만 쏙 뽑아서 줍니다.
        return None

    def order_stock(self, stock_code, qty, is_buy=True):
        """🛒 시장가 주문 실행 (is_buy가 True면 매수, False면 매도합니다)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        # 매수할 때와 매도할 때 쓰는 암호(TR 코드)가 다릅니다. 모의/실전도 다릅니다!
        tr_id = ("VTTC0802U" if is_buy else "VTTC0801U") if self.is_mock else ("TTTC0802U" if is_buy else "TTTC0801U")
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        body = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": stock_code,
            "ORD_DVSN": "01", "ORD_QTY": str(qty), "ORD_UNPR": "0" # 시장가는 가격을 0으로 쏴야 증권사가 알아먹습니다.
        }
        res = requests.post(url, headers=headers, data=json.dumps(body))
        return res.status_code == 200 and res.json()['rt_cd'] == '0'

    # ✨ [핵심 수정 완료] 들여쓰기를 맞춰서 확실하게 KIS_API 클래스 소속으로 만들었습니다!
    def get_account_holdings(self):
        """💼 실제 증권사 계좌의 보유 주식 목록과 평단가를 조회합니다."""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "tr_id": "VTTC8434R" if self.is_mock else "TTTC8434R", # 잔고조회 TR 코드
            "custtype": "P"
        }
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": "01",
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        res = requests.get(url, headers=headers, params=params)
        
        holdings = {}
        if res.status_code == 200 and res.json()['rt_cd'] == '0':
            data = res.json()['output1'] # 내 계좌에 있는 종목들이 배열 형태로 들어옵니다.
            for item in data:
                qty = int(item['hldg_qty']) # 보유 수량
                if qty > 0: # 다 팔아서 0주인데 찌꺼기로 남은 데이터는 무시합니다.
                    code = item['pdno'] # 종목코드
                    price = float(item['pchs_avg_pric']) # 내가 샀던 평단가
                    holdings[code] = {'price': price, 'qty': qty} # 예쁘게 딕셔너리로 만듭니다.
        return holdings


# =====================================================================
# [2] KIS_WebSocket 클래스 : 실시간 주가 감시 'CCTV'입니다. (현재는 보류 중)
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
# [3] KIS_Manager 클래스 : UI(FormMain)의 명령을 실무자(KIS_API)에게 전달하는 '총괄 매니저'
# UI는 KIS_API를 직접 건드리지 않고, 항상 이 매니저를 통해서만 명령을 내립니다!
# =====================================================================
class KIS_Manager:
    def __init__(self, ui_main=None):
        self.ui = ui_main 
        # ⚠️ 본인의 진짜 앱키와 시크릿키, 계좌번호로 확인 필수!
        self.app_key = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
        self.app_secret = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
        self.account_no = "50172151"
        
        # 매니저가 고용될 때 실무자(KIS_API)도 같이 하나 세팅해둡니다.
        self.api = KIS_API(self.app_key, self.app_secret, self.account_no, is_mock=True)

    def start_api(self):
        """전체 시스템 초기화 (통행증 발급 + 웹소켓 가동)"""
        self._log("🎫 KIS API 접속 준비 시작...", "info")
        self.api.get_access_token() # 매니저가 실무자한테 "가서 통행증 좀 받아와!" 시킵니다.
        approval_key = self.api.get_approval_key()
        
        if approval_key:
            self._log("🚀 실시간 감시 스레드 출발!", "success")
            # 화면이 멈추지 않게 뒤에서 몰래 CCTV(웹소켓)를 켭니다.
            threading.Thread(target=self._run_websocket, args=(approval_key,), daemon=True).start()
        else:
            self._log("❌ 초기화 실패", "error")

    def _run_websocket(self, approval_key):
        ws = KIS_WebSocket(approval_key, ui_main=self.ui, is_mock=True)
        asyncio.run(ws.connect_and_subscribe("005930"))

    def _log(self, msg, type):
        """UI(화면)가 연결되어 있으면 화면 로그창에 띄우고, 없으면 까만 콘솔창에 찍어줍니다."""
        if self.ui: self.ui.add_log(msg, type)
        else: print(f"[{type}] {msg}")

    # ---------------------------------------------------------
    # 🎯 UI 버튼이나 자동매매 로봇이 호출하는 최종 연결고리 함수들!
    # UI는 매니저에게 시키고 -> 매니저는 실무자(self.api)에게 시킵니다.
    # ---------------------------------------------------------
    def check_my_balance(self):
        """UI의 '잔고 조회' 버튼이 누르면 실행됩니다."""
        self._log("💰 예수금을 확인하고 있습니다...", "send")
        cash = self.api.get_account_balance()
        if cash is not None:
            self._log(f"✅ 현재 예수금: {cash:,}원", "success")
        else:
            self._log("❌ 잔고 조회 실패", "error")
        return cash

    def buy_market_price(self, stock_code, qty):
        """UI의 '매수' 버튼이나, 자동매매 루프가 매수할 때 부르는 함수입니다."""
        self._log(f"🛒 [{stock_code}] {qty}주 매수 주문 전송 중...", "send")
        success = self.api.order_stock(stock_code, qty, is_buy=True)
        if success:
            self._log(f"✅ 주문 접수 완료!", "success")
        else:
            self._log("❌ 주문 실패 (돈이 부족하거나, 장외 시간일 수 있습니다)", "error")
        return success
    
    # --- FormMain.py 의 일꾼(AutoTradeWorker)이 사용하는 연결고리들 ---
    def fetch_minute_data(self, code): 
        # "1분봉 좀 가져와줘!" -> API 실무자에게 전달
        return self.api.fetch_minute_data(code)

    def buy(self, code, qty): 
        # "이거 매수해 줘!" -> API 실무자에게 전달
        return self.api.order_stock(code, qty, is_buy=True)

    def sell(self, code, qty): 
        # "이거 매도해 줘!" -> API 실무자에게 전달
        return self.api.order_stock(code, qty, is_buy=False)

    def get_balance(self): 
        return self.api.get_account_balance()
    
    # ✨ 에러가 났던 주범! 매니저 안에도 이 연결고리를 뚫어놔야 FormMain이 부를 수 있습니다.
    def get_real_holdings(self): 
        # FormMain이 "내 잔고 줘!" 하면 매니저가 API 실무자의 get_account_holdings를 불러서 넘겨줍니다.
        return self.api.get_account_holdings()