import requests
import json
import time
import pandas as pd
import numpy as np

# =====================================================================
# 🌐 시스템 전역 설정 (국내/해외 시장 모드 판별용) 및 DB 매니저
# =====================================================================
from COMMON.Flag import SystemConfig 
from COMMON.DB_Manager import JubbyDB_Manager # 🔥 [DB 연동] 추가

# =====================================================================
# 👨‍💼 [1] KIS_API 클래스 (실제 통신 담당)
# =====================================================================
class KIS_API:
    def __init__(self, app_key, app_secret, account_no, is_mock=True, log_callback=None):
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = str(account_no).strip()
        self.is_mock = is_mock 
        
        # 한국투자증권 API 주소 (모의투자는 VTS, 실전은 일반 주소)
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"
        self.access_token = "" 
        self.log = log_callback 
        
        # 🔥 [DB 연동] 통신 에러나 성공 기록을 무조건 DB에 남기기 위해 장착
        self.db = JubbyDB_Manager()

    def _log_msg(self, msg, log_type="error"):
        """ 터미널에 로그를 띄우고, 동시에 C#이 볼 수 있게 DB에도 저장합니다. """
        if self.log: self.log(msg, log_type)
        else: print(f"[{log_type.upper()}] {msg}")
        
        try: self.db.insert_log(log_type.upper(), msg)
        except: pass

    def get_access_token(self):
        """ API 출입증(토큰)을 발급받습니다. """
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
        """ 내 주머니에 주식을 살 수 있는 현금이 얼마 있는지 확인합니다. """
        time.sleep(0.1)
        balance = 0.0 # 초기값
        
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
            tr_id = "VTTC8908R" if self.is_mock else "TTTC8908R"
            params = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "PDNO": "", 
                "ORD_UNPR": "", "ORD_DVSN": "01", "CMA_EVLU_AMT_ICLD_YN": "N", "OVRS_ICLD_YN": "N"
            }
            
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
            tr_id = "VTTS3012R" if self.is_mock else "JTTT3012R"
            params = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "OVRS_EXCG_CD": "NASD", 
                "TR_CRCY_CD": "USD", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""
            }

        elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
            # 🔥 [방어 로직] 모의투자일 경우 한투에서 지원하지 않으므로 통신을 시도하지 않고 바로 0을 반환합니다.
            if self.is_mock:
                self._log_msg("⚠️ 해외선물은 모의투자 잔고조회 API를 지원하지 않습니다.", "warning")
                return 0.0
                
            url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/inquire-present-balance"
            tr_id = "JTFF2001R" # (실전용 TR_ID 고정)
            params = {
                "CANO": self.account_no[:8], 
                "ACNT_PRDT_CD": "04",
                "TR_CRCY_CD": "USD"
            }
        else:
            return 0.0 

        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params)
            
            # 🔥 [안전장치] 서버가 JSON이 아닌 HTML 에러 페이지를 주면 걸러냅니다!
            try:
                data = res.json()
            except Exception:
                raw_err = str(res.text).replace('<', '&lt;').replace('>', '&gt;')
                self._log_msg(f"🚨 잔고 조회 API 거절 원문(상태코드 {res.status_code}): {raw_err}", "error")
                return 0.0

            if data.get('rt_cd') == '0':
                if SystemConfig.MARKET_MODE == "DOMESTIC":
                    balance = float(data.get('output', {}).get('ord_psbl_cash', 0))
                elif SystemConfig.MARKET_MODE == "OVERSEAS":
                    out2 = data.get('output2', {})
                    out3 = data.get('output3', {})
                    cash = out2.get('frcr_ord_psbl_amt1') or out3.get('frcr_ord_psbl_amt1') or out2.get('frcr_dncl_amt_2') or 0
                    balance = float(cash)
                elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
                    balance = float(data.get('output', {}).get('ord_psbl_amt', 0))
                    
                try: self.db.set_shared_setting("ACCOUNT", "CASH", str(balance))
                except: pass
                
                return balance
            else:
                market_str = "국내" if SystemConfig.MARKET_MODE == "DOMESTIC" else ("해외" if SystemConfig.MARKET_MODE == "OVERSEAS" else "해외선물")
                self._log_msg(f"⚠️ {market_str} 잔고 조회 거절: {data.get('msg1')}", "error")
        except Exception as e:
            self._log_msg(f"🚨 잔고 조회 중 통신 오류: {e}", "error")
            
        return 0.0

   # =====================================================================
    # 📦 계좌 보유 종목 조회
    # =====================================================================
    def get_account_holdings(self):
        """ 현재 내 계좌에 물려있거나(?) 들고 있는 주식 목록을 가져옵니다. """
        time.sleep(0.1)
        holdings = {}
        
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
            tr_id = "VTTC8434R" if self.is_mock else "TTTC8434R"
            params = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "AFHR_FLPR_YN": "N",
                "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
            }
            
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{self.base_url}/uapi/overseas-stock/v1/trading/inquire-present-balance"
            tr_id = "VTTS3012R" if self.is_mock else "JTTT3012R"
            params = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01", "OVRS_EXCG_CD": "NASD", 
                "TR_CRCY_CD": "USD", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""
            }
            
        # 🔥 [치명적 버그 수정] 해외선물 보유종목 조회 로직 추가!
        elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
            if self.is_mock: return {} # 모의투자는 미지원
            url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/inquire-balance"
            tr_id = "JTFF3012R"
            params = {"CANO": self.account_no[:8], "ACNT_PRDT_CD": "04"}
        else:
            return {}

        headers = {
            "Content-Type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key, "appSecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            
            if data.get('rt_cd') == '0':
                for item in data.get('output1', []):
                    qty_key = 'hldg_qty' if SystemConfig.MARKET_MODE == "DOMESTIC" else 'ovrs_cblc_qty'
                    pdno_key = 'pdno' if SystemConfig.MARKET_MODE == "DOMESTIC" else 'ovrs_pdno'
                    price_key = 'pchs_avg_pric'
                    
                    if qty_key in item and int(float(item.get(qty_key, 0))) > 0:
                        holdings[item[pdno_key]] = {'price': float(item[price_key]), 'qty': int(float(item[qty_key]))}
            else:
                market_str = "국내" if SystemConfig.MARKET_MODE == "DOMESTIC" else ("해외" if SystemConfig.MARKET_MODE == "OVERSEAS" else "해외선물")
                self._log_msg(f"⚠️ {market_str} 보유종목 조회 거절: {data.get('msg1')}", "warning")
        except Exception as e: 
            self._log_msg(f"🚨 보유종목 조회 중 통신 오류: {e}", "error")
            
        return holdings
    
    # =====================================================================
    # 🛒 시장가 매수/매도 주문
    # =====================================================================
    def order_stock(self, stock_code, qty, is_buy=True):
        """ 한국투자증권에 실제로 '이거 사줘!', '이거 팔아줘!' 라고 명령을 보냅니다. """
        time.sleep(0.2)
        
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
            tr_id = ("VTTC0802U" if is_buy else "VTTC0801U") if self.is_mock else ("TTTC0802U" if is_buy else "TTTC0801U")
            payload = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01",
                "PDNO": str(stock_code), "ORD_DVSN": "01", 
                "ORD_QTY": str(int(qty)), "ORD_UNPR": "0",
                "CTAC_TLNO": "", "PRSR_DVSN": "", "ALGO_NO": ""
            }
            
        elif SystemConfig.MARKET_MODE == "OVERSEAS":
            url = f"{self.base_url}/uapi/overseas-stock/v1/trading/order"
            tr_id = ("VTTT1002U" if is_buy else "VTTT1006U") if self.is_mock else ("JTTT1002U" if is_buy else "JTTT1006U")
            payload = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "01",
                "OVRS_EXCG_CD": "NASD", "PDNO": str(stock_code),
                "ORD_QTY": str(int(qty)), "OVRS_ORD_UNPR": "0", 
                "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00" 
            }

        # 🔥 [치명적 버그 수정] 해외선물 매수/매도 주문 로직 추가!
        elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
            if self.is_mock:
                self._log_msg("⚠️ 모의투자는 해외선물 주문 API를 지원하지 않습니다.", "warning")
                return False
            url = f"{self.base_url}/uapi/overseas-futureoption/v1/trading/order"
            tr_id = "JTFF1002U" if is_buy else "JTFF1006U" # 선물 실전 매수/매도 TR_ID
            payload = {
                "CANO": self.account_no[:8], "ACNT_PRDT_CD": "04",
                "PDNO": str(stock_code), "ORD_QTY": str(int(qty)),
                "ORD_DVSN": "01", "ORD_UNPR": "0" # 01: 시장가
            }
        else:
            return False

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
                self._log_msg(f"⚠️ 주문 거절 (사유: {data.get('msg1')})", "warning")
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
    # 📈 최근 1분봉 데이터 120개 조회 (AI 분석용)
    # =====================================================================
    def fetch_minute_data(self, stock_code):
        """ 종목 코드를 넣으면, 최근 120분 동안의 1분봉 차트 데이터를 가져옵니다. """
        
        # 🚀 [플랜 B 발동] 해외선물은 한투에서 분봉을 안 주므로 야후(yfinance)로 직행!
        if SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
            try:
                import yfinance as yf
                yf_ticker = stock_code
                if "NQ" in stock_code: yf_ticker = "NQ=F"
                elif "ES" in stock_code: yf_ticker = "ES=F"
                elif "YM" in stock_code: yf_ticker = "YM=F"
                elif "GC" in stock_code: yf_ticker = "GC=F"
                elif "CL" in stock_code: yf_ticker = "CL=F"

                df_yf = yf.download(yf_ticker, period="1d", interval="1m", progress=False)
                if df_yf.empty: return None
                
                if isinstance(df_yf.columns, pd.MultiIndex):
                    df_yf.columns = df_yf.columns.get_level_values(0)
                
                df_yf = df_yf.reset_index()
                df_yf.rename(columns={'Open': 'open', 'High': 'high', 'Low': 'low', 'Close': 'close', 'Volume': 'volume'}, inplace=True)
                
                df_res = df_yf[['open', 'high', 'low', 'close', 'volume']].copy()
                df_res[['open', 'high', 'low', 'close', 'volume']] = df_res[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
                
                return df_res.dropna().tail(120).reset_index(drop=True)
            except Exception as e:
                self._log_msg(f"🚨 야후 파이낸스 실시간 분봉 수집 에러: {e}", "error")
                return None

        # 🇰🇷 / 🌐 주식은 정상적으로 한국투자증권 API 사용
        target_time = "153000" if SystemConfig.MARKET_MODE == "DOMESTIC" else "160000"
        
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            tr_id = "FHKST03010200"
            params = {
                "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", 
                "FID_INPUT_ISCD": stock_code, "FID_INPUT_HOUR_1": target_time, "FID_PW_DATA_INCU_YN": "Y"
            }
        else: # OVERSEAS
            url = f"{self.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
            tr_id = "HHDFS76950200"
            params = {
                "AUTH": "", "EXCD": "NAS", "SYMB": stock_code, "NMIN": "1", "PINC": "1", 
                "NEXT": "", "NREC": "120", "FILL": "", "KEYB": ""
            }

        headers = {
            "content-type": "application/json", "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key, "appsecret": self.app_secret, "tr_id": tr_id, "custtype": "P"
        }

        try:
            res = requests.get(url, headers=headers, params=params)
            data = res.json()
            if data.get('rt_cd') == '0':
                output = data.get('output2', [])
                if not output: return None
                
                df = pd.DataFrame(output)
                cols = df.columns.tolist()
                
                c_open = next((c for c in ['stck_oprc', 'open', 'oprc'] if c in cols), None)
                c_high = next((c for c in ['stck_hgpr', 'high', 'hgpr'] if c in cols), None)
                c_low = next((c for c in ['stck_lwpr', 'low', 'lwpr'] if c in cols), None)
                c_close = next((c for c in ['stck_prpr', 'last', 'close', 'prpr'] if c in cols), None)
                c_vol = next((c for c in ['evol', 'cntg_vol', 'vold', 'vol', 'acml_vol'] if c in cols), None)
                
                if None in [c_open, c_high, c_low, c_close, c_vol]: return None

                df = df[[c_open, c_high, c_low, c_close, c_vol]]
                df.columns = ['open', 'high', 'low', 'close', 'volume']
                df = df.apply(pd.to_numeric)
                
                # 시간 역순(최신이 맨 앞)으로 오는 데이터를 과거->최신 순으로 뒤집기
                df = df.iloc[::-1].reset_index(drop=True)
                return df
            else:
                return None
        except Exception:
            return None

# =====================================================================
# 👔 [2] KIS_Manager 클래스
# =====================================================================
class KIS_Manager:
    def __init__(self, ui_main=None):
        """ 매니저 클래스: 복잡한 API 통신 로직을 감싸서 밖에서는 편하게 함수만 부를 수 있게 해줍니다. """
        self.ui = ui_main 
        
        self.APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
        self.APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
        
        # 🔥 [수정] 모드에 따라 사용하는 계좌번호를 다르게 셋팅합니다!
        if SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
            self.ACCOUNT_NO = "60039684" # 🚀 해외선물옵션 전용 계좌
        else:
            self.ACCOUNT_NO = "50172151" # 🇰🇷/🌐 주식 전용 계좌
            
        self.IS_MOCK = True # 현재 모의투자 상태
        
        # 위에서 만든 API 통신 전담 직원을 고용합니다.
        self.api = KIS_API(self.APP_KEY, self.APP_SECRET, self.ACCOUNT_NO, is_mock=self.IS_MOCK, log_callback=self._log)

    def start_api(self):
        self._log("🎫 KIS API 접속 시도 중...", "info")
        if self.api.get_access_token(): self._log("✅ 인증 성공!", "success")
        
    def _log(self, msg, log_type="error"):
        if self.ui: self.ui.add_log(msg, log_type)
        else: print(f"[{log_type.upper()}] {msg}")

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