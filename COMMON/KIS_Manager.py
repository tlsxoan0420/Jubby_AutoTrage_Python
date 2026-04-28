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

    def cancel_order(self, order_no):
        self._wait_for_api_rate_limit()
        if SystemConfig.MARKET_MODE != "DOMESTIC": return "FAIL"
        url = f"{self.base_url.rstrip('/')}/uapi/domestic-stock/v1/trading/order-rvsecnl"
        tr_id = "VTTC0803U" if self.is_mock else "TTTC0803U"
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:] if len(self.account_no) > 8 else "01"
        
        # 🚀 [버그 완벽 수정 2] 한투 API 규정상 주문 취소 시 ORD_DVSN은 반드시 "00"(지정가)이어야 합니다!
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
                self.last_error_msg = msg 
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
                self.last_error_msg = data.get('msg1', '사유 알 수 없음') 
                return None
        except Exception as e:
            self.last_error_msg = str(e)
            return None

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
                    
                    df = df.iloc[::-1].reset_index(drop=True)
                    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric, errors='coerce').fillna(0)
                    
                    # 🚀 [VWAP 완벽 보정 1단계] API가 제공하는 '당일 전체 누적' 데이터 확보
                    output1 = data.get('output1', {})
                    if isinstance(output1, dict):
                        df['total_vol'] = float(output1.get('acml_vol', 0))
                        df['total_tr_pbmn'] = float(output1.get('acml_tr_pbmn', 0))
                        
                    return df
            return None
        except: 
            return None

    # =========================================================================================
    # 🧹 [완벽 통합] 보유 종목(잔고) 조회 통합 함수 (트래픽 무적 재시도 + 에러 추적)
    # =========================================================================================
    def get_account_holdings(self):
        """ 💰 현재 계좌의 보유 종목(잔고) 목록을 조회합니다. """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        tr_id = "VTTC8434R" if self.is_mock else "TTTC8434R"
        
        headers = {
            "content-type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        
        cano = self.account_no[:8] if len(self.account_no) >= 8 else self.account_no
        acnt_prdt_cd = self.account_no[-2:] if len(self.account_no) >= 10 else "01"
        
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd, "AFHR_FLPR_YN": "N",
            "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        
        for attempt in range(3):
            self._wait_for_api_rate_limit()
            time.sleep(0.3) # 한투 서버가 놀라지 않게 0.3초 여유 대기
            
            try:
                # 🚀 [수정 1] 한투 서버가 느린 것을 감안해 10초까지 기다려줍니다.
                res = requests.get(url, headers=headers, params=params, timeout=10)
                data = res.json()
                
                if data.get('rt_cd') == '0':
                    return data.get('output1', []) 
                else:
                    msg = data.get('msg1', '')
                    if "초과" in msg:
                        if self.log: self.log(f"⏳ 종목잔고 트래픽 지연... 1초 후 재시도 ({attempt+1}/3)", "warning")
                        time.sleep(1.0) 
                        continue 
                    else:
                        if self.log: self.log(f"🚨 잔고조회 API 에러: {msg}", "error")
                        return None
            except Exception as e:
                # 🚀 [수정 2] 영어로 된 긴 에러 메시지 도배를 막고, 마지막 3번째 시도에만 빨간불을 켭니다.
                if attempt == 2:
                    if self.log: self.log("🚨 잔고조회 서버 무응답 (최종 실패)", "error")
                else:
                    if self.log: self.log(f"⏳ KIS 서버 지연... 잔고조회 재시도 ({attempt+1}/3)", "warning")
                time.sleep(1.0)
                
        return None

    # =========================================================================================
    # 💰 [완벽 통합] 예수금 조회 함수 (실전/모의투자 완벽 호환)
    # =========================================================================================
    def get_d2_deposit(self):
        """ 💰 현재 계좌의 주문 가능 예수금을 조회합니다. """
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        tr_id = "VTTC8908R" if self.is_mock else "TTTC8908R"
        
        headers = {
            "content-type": "application/json", "authorization": f"Bearer {self.access_token}", 
            "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        
        cano = self.account_no[:8] if len(self.account_no) >= 8 else self.account_no
        acnt_prdt_cd = self.account_no[-2:] if len(self.account_no) >= 10 else "01"
        
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd, "PDNO": "005930", 
            "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "Y", "OVRS_ICLD_YN": "N"
        }
        
        for attempt in range(3):
            self._wait_for_api_rate_limit()
            time.sleep(0.3) 
            
            try:
                # 🚀 [수정 1] 여기도 10초로 늘려줍니다.
                res = requests.get(url, headers=headers, params=params, timeout=10)
                data = res.json()
                
                if data.get("rt_cd") == "0":
                    d2_cash = int(float(data.get("output", {}).get("n2_dn_expect_cash_amt", "0")))
                    ord_cash = int(float(data.get("output", {}).get("ord_psbl_cash", "0")))
                    return max(d2_cash, ord_cash)
                else:
                    msg = data.get("msg1", "")
                    if "초과" in msg:
                        if self.log: self.log(f"⏳ 예수금조회 트래픽 지연... 1초 후 재시도 ({attempt+1}/3)", "warning")
                        time.sleep(1.0) 
                        continue
                    else:
                        if self.log: self.log(f"🚨 예수금 조회 거절: {msg}", "error")
                        return 0
            except Exception as e:
                # 🚀 [수정 2] 도배 방지 적용
                if attempt == 2:
                    if self.log: self.log("🚨 예수금조회 서버 무응답 (최종 실패)", "error")
                # 예수금은 워낙 자주 조회하므로 1, 2번째 실패는 아예 로그를 숨겨서 화면을 깨끗하게 유지합니다.
                time.sleep(1.0)
                
        return 0

    def get_real_holdings(self): 
        # 위에서 만든 통합 잔고 조회 함수를 사용합니다.
        raw_list = self.get_account_holdings()
        
        if raw_list is None: return None # 통신 실패 시 방어막
        
        holdings_dict = {}
        if isinstance(raw_list, list):
            for item in raw_list:
                code = item.get('pdno', '')
                hldg_qty = int(item.get('hldg_qty', '0'))
                if code and hldg_qty > 0:
                    holdings_dict[code] = {
                        'price': float(item.get('pchs_avg_pric', '0')), # 매입단가
                        'qty': hldg_qty,
                        # 🚀 [버그 완벽 수정 1] 한투 API가 알려주는 '현재가(prpr)'를 버리지 않고 챙겨옵니다!
                        'current_price': float(item.get('prpr', '0')) 
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

    def get_execution_details(self):
        """ 거래소 서버에 물어봐서 주문번호별 '실제 총 체결 수량'을 딕셔너리로 가져옵니다. """
        self._wait_for_api_rate_limit()
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        tr_id = "VTTC8001R" if self.is_mock else "TTTC8001R"
        cano = self.account_no[:8]
        acnt_prdt_cd = self.account_no[8:] if len(self.account_no) > 8 else "01"
        
        params = {
            "CANO": cano, "ACNT_PRDT_CD": acnt_prdt_cd,
            "INQR_STRT_DT": datetime.now().strftime('%Y%m%d'),
            "INQR_END_DT": datetime.now().strftime('%Y%m%d'),
            "SLL_BUY_DVSN_CD": "00", "INQR_DVSN": "00", "PDNO": "", 
            "CCLD_DVSN": "00", "ORD_GNO_BRNO": "", "ODNO": "", 
            "INQR_DVSN_3": "00", 
            "INQR_DVSN_1": "0",  # 🚀 [필수 수정] 빈칸("")을 "0"으로 변경해야만 서버가 대답합니다!
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}", 
            "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        
        # 🚀 [수정] 통신 렉 방어를 위해 10초 대기 및 3번 재시도 루프를 씌웁니다!
        for attempt in range(3):
            try:
                res = requests.get(url, headers=headers, params=params, timeout=10)
                data = res.json()
                exec_dict = {}
                if data.get('rt_cd') == '0':
                    for item in data.get('output1', []):
                        odno = str(item.get('odno', '')).strip()
                        qty = int(item.get('tot_ccld_qty', '0'))
                        if odno: exec_dict[odno] = qty
                    return exec_dict
                else:
                    msg = data.get('msg1', '')
                    if "초과" in msg:
                        time.sleep(1.0)
                        continue
                    return None
            except Exception as e: 
                # 🚀 1~2번째 실패는 조용히 넘어가고, 3번째 최종 실패 때만 에러를 띄웁니다.
                if attempt == 2:
                    print(f"🚨 체결 수량 통신 지연 (최종 실패): 서버 무응답")
                time.sleep(1.0)
                
        return None


# =====================================================================
# 👔 [사용자 편의 래퍼] KIS_Manager
# =====================================================================
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
    
    # 🚀 리스트 에러 방지를 위해 예수금을 반환하도록 강제 고정!
    def get_balance(self): return self.api.get_d2_deposit() 
    
    def cancel_order(self, order_no): return self.api.cancel_order(order_no)
    def get_real_holdings(self): return self.api.get_real_holdings()

    def get_d2_deposit(self): return self.api.get_d2_deposit()
    def get_unfilled_orders(self): return self.api.get_unfilled_orders()
    def fetch_minute_data(self, code): return self.api.fetch_minute_data(code)
    def fetch_execution_details(self): return self.api.get_execution_details()
    
    def fetch_real_unfilled_orders_set(self):
        raw_list = self.api.get_unfilled_orders() 
        real_unfilled_nos = set()
        if isinstance(raw_list, list):
            for item in raw_list:
                odno = item.get('odno')
                if odno:
                    real_unfilled_nos.add(str(odno).strip())
        return real_unfilled_nos if raw_list is not None else None