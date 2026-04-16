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

    # 🚨 [버그 수정] 취소 로직 정밀화 (이미 체결된 경우 ALREADY_FILLED 반환)
    def cancel_order(self, order_no):
        self._wait_for_api_rate_limit()
        if SystemConfig.MARKET_MODE != "DOMESTIC": return "FAIL"
        url = f"{self.base_url.rstrip('/')}/uapi/domestic-stock/v1/trading/order-rvsecnl"
        tr_id = "VTTC0803U" if self.is_mock else "TTTC0803U"
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:] if len(self.account_no) > 8 else "01"
        payload = {"CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd, "ORGN_ODNO": str(order_no).zfill(10), "ORD_DVSN": "01", "RVSE_CNCL_DVSN_CD": "02", "ORD_QTY": "0", "ORD_UNPR": "0", "QTY_ALL_ORD_YN": "Y"}
        headers = {"Content-Type": "application/json", "authorization": f"Bearer {self.access_token}", "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"}
        try:
            res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5.0)
            data = self._safe_json_parse(res)
            msg = data.get('msg1', '')
            if data.get('rt_cd') == '0':
                if "이미 체결" in msg or "수량이 없습니다" in msg or "완료" in msg:
                    return "ALREADY_FILLED" # 취소 요청했으나 사실 사졌음
                return "DONE" # 진짜 취소 성공
            else:
                if "이미 체결" in msg: return "ALREADY_FILLED"
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

    def fetch_minute_data(self, stock_code):
        """ 최근 분봉 데이터 조회 및 컬럼명 변경 (KeyError 해결) """
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
                    # 🚀 [핵심 수정] 한투의 'stck_prpr' 컬럼을 'close'로 이름을 바꿉니다!
                    df = df.rename(columns={'stck_prpr': 'close'})
                    # 숫자 데이터로 변환
                    df['close'] = pd.to_numeric(df['close'])
                    return df
            return None
        except: 
            return None

    def get_account_balance(self):
        PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.access_token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": "VTTC8908R" if self.is_mock else "TTTC8908R", "custtype": "P"}
        params = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": "", "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "Y", "OVRS_ICLD_YN": "N"}
        for _ in range(3):
            self._wait_for_api_rate_limit()
            try:
                res = requests.get(f"{self.base_url}/{PATH}", headers=headers, params=params)
                data = res.json()
                if data.get("rt_cd") == "0": return int(data["output"]["ord_psbl_cash"])
            except: pass
        return 0

    def get_account_holdings(self):
        PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.access_token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": "VTTC8434R" if self.is_mock else "TTTC8434R", "custtype": "P"}
        params = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
        for _ in range(3):
            self._wait_for_api_rate_limit()
            try:
                res = requests.get(f"{self.base_url}/{PATH}", headers=headers, params=params)
                data = res.json()
                if data.get("rt_cd") == "0": return data.get("output1", [])
            except: pass
        return []
    
    def get_unfilled_orders(self):
        """ 🔍 [신규] 한투 서버에서 실제 '미체결 내역'을 직접 긁어옵니다. """
        self._wait_for_api_rate_limit() # 초당 호출 제한 방지
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        headers = {
            "content-type": "application/json", 
            "authorization": f"Bearer {self.access_token}", 
            "appkey": self.app_key, "appsecret": self.app_secret, 
            "tr_id": "VTTC8001R" if self.is_mock else "TTTC8001R", "custtype": "P"
        }
        # 오늘 날짜의 미체결(CCLD_DVSN: 02) 데이터 요청
        params = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01",
            "INQR_STRT_DT": datetime.now().strftime("%Y%m%d"), "INQR_END_DT": datetime.now().strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00", "INQR_DVSN": "00", "PDNO": "", "CCLD_DVSN": "02",
            "ORD_GNO_BRNO": "", "ODNO": "", "INQR_DVSN_3": "00", "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            # 서버에서 받은 미체결 리스트 반환 (없으면 빈 리스트)
            return data.get('output1', [])
        except: return []

    def get_d2_deposit(self):
        """ 💰 [신규] D+2일 뒤에 실제로 들어올 '예수금'을 조회합니다. """
        self._wait_for_api_rate_limit()
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {
            "content-type": "application/json", 
            "authorization": f"Bearer {self.access_token}", 
            "appkey": self.app_key, "appsecret": self.app_secret, 
            "tr_id": "VTTC8908R" if self.is_mock else "TTTC8908R", "custtype": "P"
        }
        params = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", 
            "PDNO": "005930", "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "Y", "OVRS_ICLD_YN": "N"
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            # n2_dn_expect_cash_amt가 D+2 예수금 항목입니다.
            return int(float(data.get("output", {}).get("n2_dn_expect_cash_amt", "0")))
        except: return 0


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
    def get_real_holdings(self): 
        raw_list = self.api.get_account_holdings()
        holdings_dict = {}
        if isinstance(raw_list, list):
            for item in raw_list:
                code = item.get('pdno', '')
                hldg_qty = int(item.get('hldg_qty', '0'))
                if code and hldg_qty > 0:
                    holdings_dict[code] = {
                        'price': float(item.get('pchs_avg_pric', '0')), # 🚀 'price' 추가!
                        'qty': hldg_qty
                    }
        return holdings_dict

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