import requests
import json
import asyncio
import websockets
import threading
import pandas as pd
import time

# =====================================================================
# 👨‍💼 [1] KIS_API 클래스 (실제 통신 담당)
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
        except Exception: pass
        return None

    def get_account_balance(self):
        time.sleep(0.1)
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret,
            "tr_id": "VTTC8908R" if self.is_mock else "TTTC8908R", "custtype": "P"
        }
        params = {
            "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": "", 
            "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
        }
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get('rt_cd') == '0': return int(data['output']['ord_psbl_cash'])
        except: pass
        return 0

    def get_account_holdings(self):
        time.sleep(0.1)
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
            data = res.json()
            if data.get('rt_cd') == '0':
                for item in data.get('output1', []):
                    qty = int(item['hldg_qty'])
                    if qty > 0:
                        holdings[item['pdno']] = {'price': float(item['pchs_avg_pric']), 'qty': qty}
        except: pass
        return holdings

    # =====================================================================
    # 🛒 시장가 매수/매도 주문 (계좌 상품코드 01, 02 2중 시도)
    # =====================================================================
    def order_stock(self, stock_code, qty, is_buy=True):
        time.sleep(0.2)
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        tr_id = ("VTTC0802U" if is_buy else "VTTC0801U") if self.is_mock else ("TTTC0802U" if is_buy else "TTTC0801U")
        
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P"
        }

        payload = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": "01",
            "PDNO": str(stock_code),
            "ORD_DVSN": "01",
            "ORD_QTY": str(int(qty)),
            "ORD_UNPR": "0",
            "CTAC_TLNO": "",
            "PRSR_DVSN": "",
            "ALGO_NO": ""
        }
        
        try:
            res = requests.post(url, headers=headers, data=json.dumps(payload))
            data = res.json()
            
            if data.get('rt_cd') == '0':
                return True
            else:
                # 🚨 잔고 에러 시 상품코드를 '02'로 변경하여 재시도
                if not is_buy and self.is_mock and ("잔고" in data.get('msg1', '')):
                    payload["ACNT_PRDT_CD"] = "02"
                    self._log_msg(f"🔄 [{stock_code}] 상품코드 02로 재시도 중...", "info")
                    res = requests.post(url, headers=headers, data=json.dumps(payload))
                    if res.json().get('rt_cd') == '0': return True
                
                self._log_msg(f"⚠️ 주문 거절: {data.get('msg1')}")
                return False
        except Exception as e:
            self._log_msg(f"🚨 시스템 오류: {e}")
            return False

    def fetch_minute_data(self, stock_code):
        time.sleep(0.1)
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {"Content-Type": "application/json", "authorization": f"Bearer {self.access_token}", "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": "FHKST03010200", "custtype": "P"}
        params = {"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": "", "FID_PW_DATA_INCU_YN": "Y"}
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data['rt_cd'] == '0':
                df = pd.DataFrame(data['output2'])
                df = df[['stck_bsop_date', 'stck_cntg_hour', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'stck_prpr', 'cntg_vol']]
                df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
                return df.apply(pd.to_numeric).iloc[::-1].reset_index(drop=True) 
        except: pass
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

    # 💡 누락되었던 buy_market_price 함수 완벽 복구!
    def buy_market_price(self, stock_code, qty):
        self._log(f"🛒 [{stock_code}] {qty}주 매수 시도 (시장가)", "buy")
        return self.api.order_stock(stock_code, qty, is_buy=True)

    def check_my_balance(self): return self.api.get_account_balance()
    def buy(self, code, qty): return self.api.order_stock(code, qty, is_buy=True)
    def sell(self, code, qty): 
        self._log(f"📉 [{code}] 매도 전송 중...", "send")
        return self.api.order_stock(code, qty, is_buy=False)
    def get_balance(self): return self.api.get_account_balance()
    def get_real_holdings(self): return self.api.get_account_holdings()
    def fetch_minute_data(self, code): return self.api.fetch_minute_data(code)