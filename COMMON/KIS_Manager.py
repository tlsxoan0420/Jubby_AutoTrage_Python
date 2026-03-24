import requests
import json
import time
import pandas as pd
import numpy as np

# =====================================================================
# 🌐 시스템 전역 설정 (국내/해외 시장 모드 판별용)
# =====================================================================
from COMMON.Flag import SystemConfig 

# =====================================================================
# 👨‍💼 [1] KIS_API 클래스 (실제 통신 담당)
# =====================================================================
class KIS_API:
    def __init__(self, app_key, app_secret, account_no, is_mock=True, log_callback=None):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = str(account_no).strip()
        self.is_mock = is_mock 
        
        # 한국투자증권 API 도메인
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
        self.access_token = "" 
        self.log = log_callback 

    def _log_msg(self, msg, log_type="error"):
        if self.log: self.log(msg, log_type)
        else: print(f"[{log_type}] {msg}")

    def get_access_token(self):
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "appsecret": self.app_secret}
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body))
            if res.status_code == 200:
                self.access_token = res.json().get("access_token")
                return self.access_token
            else:
                self._log_msg(f"토큰 발급 실패: {res.text}", "error")
        except Exception as e: 
            self._log_msg(f"토큰 발급 오류: {e}", "error")
        return None
    
    # =====================================================================
    # 💰 계좌 주문 가능 금액(잔고) 조회
    # =====================================================================
    def get_account_balance(self):
        time.sleep(0.1)
        
        # 🇰🇷 [분기 1] 국내 주식 모드일 때
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
            tr_id = "VTTC8908R" if self.is_mock else "TTTC8908R"
            params = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": "", 
                "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
            }
            
        # 🌐 [분기 2] 해외 주식 모드일 때
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
            tr_id = "VTTS3012R" if self.is_mock else "JTTT3012R"
            
            # 🔥 [핵심 수정] 해외 잔고조회 필수 파라미터(OVRS_EXCG_CD 등) 완벽 세팅
            params = {
                "CANO": self.account_no[:8], 
                "ACNT_PRDT_CD": "01", 
                "OVRS_EXCG_CD": "NASD", # 나스닥 (전체는 NASD로 통일해도 조회됨)
                "TR_CRCY_CD": "USD",    # 달러
                "CTX_AREA_FK200": "", 
                "CTX_AREA_NK200": ""
            }

        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret,
            "tr_id": tr_id, "custtype": "P"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            
            if data.get('rt_cd') == '0':
                if SystemConfig.MARKET_MODE == "DOMESTIC":
                    return float(data['output']['ord_psbl_cash'])
                else:
                    # 💡 해외는 output2 또는 output3에 주문 가능 금액(달러)이 들어있습니다.
                    out2 = data.get('output2', {})
                    out3 = data.get('output3', {})
                    
                    # 외화주문가능금액1(frcr_ord_psbl_amt1) 또는 외화예수금(frcr_dncl_amt_2) 스캔
                    cash = out2.get('frcr_ord_psbl_amt1') or out3.get('frcr_ord_psbl_amt1') or out2.get('frcr_dncl_amt_2') or 0
                    return float(cash)
            else:
                market_str = "국내" if SystemConfig.MARKET_MODE == "DOMESTIC" else "해외"
                self._log_msg(f"⚠️ {market_str} 잔고 조회 거절: {data.get('msg1')}", "error")
        except Exception as e:
            self._log_msg(f"🚨 잔고 조회 중 통신 오류: {e}", "error")
            
        return 0

    # =====================================================================
    # 📦 계좌 보유 종목 조회
    # =====================================================================
    def get_account_holdings(self):
        time.sleep(0.1)
        holdings = {}
        
        # 🇰🇷 [분기 1] 국내 주식 모드
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
            tr_id = "VTTC8434R" if self.is_mock else "TTTC8434R"
            params = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "AFHR_FLPR_YN": "N",
                "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
            }
            
        # 🌐 [분기 2] 해외 주식 모드
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            # 🔥 [핵심 수정] 해외 주식 잔고는 inquire-balance가 아니라 inquire-present-balance를 써야 합니다.
            url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
            tr_id = "VTTS3012R" if self.is_mock else "JTTT3012R"
            
            # 🔥 [핵심 수정] 잔고 조회와 똑같은 필수 파라미터 세팅
            params = {
                "CANO": self.account_no[:8], 
                "ACNT_PRDT_CD": "01",
                "OVRS_EXCG_CD": "NASD", 
                "TR_CRCY_CD": "USD", 
                "CTX_AREA_FK200": "", 
                "CTX_AREA_NK200": ""
            }

        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret,
            "tr_id": tr_id, "custtype": "P"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            
            if data.get('rt_cd') == '0':
                for item in data.get('output1', []):
                    qty_key = 'hldg_qty' if SystemConfig.MARKET_MODE == "DOMESTIC" else 'ovrs_cblc_qty'
                    pdno_key = 'pdno' if SystemConfig.MARKET_MODE == "DOMESTIC" else 'ovrs_pdno'
                    price_key = 'pchs_avg_pric'
                    
                    if qty_key in item and int(item.get(qty_key, 0)) > 0:
                        holdings[item[pdno_key]] = {'price': float(item[price_key]), 'qty': int(item[qty_key])}
            else:
                market_str = "국내" if SystemConfig.MARKET_MODE == "DOMESTIC" else "해외"
                self._log_msg(f"⚠️ {market_str} 보유종목 조회 거절: {data.get('msg1')}", "warning")
        except Exception as e: 
            self._log_msg(f"🚨 보유종목 조회 중 통신 오류: {e}", "error")
            
        return holdings
    
    # =====================================================================
    # 🛒 시장가 매수/매도 주문
    # =====================================================================
    def order_stock(self, stock_code, qty, is_buy=True):
        time.sleep(0.2)
        
        # 🇰🇷 [분기 1] 국내 주식 주문
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
            tr_id = ("VTTC0802U" if is_buy else "VTTC0801U") if self.is_mock else ("TTTC0802U" if is_buy else "TTTC0801U")
            
            payload = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01",
                "PDNO": str(stock_code), "ORD_DVSN": "01", # 01: 시장가
                "ORD_QTY": str(int(qty)), "ORD_UNPR": "0",
                "CTAC_TLNO": "", "PRSR_DVSN": "", "ALGO_NO": ""
            }
            
        # 🌐 [분기 2] 해외 주식 주문
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
            # 🔥 해외주식 매매 TR_ID 완벽 교정 (모의/실전 구분)
            tr_id = ("VTTT1002U" if is_buy else "VTTT1006U") if self.is_mock else ("JTTT1002U" if is_buy else "JTTT1006U")
            
            payload = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01",
                "OVRS_EXCG_CD": "NASD", "PDNO": str(stock_code),
                "ORD_QTY": str(int(qty)), "OVRS_ORD_UNPR": "0", 
                "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00" 
            }

        headers = {
            "Content-Type": "application/json; charset=utf-8", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        
        try:
            res = requests.post(url, headers=headers, data=json.dumps(payload))
            data = res.json()
            
            if data.get('rt_cd') == '0':
                self._log_msg(f"✅ [{SystemConfig.MARKET_MODE}] 주문 성공: {data.get('msg1')}", "success")
                return True
            else:
                # 🚨 에러가 발생하면 반드시 로그창에 이유를 띄웁니다!
                self._log_msg(f"⚠️ 주문 거절 (사유: {data.get('msg1')})", "warning")
                
                # 모의투자 에러 우회
                if SystemConfig.MARKET_MODE == "DOMESTIC" and not is_buy and self.is_mock and ("잔고" in data.get('msg1', '')):
                    payload["ACNT_PRDT_CD"] = "02"
                    self._log_msg(f"🔄 [{stock_code}] 상품코드 02로 재시도 중...", "info")
                    res = requests.post(url, headers=headers, data=json.dumps(payload))
                    if res.json().get('rt_cd') == '0': return True
                    
                return False
        except Exception as e:
            self._log_msg(f"🚨 주문 통신 오류: {e}")
            return False

    # =====================================================================
    # 📈 1분봉 차트 데이터 조회 (어떤 이름이 와도 알아서 변환)
    # =====================================================================
    def fetch_minute_data(self, stock_code):
        time.sleep(0.1)
        
        # 🇰🇷 [분기 1] 국내 분봉 조회
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            headers = {
                "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}", 
                "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": "FHKST03010200", "custtype": "P"
            }
            params = {
                "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", 
                "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": "", "FID_PW_DATA_INCU_YN": "Y"
            }
            
        # 🌐 [분기 2] 해외(미국) 분봉 조회
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{self.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
            headers = {
                "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}", 
                "appKey": self.app_key, "appSecret": self.app_secret, 
                "tr_id": "HHDFS76950200", 
                "custtype": "P"
            }
            params = {
                "AUTH": "", "EXCD": "NAS", "SYMB": stock_code, 
                "NMIN": "1", "PINC": "1", 
                "NEXT": "", "NREC": "120", "FILL": "", "KEYB": ""
            }
            
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            
            if data['rt_cd'] == '0':
                df = pd.DataFrame(data['output2'])
                
                cols = df.columns.tolist()
                c_date = 'stck_bsop_date' if 'stck_bsop_date' in cols else ('xymd' if 'xymd' in cols else cols[0])
                c_time = 'stck_cntg_hour' if 'stck_cntg_hour' in cols else ('xhms' if 'xhms' in cols else ('xhm' if 'xhm' in cols else cols[1]))
                c_open = 'open' if 'open' in cols else ('oprc' if 'oprc' in cols else None)
                c_high = 'high' if 'high' in cols else ('hgpr' if 'hgpr' in cols else None)
                c_low = 'low' if 'low' in cols else ('lwpr' if 'lwpr' in cols else None)
                c_close = 'last' if 'last' in cols else ('prpr' if 'prpr' in cols else ('close' if 'close' in cols else None))
                c_vol = 'evol' if 'evol' in cols else ('vold' if 'vold' in cols else ('cntg_vol' if 'cntg_vol' in cols else ('vol' if 'vol' in cols else None)))
                
                df = df[[c_date, c_time, c_open, c_high, c_low, c_close, c_vol]]
                df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
                
                return df.apply(pd.to_numeric).iloc[::-1].reset_index(drop=True) 
        except:
            pass
            
        return None

# =====================================================================
# 👔 [2] KIS_Manager 클래스
# =====================================================================
class KIS_Manager:
    def __init__(self, ui_main=None):
        self.ui = ui_main 
        
        self.APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
        self.APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
        self.ACCOUNT_NO = "50172151" 
        self.IS_MOCK = True 
        self.api = KIS_API(self.APP_KEY, self.APP_SECRET, self.ACCOUNT_NO, is_mock=self.IS_MOCK, log_callback=self._log)

    def start_api(self):
        self._log("🎫 KIS API 접속 시도 중...", "info")
        if self.api.get_access_token(): self._log("✅ 인증 성공!", "success")
        
    def _log(self, msg, log_type="error"):
        if self.ui: self.ui.add_log(msg, log_type)
        else: print(f"[{log_type}] {msg}")

    def buy_market_price(self, stock_code, qty):
        mode_icon = "🇰🇷" if SystemConfig.MARKET_MODE == "DOMESTIC" else "🌐"
        self._log(f"🛒 {mode_icon} [{stock_code}] {qty}주 매수 시도 (시장가)", "buy")
        return self.api.order_stock(stock_code, qty, is_buy=True)

    def check_my_balance(self): return self.api.get_account_balance()
    def buy(self, code, qty): return self.api.order_stock(code, qty, is_buy=True)
    
    def sell(self, code, qty): 
        mode_icon = "🇰🇷" if SystemConfig.MARKET_MODE == "DOMESTIC" else "🌐"
        self._log(f"📉 {mode_icon} [{code}] 매도 전송 중...", "send")
        return self.api.order_stock(code, qty, is_buy=False)
        
    def get_balance(self): return self.api.get_account_balance()
    def get_real_holdings(self): return self.api.get_account_holdings()
    def fetch_minute_data(self, code): return self.api.fetch_minute_data(code)