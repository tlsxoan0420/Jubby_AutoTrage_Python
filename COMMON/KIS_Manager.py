import requests
import json
import time
import pandas as pd
import numpy as np
import os
import threading
from datetime import datetime

# =====================================================================
# 🌐 시스템 전역 설정 및 DB 매니저
# =====================================================================
from COMMON.Flag import SystemConfig 
from COMMON.DB_Manager import JubbyDB_Manager 

# =====================================================================
# 👨‍💼 [1] KIS_API 클래스 (한국투자증권 서버와 직접 통신)
# =====================================================================
class KIS_API:
    def __init__(self, app_key, app_secret, account_no, is_mock=True, log_callback=None):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = str(account_no).strip()
        self.is_mock = is_mock 
        
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
        self.access_token = "" 
        self.log = log_callback 
        self.db = JubbyDB_Manager()
        
        self.last_error_msg = ""

        self.api_lock = threading.Lock()
        self.last_api_call = 0.0

    def _log_msg(self, msg, log_type="error"):
        if self.log: self.log(msg, log_type)
        else: print(f"[{log_type.upper()}] {msg}")
        try: self.db.insert_log(log_type.upper(), msg)
        except: pass

    # 🚀 [에러 해결] API 호출 제한 방지 함수 (AttributeError 방지용 위치 고정)
    def _wait_for_api_rate_limit(self):
        with self.api_lock:
            now = time.time()
            elapsed = now - self.last_api_call
            if elapsed < 0.20:
                time.sleep(0.20 - elapsed)
            self.last_api_call = time.time()

    def _safe_json_parse(self, response):
        try:
            if not response.text or response.text.strip() == "":
                return {"rt_cd": "9", "msg1": "서버 응답 없음"}
            return response.json()
        except:
            return {"rt_cd": "9", "msg1": "JSON 파싱 에러"}

    def get_access_token(self):
        token_path = os.path.join(SystemConfig.PROJECT_ROOT, "kis_token.txt")
        with self.api_lock:
            if os.path.exists(token_path):
                if time.time() - os.path.getmtime(token_path) < 72000:
                    with open(token_path, "r") as f:
                        cached_token = f.read().strip()
                    if cached_token:
                        self.access_token = cached_token 
                        return cached_token

        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            if res.status_code == 200:
                new_token = res.json().get("access_token")
                with open(token_path, "w") as f: f.write(new_token)
                self.access_token = new_token
                return new_token
        except: pass
        return ""

    # 🔑 [신규 복구] 실시간 체결 웹소켓 승인키 발급 (FormTicker 에러 해결)
    def get_approval_key(self):
        self._wait_for_api_rate_limit()
        url = f"{self.base_url}/oauth2/Approval"
        headers = {"content-type": "application/json; utf-8"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.app_secret}
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            if res.status_code == 200:
                approval_key = res.json().get("approval_key")
                self._log_msg("✅ 실시간 체결 웹소켓 승인키 발급 성공!", "success")
                return approval_key
        except Exception as e:
            self._log_msg(f"🚨 승인키 발급 오류: {e}")
        return None

    # ---------------------------------------------------------
    # [1] cancel_order 함수 수정 (주문 취소 규격 완벽 대응)
    # ---------------------------------------------------------
    def cancel_order(self, order_no):
        self._wait_for_api_rate_limit()
        if SystemConfig.MARKET_MODE != "DOMESTIC": return "FAIL"
        url = f"{self.base_url.rstrip('/')}/uapi/domestic-stock/v1/trading/order-rvsecnl"
        tr_id = "VTTC0803U" if self.is_mock else "TTTC0803U"
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:] if len(self.account_no) > 8 else "01"
        
        # 🚀 [버그 완벽 수정 2] 한투 API 규정상 주문 취소 시 ORD_DVSN은 반드시 "00"(지정가)이어야 합니다!
        # 기존 "01"(시장가)로 보내면 서버가 형식이 틀렸다며 응답을 주지 않거나 실패 처리합니다.
        payload = {
            "CANO": cano, 
            "ACNT_PRDT_CD": acnt_prdt_cd, 
            "ORGN_ODNO": str(order_no).zfill(10), 
            "ORD_DVSN": "00",  # 👈 핵심 수정 부분
            "RVSE_CNCL_DVSN_CD": "02", 
            "ORD_QTY": "0", 
            "ORD_UNPR": "0", 
            "QTY_ALL_ORD_YN": "Y"
        }
        
        headers = {"Content-Type": "application/json", "authorization": f"Bearer {self.access_token}", "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"}
        try:
            res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5.0)
            data = self._safe_json_parse(res)
            msg = data.get('msg1', '')
            if data.get('rt_cd') == '0':
                if "이미 체결" in msg or "수량이 없습니다" in msg or "완료" in msg:
                    return "ALREADY_FILLED" 
                return "DONE" 
            else:
                self.last_error_msg = msg # 🚀 실패 사유를 메인 UI에 넘겨주기 위해 보관합니다.
                if "이미 체결" in msg or "취소가능수량" in msg: return "ALREADY_FILLED"
                return "FAIL"
        except: return "ERROR"

    def order_stock(self, stock_code, qty, is_buy=True, limit_price=0, prcs_dv="01"):
        self._wait_for_api_rate_limit()
        ord_dvsn = "00" if limit_price > 0 else prcs_dv
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = ("VTTC0802U" if is_buy else "VTTC0801U") if self.is_mock else ("TTTC0802U" if is_buy else "TTTC0801U")
        payload = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": str(stock_code), "ORD_DVSN": ord_dvsn, "ORD_QTY": str(int(qty)), "ORD_UNPR": str(int(limit_price)), "CTAC_TLNO": "", "PRSR_DVSN": "", "ALGO_NO": ""}
        headers = {"Content-Type": "application/json", "authorization": f"Bearer {self.access_token}", "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"}
        try:
            res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5.0)
            data = self._safe_json_parse(res)
            
            if data.get('rt_cd') == '0':
                return data.get('output', {}).get('ODNO', '00000000')
            else:
                # 🚀 [수정] 서버가 준 진짜 사유(msg1)를 보관합니다.
                self.last_error_msg = data.get('msg1', '사유 알 수 없음') 
                return None
        except Exception as e:
            self.last_error_msg = str(e)
            return None

    # ---------------------------------------------------------
    # [2] fetch_minute_data 함수 수정 (시간순 정렬)
    # ---------------------------------------------------------
    def fetch_minute_data(self, stock_code):
        """ 최근 분봉 데이터 조회 및 컬럼명 변경 """
        self._wait_for_api_rate_limit()
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "content-type": "application/json", 
            "authorization": f"Bearer {self.access_token}", 
            "appkey": self.app_key, "appsecret": self.app_secret, 
            "tr_id": "FHKST03010200", "custtype": "P"
        }
        params = {
            "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", 
            "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": "153000", "FID_PW_DATA_INCU_YN": "Y"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            if data.get('rt_cd') == '0':
                df = pd.DataFrame(data.get('output2', []))
                if not df.empty:
                    df = df.rename(columns={
                        'stck_prpr': 'close',
                        'stck_oprc': 'open',
                        'stck_hgpr': 'high',
                        'stck_lwpr': 'low',
                        'cntg_vol': 'volume'
                    })
                    
                    # 🚀 [버그 완벽 수정 3] 한투 API는 최신 데이터가 인덱스 0에 옵니다.
                    # 이를 과거->최신 순으로 뒤집어야 iloc[-1]을 호출했을 때 찐 '현재가'를 가져옵니다!
                    df = df.iloc[::-1].reset_index(drop=True)
                    
                    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric, errors='coerce').fillna(0)
                    return df
            return None
        except: 
            return None

    def get_account_holdings(self):
        PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.access_token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": "VTTC8434R" if self.is_mock else "TTTC8434R", "custtype": "P"}
        acnt_prdt_cd = self.account_no[8:] if len(self.account_no) > 8 else "01"
        params = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": acnt_prdt_cd, "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
        for _ in range(3):
            self._wait_for_api_rate_limit()
            try:
                res = requests.get(f"{self.base_url}/{PATH}", headers=headers, params=params)
                data = res.json()
                if data.get("rt_cd") == "0": return data.get("output1", [])
            except: pass
        return None
    
    def get_account_holdings(self):
        PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.access_token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": "VTTC8434R" if self.is_mock else "TTTC8434R", "custtype": "P"}
        # 🚀 [핵심] PRCS_DVSN을 "00"으로 변경하여 '당일 매수한 종목'도 실시간 잔고에 즉각 포함되도록 수정!
        params = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
        for _ in range(3):
            self._wait_for_api_rate_limit()
            try:
                res = requests.get(f"{self.base_url}/{PATH}", headers=headers, params=params)
                data = res.json()
                if data.get("rt_cd") == "0": return data.get("output1", [])
            except: pass
        return None # 🚀 [] 대신 None을 반환하여 윗표 증발을 막음!
    
    def get_real_holdings(self): 
        # 🚀 [핵심 수정] self.api.get_account_holdings() 에서 '.api'를 지웠습니다!
        raw_list = self.get_account_holdings()
        
        if raw_list is None: return None # 통신 실패 시 방어막
        
        holdings_dict = {}
        if isinstance(raw_list, list):
            for item in raw_list:
                code = item.get('pdno', '')
                hldg_qty = int(item.get('hldg_qty', '0'))
                if code and hldg_qty > 0:
                    holdings_dict[code] = {
                        'price': float(item.get('pchs_avg_pric', '0')), 
                        'qty': hldg_qty
                    }
        return holdings_dict
    
    def get_unfilled_orders(self):
        self._wait_for_api_rate_limit() 
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.access_token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": "VTTC8001R" if self.is_mock else "TTTC8001R", "custtype": "P"}
        acnt_prdt_cd = self.account_no[8:] if len(self.account_no) > 8 else "01"
        params = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": acnt_prdt_cd, "INQR_STRT_DT": datetime.now().strftime("%Y%m%d"), "INQR_END_DT": datetime.now().strftime("%Y%m%d"), "SLL_BUY_DVSN_CD": "00", "INQR_DVSN": "00", "PDNO": "", "CCLD_DVSN": "02", "ORD_GNO_BRNO": "", "ODNO": "", "INQR_DVSN_3": "00", "INQR_DVSN_1": "", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            return data.get('output1', [])
        except: return []

    def get_d2_deposit(self):
        self._wait_for_api_rate_limit()
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.access_token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": "VTTC8908R" if self.is_mock else "TTTC8908R", "custtype": "P"}
        acnt_prdt_cd = self.account_no[8:] if len(self.account_no) > 8 else "01"
        params = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": acnt_prdt_cd, "PDNO": "005930", "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "Y", "OVRS_ICLD_YN": "N"}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            return int(float(data.get("output", {}).get("n2_dn_expect_cash_amt", "0")))
        except: return 0

    def get_execution_details(self):
        """ 거래소 서버에 물어봐서 주문번호별 '실제 총 체결 수량'을 딕셔너리로 가져옵니다. """
        self._wait_for_api_rate_limit()
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        tr_id = "VTTC8001R" if self.is_mock else "TTTC8001R"
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:] if len(self.account_no) > 8 else "01"
        
        # 🚀 [핵심 원인 수정] 한투 서버가 깐깐하게 요구하는 14개 필수 검색 조건을 모두 채웠습니다!
        # 이거 하나라도 빠지면 서버가 대답을 안 해서 탐정이 체결 확인을 못 합니다.
        params = {
            "CANO": cano, 
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "INQR_STRT_DT": datetime.now().strftime('%Y%m%d'),
            "INQR_END_DT": datetime.now().strftime('%Y%m%d'),
            "SLL_BUY_DVSN_CD": "00",  # 00: 전체 (매도/매수 구분)
            "INQR_DVSN": "00",        # 00: 역순
            "PDNO": "",               # 종목코드 (공백 시 전체)
            "CCLD_DVSN": "00",        # 00: 전체 (체결/미체결 모두 조회)
            "ORD_GNO_BRNO": "",       # 주문채번지점번호
            "ODNO": "",               # 주문번호 (공백 시 전체)
            "INQR_DVSN_3": "00",      # 00: 전체
            "INQR_DVSN_1": "",        # 조회구분1
            "CTX_AREA_FK100": "",     # 연속조회 조건
            "CTX_AREA_NK100": ""      # 연속조회 키
        }
        
        headers = {
            "Content-Type": "application/json", 
            "authorization": f"Bearer {self.access_token}", 
            "appKey": self.app_key, 
            "appSecret": self.app_secret, 
            "tr_id": tr_id, 
            "custtype": "P"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            exec_dict = {}
            if data.get('rt_cd') == '0':
                for item in data.get('output1', []):
                    odno = str(item.get('odno', '')).strip()
                    # tot_ccld_qty = 이 주문번호로 지금까지 실제로 사거나 판 찐 개수
                    qty = int(item.get('tot_ccld_qty', '0'))
                    if odno: exec_dict[odno] = qty
            return exec_dict
        except Exception as e: 
            print(f"체결 수량 확인 통신 에러: {e}")
            return None

# 👔 [사용자 편의 래퍼] KIS_Manager
class KIS_Manager:
    def __init__(self, ui_main=None):
        self.ui = ui_main 
        self.db = JubbyDB_Manager()
        self.APP_KEY = self.db.get_shared_setting("KIS_API", "APP_KEY", "")
        self.APP_SECRET = self.db.get_shared_setting("KIS_API", "APP_SECRET", "")
        self.IS_MOCK = self.db.get_shared_setting("KIS_API", "IS_MOCK", "TRUE").upper() == "TRUE"
        self.ACCOUNT_NO = self.db.get_shared_setting("KIS_API", "STOCK_ACCOUNT", "")
        self.api = KIS_API(self.APP_KEY, self.APP_SECRET, self.ACCOUNT_NO, is_mock=self.IS_MOCK, log_callback=self._log)     

    def start_api(self):
        self._log("🎫 KIS API 접속 시도 중...", "info")
        if self.api.get_access_token(): self._log("✅ 인증 성공!", "success")
        
    def _log(self, msg, log_type="error"):
        if self.ui: self.ui.add_log(msg, log_type)
        else: print(f"[{log_type.upper()}] {msg}")

    def buy_market_price(self, code, qty): return self.api.order_stock(code, qty, is_buy=True)
    def sell(self, code, qty): return self.api.order_stock(code, qty, is_buy=False)
    def get_balance(self): return self.api.get_account_balance()
    def cancel_order(self, order_no): return self.api.cancel_order(order_no)
    def get_real_holdings(self): return self.api.get_real_holdings()

    def fetch_minute_data(self, code): # 🚀 UI에서 부를 수 있게 연결통로 추가!
        return self.api.fetch_minute_data(code)
    def get_d2_deposit(self): 
        """ UI의 예수금 조회 요청을 API 클래스로 전달 """
        return self.api.get_d2_deposit()
    def get_unfilled_orders(self): 
        """ UI의 미체결 내역 요청을 API 클래스로 전달 """
        return self.api.get_unfilled_orders()
    def fetch_minute_data(self, code): 
        """ UI의 차트 데이터 요청을 API 클래스로 전달 """
        return self.api.fetch_minute_data(code)
    
    def fetch_execution_details(self):
        """ 주문번호별 실제 체결 수량을 딕셔너리로 반환합니다. """
        return self.api.get_execution_details()
    
    # ---------------------------------------------------------
    # 🔍 [핵심 추가] 거래소 실제 미체결 내역 조회 (유령 주문 판별용)
    # ---------------------------------------------------------
    def fetch_real_unfilled_orders_set(self):
        """ 
        현재 거래소(한투) 서버에 실제로 살아있는 미체결 주문번호들을 set 형태로 가져옵니다. 
        이 명단에 없는 주문은 우리 DB에서 지워버려야 할 '유령 주문'입니다.
        """
        # 기존에 만들어둔 get_unfilled_orders 함수를 활용합니다.
        raw_list = self.api.get_unfilled_orders() 
        
        real_unfilled_nos = set()
        if isinstance(raw_list, list):
            for item in raw_list:
                # 주문번호(odno)를 추출하여 공백 제거 후 저장
                odno = item.get('odno')
                if odno:
                    real_unfilled_nos.add(str(odno).strip())
        
        # 🚀 [주석] 만약 서버 에러로 리스트를 못 가져왔다면 None을 반환하여 
        # 탐정이 함부로 DB를 지우지 못하게 방어막을 칩니다.
        return real_unfilled_nos if raw_list is not None else None