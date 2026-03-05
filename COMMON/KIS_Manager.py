# =====================================================================
# 🧰 [0] 마법 도구상자 (필요한 부품들을 가져옵니다)
# =====================================================================
import requests    # 인터넷 창을 열지 않고도 서버(한국투자증권)에 데이터를 요청하고 받아오는 통신병입니다.
import json        # 파이썬 데이터를 인터넷이 알아들을 수 있게 포장해 주는 번역기입니다.
import asyncio     # 실시간 통신을 할 때, 화면이 멈추지 않게 비동기(동시 작업)로 일하게 해주는 도구입니다.
import websockets  # 1초마다 시세가 바뀌는 걸 감시하는 '실시간 CCTV' 통신 도구입니다.
import threading   # 대장님(UI)이 일하는 동안, 뒤에서 몰래 일할 그림자 일꾼을 만드는 도구입니다.
import pandas as pd # 받아온 복잡한 숫자 덩어리들을 엑셀 표(DataFrame)처럼 예쁘게 정리해 줍니다.
import time        # 💡 [핵심!] "잠깐 멈춰!" 라고 명령해서 증권사 서버가 화내지 않게 조율하는 신호등입니다.

# =====================================================================
# 👨‍💼 [1] KIS_API 클래스 (증권사 서버와 직접 싸우는 최전선 실무자)
# 과외 쌤의 설명: 이 친구는 UI 화면이 어떻게 생겼는지 모릅니다. 
# 그저 "얼마 있어?", "삼성전자 사와!" 라는 명령을 받으면, 
# 진짜 증권사 서버로 달려가서 돈을 확인하고 주식을 사오는 '행동 대장'입니다.
# =====================================================================
class KIS_API:
    def __init__(self, app_key, app_secret, account_no, is_mock=True, log_callback=None):
        # 실무자가 증권사 건물에 들어갈 때 보여줄 '출입증(ID/비밀번호/계좌번호)'입니다.
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.is_mock = is_mock # True면 모의투자 연습장, False면 진짜 내 돈이 걸린 실전!
        
        # 모의투자냐 실전이냐에 따라 찾아갈 건물(서버 주소)이 다릅니다.
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
        self.access_token = "" # 24시간짜리 임시 출입증을 보관할 주머니입니다.
        
        # 🎤 [개조 포인트] 실무자도 억울한 일이 생기면 대장님(화면)에게 바로 일러바칠 수 있게 무전기를 받았습니다!
        self.log = log_callback 

    def _log_msg(self, msg, log_type="error"):
        """실무자가 증권사 서버한테 까였을 때, 대장님 화면에 빨간 글씨로 띄워주는 기능입니다."""
        if self.log:
            self.log(msg, log_type) # 무전기가 있으면 화면에 띄우고!
        else:
            print(msg) # 없으면 그냥 까만 콘솔창에 조용히 씁니다.

    def get_access_token(self):
        """🔑 REST API용 24시간 임시 통행증(Token) 발급받기"""
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        
        try:
            # 증권사 경비아저씨한테 내 신분증(body)을 주면서 "오늘 하루 출입증 주세요!" 요청(post)합니다.
            res = requests.post(url, headers=headers, data=json.dumps(body))
            if res.status_code == 200: # 200은 "성공(OK)!"을 의미합니다.
                self.access_token = res.json().get("access_token")
                return self.access_token
        except Exception as e:
            self._log_msg(f"⚠️ [통행증 에러] 서버 연결 실패: {e}")
        return None

    def get_approval_key(self):
        """🔑 실시간 시세 감시용(Websocket) 또 다른 승인키 발급받기"""
        url = f"{self.base_url}/oauth2/Approval"
        headers = {"content-type": "application/json; utf-8"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.app_secret}
        res = requests.post(url, headers=headers, data=json.dumps(body))
        return res.json().get("approval_key") if res.status_code == 200 else None

    def fetch_minute_data(self, stock_code):
        """📈 AI 두뇌에게 먹일 '최근 1분봉 차트 데이터' 가져오기"""
        # 🚨 [매우 중요] 주삐가 0.01초 만에 종목 20개를 다다다 물어보면 서버가 디도스(해킹)로 오해하고 차단합니다!
        # 그래서 질문하기 전에 무조건 0.2초씩 숨을 고릅니다.
        time.sleep(0.2) 
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret,
            "tr_id": "FHKST03010200", "custtype": "P" # P는 개인투자자(Person)라는 뜻입니다.
        }
        params = {
            "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_HOUR_1": "", "FID_PW_DATA_INCU_YN": "Y" # Y: 방금 막 그려진 캔들도 포함해서 줘!
        }
        
        try:
            res = requests.get(url, headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0': # rt_cd가 '0'이면 한국투자증권이 정상 처리했다는 도장입니다.
                    df = pd.DataFrame(data['output2'])
                    # AI가 밥으로 먹을 핵심 반찬들(시,고,저,종,거래량)만 딱 골라냅니다.
                    df = df[['stck_bsop_date', 'stck_cntg_hour', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_prpr', 'cntg_vol']]
                    df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
                    df = df.apply(pd.to_numeric)
                    # 서버는 최신 걸 맨 위에 주니까, 우리가 차트 보기 편하게 옛날->최신 순서로 뒤집어줍니다.
                    return df.iloc[::-1].reset_index(drop=True) 
                else:
                    # 🚫 만약 서버가 화내면, 왜 화냈는지(msg1) 로그창에 띄워줍니다!
                    self._log_msg(f"⚠️ [차트 거절] 한투 응답: {data.get('msg1')}") 
            else:
                self._log_msg(f"⚠️ [통신 장애] 차트 서버 에러코드: {res.status_code}")
        except Exception as e:
            self._log_msg(f"⚠️ [시스템 에러] 차트 조회 중 오류: {e}")
            
        return None

    def get_account_balance(self):
        """💰 (문제 해결의 핵심!) 계좌 내 주문 가능 현금(예수금) 가져오기"""
        # 🚨 여기서 0.2초를 쉬어야 앞서 차트를 물어본 것 때문에 화난 서버가 진정합니다.
        time.sleep(0.2) 
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret,
            "tr_id": "VTTC8908R" if self.is_mock else "TTTC8908R", # 모의투자는 V, 실전은 T
            "custtype": "P"
        }
        params = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": "", 
            "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0':
                    # 천만 원! 진짜 예수금 숫자만 쏙 빼서 돌려줍니다.
                    return int(data['output']['ord_psbl_cash']) 
                else:
                    # 🚨 드디어! 일꾼이 왜 돈을 못 가져왔는지 그 진짜 이유("초당 거래건수 초과" 등)가 로그에 찍힙니다!
                    self._log_msg(f"⚠️ [잔고조회 거절] 한투 응답: {data.get('msg1')}") 
            else:
                self._log_msg(f"⚠️ [통신 장애] 한투 서버 상태코드: {res.status_code}")
        except Exception as e:
            self._log_msg(f"⚠️ [파이썬 에러] 잔고조회 중 문제발생: {e}")
            
        return None # 돈을 못 가져오면 None을 뱉고, FormMain에서 이 None을 0원으로 둔갑시켰던 겁니다!

    def order_stock(self, stock_code, qty, is_buy=True):
        """🛒 시장가 매수/매도 주문 넣기"""
        time.sleep(0.2) # 주문도 너무 다다다닥 넣으면 막히니까 숨 고르기!
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        # 암호 코드(TR_ID)가 아주 복잡하죠? 모의/실전, 매수/매도마다 쓰는 암호가 다릅니다.
        tr_id = ("VTTC0802U" if is_buy else "VTTC0801U") if self.is_mock else ("TTTC0802U" if is_buy else "TTTC0801U")
        
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        body = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": stock_code,
            "ORD_DVSN": "01", # 01은 '시장가'를 뜻합니다. 시장가로 던져야 즉시 체결됩니다!
            "ORD_QTY": str(qty), 
            "ORD_UNPR": "0"   # 시장가 주문은 가격을 0원으로 적어서 보내야 한투가 알아먹습니다.
        }
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0': return True # 주문 접수 대성공!
                else: self._log_msg(f"⚠️ [주문 거절] 한투 응답: {data.get('msg1')}")
        except Exception as e:
            self._log_msg(f"⚠️ [주문 에러] 시스템 문제발생: {e}")
        return False

    def get_account_holdings(self):
        """💼 내 지갑에 들어있는 주식 종목과 평단가 가져오기 (프로그램 켤 때 이어달리기 용도)"""
        time.sleep(0.2) # 안전제일!
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret,
            "tr_id": "VTTC8434R" if self.is_mock else "TTTC8434R", "custtype": "P"
        }
        params = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "AFHR_FLPR_YN": "N",
            "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        holdings = {}
        try:
            res = requests.get(url, headers=headers, params=params)
            if res.status_code == 200:
                data = res.json()
                if data['rt_cd'] == '0':
                    for item in data['output1']: # 내 종목들이 리스트로 우르르 옵니다.
                        qty = int(item['hldg_qty']) 
                        if qty > 0: # 다 팔아서 0주인 쓰레기 데이터는 버립니다.
                            code = item['pdno'] 
                            price = float(item['pchs_avg_pric']) 
                            # 예쁘게 딕셔너리에 담아줍니다. 예: holdings["005930"] = {'price': 70000, 'qty': 10}
                            holdings[code] = {'price': price, 'qty': qty}
                else:
                    self._log_msg(f"⚠️ [보유종목 거절] 한투 응답: {data.get('msg1')}")
        except Exception as e:
            self._log_msg(f"⚠️ [보유종목 에러] 시스템 오류: {e}")
        return holdings


# =====================================================================
# 🎥 [2] KIS_WebSocket 클래스 (실시간 CCTV)
# =====================================================================
class KIS_WebSocket:
    def __init__(self, approval_key, ui_main=None, is_mock=True):
        self.approval_key = approval_key
        self.ui = ui_main
        self.url = "ws://ops.koreainvestment.com:31000" if is_mock else "ws://ops.koreainvestment.com:21000"

    async def connect_and_subscribe(self, stock_code="005930"):
        try:
            async with websockets.connect(self.url, ping_interval=None) as websocket:
                self._log("📡 실시간 웹소켓 서버 연결 성공", "success")
                req_data = {
                    "header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                    "body": {"input": {"tr_id": "H0STCNT0", "tr_key": stock_code}}
                }
                await websocket.send(json.dumps(req_data))
                while True: await websocket.recv() 
        except Exception as e:
            self._log(f"⚠️ 웹소켓 중단: {e}", "error")

    def _log(self, msg, type):
        if self.ui: self.ui.add_log(msg, type)
        else: print(f"[{type}] {msg}")


# =====================================================================
# 👔 [3] KIS_Manager 클래스 (총괄 매니저)
# 과외 쌤의 설명: FormMain.py 화면단은 복잡한 API 구조를 몰라도 됩니다.
# 그냥 이 매니저한테 "야, 사!", "돈 얼마 남았어?" 라고 쉽게 물어보면,
# 매니저가 실무자(KIS_API)한테 명령을 번역해서 토스해주고, 결과를 화면에 찍어줍니다.
# =====================================================================
class KIS_Manager:
    def __init__(self, ui_main=None):
        self.ui = ui_main # FormMain 대장님과 무전기를 연결합니다.
        
        self.app_key = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
        self.app_secret = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
        self.account_no = "50172151"
        
        # 💡 [중요] 실무자(API)를 고용할 때, "에러 나면 나한테 귓속말(_log) 해줘!" 라고 무전기(log_callback)를 쥐여줬습니다.
        self.api = KIS_API(self.app_key, self.app_secret, self.account_no, is_mock=True, log_callback=self._log)

    def start_api(self):
        """프로그램 켤 때 제일 먼저 실행되는 아침 조회 시간입니다."""
        self._log("🎫 KIS API 접속 준비 시작...", "info")
        self.api.get_access_token() 
        approval_key = self.api.get_approval_key()
        
        if approval_key:
            self._log("🚀 실시간 감시 스레드 출발!", "success")
            # CCTV 담당자(웹소켓)를 백그라운드 스레드로 켜둡니다.
            threading.Thread(target=self._run_websocket, args=(approval_key,), daemon=True).start()
        else:
            self._log("❌ 초기화 실패", "error")

    def _run_websocket(self, approval_key):
        ws = KIS_WebSocket(approval_key, ui_main=self.ui, is_mock=True)
        asyncio.run(ws.connect_and_subscribe("005930"))

    def _log(self, msg, type="error"):
        """화면 로그창에 예쁜 색깔로 글씨를 띄워주는 보조 마이크입니다."""
        if self.ui: self.ui.add_log(msg, type)
        else: print(f"[{type}] {msg}")

    # --- UI 버튼(수동 조작)이 부르는 편의점 함수들 ---
    def check_my_balance(self):
        self._log("💰 예수금을 확인하고 있습니다...", "send")
        cash = self.api.get_account_balance()
        if cash is not None:
            self._log(f"✅ 현재 예수금: {cash:,}원", "success")
        else:
            self._log("❌ 잔고 조회 실패", "error")
        return cash

    def buy_market_price(self, stock_code, qty):
        self._log(f"🛒 [{stock_code}] {qty}주 매수 주문 전송 중...", "send")
        success = self.api.order_stock(stock_code, qty, is_buy=True)
        if success:
            self._log(f"✅ 주문 접수 완료!", "success")
        else:
            self._log("❌ 주문 실패 (돈이 부족하거나, 장외 시간일 수 있습니다)", "error")
        return success
    
    # --- 자동매매 주삐 일꾼(AutoTradeWorker)이 다이렉트로 부르는 스피드 함수들 ---
    def fetch_minute_data(self, code): 
        return self.api.fetch_minute_data(code)

    def buy(self, code, qty): 
        return self.api.order_stock(code, qty, is_buy=True)

    def sell(self, code, qty): 
        return self.api.order_stock(code, qty, is_buy=False)

    def get_balance(self): 
        return self.api.get_account_balance()
    
    def get_real_holdings(self): 
        return self.api.get_account_holdings()