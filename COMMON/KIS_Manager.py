import requests
import json
import time
import pandas as pd
import numpy as np
import os
import threading

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
        
        # 모의투자(VTS)와 실전 서버 주소 구분
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
        self.access_token = "" 
        self.log = log_callback 
        self.last_error_msg = ""  # 에러 발생 시 UI에 뿌려줄 메시지 저장소
        self.db = JubbyDB_Manager()
        
        self.api_lock = threading.Lock()
        self.last_api_call = 0.0

    def _log_msg(self, msg, log_type="error"):
        """ 로그 출력 및 C# 공유용 DB 저장 """
        if self.log: self.log(msg, log_type)
        else: print(f"[{log_type.upper()}] {msg}")
        try: self.db.insert_log(log_type.upper(), msg)
        except: pass

    def _safe_json_parse(self, response):
        try:
            if not response.text or response.text.strip() == "":
                return {"rt_cd": "9", "msg1": "서버 응답 없음"}
            return response.json()
        except:
            return {"rt_cd": "9", "msg1": "JSON 파싱 에러"}

    def get_access_token(self):
        """ KIS API 접속 토큰 발급 (파일 캐싱 적용으로 1분 제한 방어) """
        token_path = os.path.join(SystemConfig.PROJECT_ROOT, "kis_token.txt")
        
        # 1단계: 기존 토큰 재사용 (20시간 이내)
        if os.path.exists(token_path):
            if time.time() - os.path.getmtime(token_path) < 72000:
                with open(token_path, "r") as f:
                    cached_token = f.read().strip()
                if cached_token:
                    if self.log: self.log("♻️ 기존에 발급받은 KIS 토큰을 재사용합니다.", "info")
                    self.access_token = cached_token 
                    return cached_token

        # 2단계: 신규 토큰 발급
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            if res.status_code == 200:
                new_token = res.json().get("access_token")
                with open(token_path, "w") as f: f.write(new_token)
                if self.log: self.log("🎫 새 KIS 접속 토큰 발급 및 저장 완료!", "success")
                self.access_token = new_token
                return new_token
            else:
                if self.log: self.log(f"🚨 토큰 발급 실패: {res.text}", "error")
                if os.path.exists(token_path):
                    with open(token_path, "r") as f:
                        fb_token = f.read().strip()
                        self.access_token = fb_token
                        return fb_token
        except Exception as e:
            if self.log: self.log(f"🚨 토큰 발급 중 통신 에러: {e}", "error")
        return ""

    def get_approval_key(self):
        """ 실시간 체결 웹소켓 접속을 위한 승인키 발급 """
        url = f"{self.base_url}/oauth2/Approval"
        headers = {"content-type": "application/json; utf-8"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.app_secret}
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            if res.status_code == 200:
                approval_key = res.json().get("approval_key")
                self._log_msg("✅ 실시간 체결 웹소켓 승인키 발급 성공!", "success")
                return approval_key
        except Exception as e: self._log_msg(f"🚨 승인키 발급 오류: {e}")
        return None

    def get_account_balance(self):
        """ 예수금(주문가능금액) 조회 (안전망 적용) """
        PATH = "uapi/domestic-stock/v1/trading/inquire-psbl-order"
        URL = f"{self.base_url}/{PATH}"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "VTTC8908R" if self.is_mock else "TTTC8908R",
            "custtype": "P",
        }
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:],
            "PDNO": "",
            "ORD_UNPR": "",
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "Y",
            "OVRS_ICLD_YN": "N"
        }
        
        # 💡 [핵심 수정] 프로그램 시작 직후 씹힘 현상을 막기 위해 최대 3번까지 재시도합니다!
        for attempt in range(3):
            self._wait_for_api_rate_limit()
            try:
                res = requests.get(URL, headers=headers, params=params)
                data = res.json()
                
                # 성공 시 즉시 돈 반환
                if res.status_code == 200 and data["rt_cd"] == "0":
                    return int(data["output"]["ord_psbl_cash"])
                else:
                    # 실패 시 0.3초 대기 후 다시 물어봄
                    self.last_error_msg = data.get("msg1", "")
                    time.sleep(0.3)
            except Exception as e:
                time.sleep(0.3)
                
        # 3번 다 실패했을 때만 0원 반환
        return 0

    def get_account_holdings(self):
        """ 보유 종목 리스트 조회 (안전망 적용) """
        PATH = "uapi/domestic-stock/v1/trading/inquire-balance"
        URL = f"{self.base_url}/{PATH}"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "VTTC8434R" if self.is_mock else "TTTC8434R",
            "custtype": "P",
        }
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:],
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
        
        # 💡 [핵심 수정] 잔고 조회 실패 시 빈 깡통을 반환하지 않도록 3번 재시도!
        for attempt in range(3):
            self._wait_for_api_rate_limit()
            try:
                res = requests.get(URL, headers=headers, params=params)
                data = res.json()
                
                if res.status_code == 200 and data["rt_cd"] == "0":
                    return data["output1"]
                else:
                    self.last_error_msg = data.get("msg1", "")
                    time.sleep(0.3)
            except Exception as e:
                time.sleep(0.3)
        
        return []
    
    def get_unfilled_orders(self):
        """ 🔍 서버에서 '진짜' 예약매수/예약매도(미체결) 내역을 가져옵니다. """
        unfilled_list = []
        if SystemConfig.MARKET_MODE != "DOMESTIC": 
            return unfilled_list
            
        # 한투 미체결 조회 API 주소
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecnl"
        tr_id = "VTTC8036R" if self.is_mock else "TTTC8036R"
        params = {
            "CANO": self.account_no[:8], 
            "ACNT_PRDT_CD": "01",
            "CTX_AREA_FK100": "", 
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "0", 
            "INQR_DVSN_2": "0"
        }
        headers = {
            "Content-Type": "application/json", 
            "authorization": f"Bearer {self.access_token}", 
            "appKey": self.app_key, 
            "appSecret": self.app_secret, 
            "tr_id": tr_id, 
            "custtype": "P"
        }
        
        # 🟢 [수정 후] 이렇게 2줄을 바꾸세요!
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5.0)
            data = self._safe_json_parse(res)
            if data.get('rt_cd') == '0':
                for item in data.get('output', []):
                    remn_qty = int(item.get('remn_qty', 0))
                    if remn_qty > 0: # 잔여(미체결) 수량이 남아있는 것만 수집!
                        unfilled_list.append({
                            '주문번호': item.get('odno', ''),
                            '종목코드': item.get('pdno', ''),
                            '종목명': item.get('prdt_name', ''),
                            '주문종류': item.get('sll_buy_dvsn_cd_name', '예약'), # KIS가 '매도' 또는 '매수'로 줍니다.
                            '주문수량': int(item.get('ord_qty', 0)),
                            '미체결수량': remn_qty,
                            '주문가격': float(item.get('ord_unpr', 0)),
                            '주문시간': item.get('ord_tmd', '') # 시간 (HHMMSS 형식)
                        })
        except Exception as e: 
            print(f"미체결 조회 에러: {e}")
            
        return unfilled_list

    # =====================================================================
    # 🛒 [핵심 수정] 주식 주문 (주문번호 ODNO 반환 및 전략 적용)
    # =====================================================================
    def order_stock(self, stock_code, qty, is_buy=True, limit_price=0, prcs_dv="01"):
        """ 
        실제 주문 전송 함수 
        - limit_price > 0 이면 지정가(00)
        - limit_price == 0 이면 prcs_dv(기본 시장가 01) 적용
        """
        self._wait_for_api_rate_limit() # 💡 추가!
        # 가격이 있으면 지정가(00), 없으면 시장가 혹은 최우선지정가(prcs_dv)
        ord_dvsn = "00" if limit_price > 0 else prcs_dv
        price_str = str(int(limit_price)) if limit_price > 0 else "0"
        
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
            tr_id = ("VTTC0802U" if is_buy else "VTTC0801U") if self.is_mock else ("TTTC0802U" if is_buy else "TTTC0801U")
            payload = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": str(stock_code), "ORD_DVSN": ord_dvsn, "ORD_QTY": str(int(qty)), "ORD_UNPR": price_str, "CTAC_TLNO": "", "PRSR_DVSN": "", "ALGO_NO": ""}
            # (해외 로직 생략 - 국내와 동일 구조로 적용 가능)
        else: return None

        headers = {"Content-Type": "application/json; charset=utf-8", "authorization": f"Bearer {self.access_token}", "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"}
        
        # 🟢 [수정 후] 이렇게 2줄을 바꾸세요!
        try:
            res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5.0)
            data = self._safe_json_parse(res)
            
            if data.get('rt_cd') == '0':
                self.last_error_msg = ""
                # 🚀 [핵심 반환] 한투가 준 진짜 주문번호(ODNO)를 반환하여 Ticker와 동기화합니다.
                odno = data.get('output', {}).get('ODNO', '00000000') 
                self._log_msg(f"✅ 주문 성공 [번호:{odno}]: {data.get('msg1')}", "success")
                return odno 
            else:
                self.last_error_msg = data.get('msg1', '')
                self._log_msg(f"⚠️ 주문 거절: {self.last_error_msg}", "warning")
                return None
        except Exception as e:
            self.last_error_msg = str(e)
            return None
        
    def _wait_for_api_rate_limit(self):
        """
        💡 [상세 설명]
        한투 API는 초당 20회 제한이 있습니다. 
        여러 스레드(매수일꾼, 매도일꾼)가 동시에 요청하는 것을 방지하기 위해
        자물쇠(Lock)를 채우고, 이전 호출로부터 최소 0.06초의 간격을 강제합니다.
        """
        with self.api_lock:
            now = time.time()
            elapsed = now - self.last_api_call
            if elapsed < 0.06: # 안전하게 0.06초 (초당 약 16회)
                time.sleep(0.06 - elapsed)
            self.last_api_call = time.time()

    def fetch_minute_data(self, stock_code):
        """ 최근 1분봉 데이터 조회 (3회 리트라이 방어막 포함) """
        self._wait_for_api_rate_limit() # 💡 API 호출 직전에 무조건 대기

        target_time = "153000" if SystemConfig.MARKET_MODE == "DOMESTIC" else "160000"
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.access_token}", "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": "FHKST03010200", "custtype": "P"}
        params = {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": target_time, "FID_PW_DATA_INCU_YN": "Y"}

        for attempt in range(3): 
            try:
                res = requests.get(url, headers=headers, params=params)
                data = res.json()
                if data.get('rt_cd') == '0':
                    df = pd.DataFrame(data.get('output2', []))
                    # (컬럼 매핑 로직 유지...)
                    df[['open', 'high', 'low', 'close', 'volume']] = df[['stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_prpr', 'cntg_vol']].apply(pd.to_numeric)
                    return df.iloc[::-1].reset_index(drop=True)
                else:
                    msg = data.get('msg1', '')
                    if "초과" in msg or "초당" in msg:
                        time.sleep(0.5) # 트래픽 초과 시 잠시 쉬고 리트라이
                        continue
                    return None
            except: time.sleep(0.5)
        return None

    def cancel_order(self, order_no):
        self._wait_for_api_rate_limit() # 💡 추가!
        """ [B전략] 미체결 주문 강제 취소 전송 """
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecnl"
            tr_id = "VTTC0803U" if self.is_mock else "TTTC0803U"
            payload = {
                "CANO": self.account_no[:8], 
                "ACNT_PRDT_CD": "01", 
                "KRX_FWDG_ORD_ORGNO": "", 
                "ORGN_ODNO": str(order_no), 
                "ORD_DVSN": "00", 
                "RVSE_CNCL_DVSN_CD": "02", # 02가 취소 명령
                "ORD_QTY": "0",            # 0은 전량 취소를 의미
                "ORD_UNPR": "0", 
                "QTY_ALL_ORD_YN": "Y"
            }
            headers = {"Content-Type": "application/json; charset=utf-8", "authorization": f"Bearer {self.access_token}", "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"}
            try:
                # 🔥 [렉 방지 마법] timeout=5.0을 추가해서 한투 서버가 느려도 5초 뒤엔 쿨하게 넘어가도록 설정!
                res = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5.0)
                
                # 🚀 [핵심 방어막] 한투 서버가 렉에 걸려 아무런 대답도 안 줬을 때(빈 화면) 파싱 에러를 막습니다!
                if not res.text.strip():
                    self._log_msg(f"⚠️ 주문취소 지연: 한투 서버 무응답. 다음 턴에 재시도합니다.", "warning")
                    return False

                # 빈 응답이 아닐 때만 안전하게 JSON 변환 시도
                try:
                    data = res.json()
                except json.JSONDecodeError:
                    self._log_msg(f"⚠️ 주문취소 지연: 한투 서버 데이터 깨짐. 다음 턴에 재시도합니다.", "warning")
                    return False

                if data.get('rt_cd') == '0':
                    self._log_msg(f"✅ 주문취소 성공 [원주문번호:{order_no}]", "success")
                    return True
                else:
                    self._log_msg(f"⚠️ 주문취소 실패: {data.get('msg1')}", "warning")

            except Exception as e:
                self._log_msg(f"🚨 주문취소 통신 에러: {e}", "error")
                
        return False
    
    # --- KIS_Manager.py 맨 아래 덮어쓰기 ---
    def get_d2_deposit(self):
        try:
            # 1차 시도: 주문가능금액조회(8908 API)
            headers = {
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {self.api.access_token}",
                "appkey": self.api.app_key, "appsecret": self.api.app_secret,
                "tr_id": "VTTC8908R" if self.api.is_mock else "TTTC8908R", "custtype": "P"
            }
            params = {
                "CANO": self.api.account_no[:8],
                "ACNT_PRDT_CD": self.api.account_no[8:] if len(self.api.account_no) > 8 else "01",
                "PDNO": "005930", "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "Y", "OVRS_ICLD_YN": "N"
            }
            res = requests.get(f"{self.api.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order", headers=headers, params=params, timeout=5)
            data = res.json()
            d2_val = int(float(data.get("output", {}).get("n2_dn_expect_cash_amt", "0")))

            # 💡 만약 0원이라면? 2차 예비 수단(8434 API) 가동
            if d2_val <= 0:
                headers["tr_id"] = "VTTC8434R" if self.api.is_mock else "TTTC8434R"
                res2 = requests.get(f"{self.api.base_url}/uapi/domestic-stock/v1/trading/inquire-balance", headers=headers, params=params, timeout=5)
                d2_val = int(float(res2.json().get("output2", [{}])[0].get("prcs_arrc_excc_amt", "0")))

            return d2_val
        except:
            return 0
# =====================================================================
# 👔 [2] KIS_Manager 클래스 (사용자 편의용 래퍼 클래스)
# =====================================================================
class KIS_Manager:
    def __init__(self, ui_main=None):
        self.ui = ui_main 
        self.db = JubbyDB_Manager()
        
        # 설정 로드
        self.APP_KEY = self.db.get_shared_setting("KIS_API", "APP_KEY", "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy")
        self.APP_SECRET = self.db.get_shared_setting("KIS_API", "APP_SECRET", "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8=")
        self.IS_MOCK = self.db.get_shared_setting("KIS_API", "IS_MOCK", "TRUE").upper() == "TRUE"
        self.ACCOUNT_NO = self.db.get_shared_setting("KIS_API", "STOCK_ACCOUNT", "50172151")
            
        self.api = KIS_API(self.APP_KEY, self.APP_SECRET, self.ACCOUNT_NO, is_mock=self.IS_MOCK, log_callback=self._log)     

    def start_api(self):
        self._log("🎫 KIS API 접속 시도 중...", "info")
        if self.api.get_access_token(): self._log("✅ 인증 성공!", "success")
        
    def _log(self, msg, log_type="error"):
        if self.ui: self.ui.add_log(msg, log_type)
        else: print(f"[{log_type.upper()}] {msg}")

    # =====================================================================
    # 💡 [여기에 추가] 한국 증시 호가단위 자동 계산기 (에러 방지용)
    # =====================================================================
    def get_tick_price(self, price):
        """ 주가를 한국거래소(KRX) 정상 호가 단위로 자동 보정합니다. """
        if SystemConfig.MARKET_MODE != "DOMESTIC":
            return int(price) # 해외 주식은 틱 단위가 다르므로 우선 정수 변환만
            
        p = int(price)
        # 한국 주식 호가 단위 규정
        if p < 2000: tick = 1
        elif p < 5000: tick = 5
        elif p < 20000: tick = 10
        elif p < 50000: tick = 50
        elif p < 200000: tick = 100
        elif p < 500000: tick = 500
        else: tick = 1000
        
        # 호가 단위에 맞게 내림 처리하여 안전하게 지정가 생성
        return int((p // tick) * tick)

    # --- 주문 함수들 (이제 모두 주문번호 ODNO를 반환합니다) ---

    def buy_market_price(self, stock_code, qty):
        """ 시장가 매수 """
        return self.api.order_stock(stock_code, qty, is_buy=True, prcs_dv="01")

    def buy_limit_order(self, code, qty, price):
        """ 지정가 매수 (스마트 지정가용) + 호가 단위 보정 """
        # 계산된 가격을 규격에 맞는 호가로 다듬습니다.
        adj_price = self.get_tick_price(price) 
        
        return self.api.order_stock(code, qty, is_buy=True, limit_price=adj_price)

    # ✅ 올바른 코드 (이걸로 교체)
    def sell(self, code, qty): 
        mode_icon = "🇰🇷" if SystemConfig.MARKET_MODE == "DOMESTIC" else "🌐"
        self._log(f"📉 {mode_icon} [{code}] 매도 전송 중... (시장가 01)", "send")
        # 모의투자 에러 방지를 위해 01(시장가) 유지 권장
        return self.api.order_stock(code, qty, is_buy=False, prcs_dv="01")

    # --- 조회 함수들 ---
    def get_balance(self): return self.api.get_account_balance()
    
    # 🔥 [버그 수정] API에서 받은 리스트 형태의 잔고를 딕셔너리 형태로 예쁘게 포장해서 넘겨줍니다!
    def get_real_holdings(self): 
        raw_list = self.api.get_account_holdings()
        holdings_dict = {}
        if isinstance(raw_list, list):
            for item in raw_list:
                code = item.get('pdno', '') # 종목코드
                qty = int(item.get('hldg_qty', '0')) # 보유수량
                if code and qty > 0:
                    holdings_dict[code] = {
                        'price': float(item.get('pchs_avg_pric', '0')), # 매입단가
                        'qty': qty
                    }
        return holdings_dict

    # --- KIS_Manager.py 맨 아래 덮어쓰기 ---
    def get_d2_deposit(self):
        try:
            # 1차 시도: 주문가능금액조회(8908 API)
            headers = {
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {self.api.access_token}",
                "appkey": self.api.app_key, "appsecret": self.api.app_secret,
                "tr_id": "VTTC8908R" if self.api.is_mock else "TTTC8908R", "custtype": "P"
            }
            params = {
                "CANO": self.api.account_no[:8],
                "ACNT_PRDT_CD": self.api.account_no[8:] if len(self.api.account_no) > 8 else "01",
                "PDNO": "005930", "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "Y", "OVRS_ICLD_YN": "N"
            }
            res = requests.get(f"{self.api.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order", headers=headers, params=params, timeout=5)
            data = res.json()
            d2_val = int(float(data.get("output", {}).get("n2_dn_expect_cash_amt", "0")))

            # 💡 만약 0원이라면? 2차 예비 수단(8434 API) 가동
            if d2_val <= 0:
                headers["tr_id"] = "VTTC8434R" if self.api.is_mock else "TTTC8434R"
                res2 = requests.get(f"{self.api.base_url}/uapi/domestic-stock/v1/trading/inquire-balance", headers=headers, params=params, timeout=5)
                d2_val = int(float(res2.json().get("output2", [{}])[0].get("prcs_arrc_excc_amt", "0")))

            return d2_val
        except:
            return 0

    def fetch_minute_data(self, code): return self.api.fetch_minute_data(code)
    def cancel_order(self, order_no): return self.api.cancel_order(order_no)