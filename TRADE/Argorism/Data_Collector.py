import sys
import os
import pandas as pd
import numpy as np
import requests
import time
import FinanceDataReader as fdr

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

import COMMON.KIS_Manager as KIS

# =====================================================================
# 🌐 시스템 전역 설정 (국내/해외 시장 모드 판별용)
# =====================================================================
from COMMON.Flag import SystemConfig 

class UltraDataCollector:
    def __init__(self, app_key, app_secret, account_no, is_mock=True, log_callback=None):
        self.log_callback = log_callback
        
        market_name = "국내 주식" if SystemConfig.MARKET_MODE == "DOMESTIC" else "미국(해외) 주식"
        # 인사말 업데이트!
        self.send_log(f"🔥 [주삐 울트라 컬렉터] 시스템 가동! {market_name} 시가총액 상위 종목의 '최근 5거래일(1주일)' 빅데이터 사냥을 준비합니다.", "success")
        
        self.api = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        self.api.get_access_token()
        
        self.base_url = self.api.base_url
        self.market_dict = {} 

        if not self.api.access_token:
            self.send_log("🚨 [경고] 토큰 발급에 실패했습니다. API Key나 모의/실전 여부를 다시 확인하세요!", "error")
        else:
            self.send_log(f"🔑 발급된 토큰 확인: {self.api.access_token[:15]}... (보안상 일부만 표시)", "info")
        
    def send_log(self, msg, log_type="info"):
        if self.log_callback: self.log_callback(msg, log_type)
        else: print(msg) 

    # =====================================================================
    # 📈 분봉 데이터 수집 (어떤 컬럼명이 와도 알아서 매핑하는 자율 주행 로직)
    # =====================================================================
    def fetch_full_day_data(self, stock_code, is_market_index=False):
        all_chunks = [] 
        
        target_time = "153000" if SystemConfig.MARKET_MODE == "DOMESTIC" else "160000"
        next_key = ""

        loop_count = 65 if SystemConfig.MARKET_MODE == "DOMESTIC" else 17

        for i in range(loop_count):
            if SystemConfig.MARKET_MODE == "DOMESTIC" or (is_market_index and SystemConfig.MARKET_MODE == "DOMESTIC"):
                url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
                headers = {
                    "content-type": "application/json",
                    "authorization": f"Bearer {self.api.access_token}",
                    "appkey": self.api.app_key, "appsecret": self.api.app_secret,
                    "tr_id": "FHKST03010200", "custtype": "P"
                }
                params = {
                    "FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", 
                    "FID_INPUT_ISCD": stock_code, 
                    "FID_INPUT_HOUR_1": target_time, 
                    "FID_PW_DATA_INCU_YN": "Y"  
                }

            elif SystemConfig.MARKET_MODE == "OVERSEAS":
                url = f"{self.base_url}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
                headers = {
                    "content-type": "application/json",
                    "authorization": f"Bearer {self.api.access_token}",
                    "appkey": self.api.app_key, "appsecret": self.api.app_secret,
                    "tr_id": "HHDFS76950200", 
                    "custtype": "P"
                }
                params = {
                    "AUTH": "", "EXCD": "NAS", "SYMB": stock_code, 
                    "NMIN": "1", "PINC": "1", 
                    "NEXT": next_key, "NREC": "120", "FILL": "",
                    "KEYB": next_key
                }
            
            res = requests.get(url, headers=headers, params=params)
            
            if res.status_code == 200 and res.json().get('rt_cd') == '0':
                json_data = res.json()
                data = json_data.get('output2', [])
                
                if not data: break 
                
                df_chunk = pd.DataFrame(data)
                
                # =================================================================
                # 🤖 [핵심 수정] 서버가 준 이름표가 뭔지 스캔해서 알아서 끼워 맞춥니다!
                # =================================================================
                cols = df_chunk.columns.tolist()
                
                c_date = 'stck_bsop_date' if 'stck_bsop_date' in cols else ('xymd' if 'xymd' in cols else cols[0])
                
                # 🔥 [수정 1] xhm 대신 xhms 를 찾도록 추가합니다!
                c_time = 'stck_cntg_hour' if 'stck_cntg_hour' in cols else ('xhms' if 'xhms' in cols else ('xhm' if 'xhm' in cols else cols[1]))
                
                c_open = 'open' if 'open' in cols else ('oprc' if 'oprc' in cols else None)
                c_high = 'high' if 'high' in cols else ('hgpr' if 'hgpr' in cols else None)
                c_low = 'low' if 'low' in cols else ('lwpr' if 'lwpr' in cols else None)
                c_close = 'last' if 'last' in cols else ('prpr' if 'prpr' in cols else ('close' if 'close' in cols else None))
                
                # 🔥 [수정 2] vold 대신 evol 를 우선적으로 찾도록 추가합니다!
                c_vol = 'evol' if 'evol' in cols else ('vold' if 'vold' in cols else ('cntg_vol' if 'cntg_vol' in cols else ('vol' if 'vol' in cols else None)))

                try:
                    df_chunk = df_chunk[[c_date, c_time, c_open, c_high, c_low, c_close, c_vol]]
                    df_chunk.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
                except Exception as e:
                    self.send_log(f"🚨 [매핑 에러] 서버에서 이상한 데이터를 줬습니다: {cols}", "error")
                    break
                # =================================================================
                
                if SystemConfig.MARKET_MODE == "OVERSEAS":
                    all_chunks.append(df_chunk)
                    
                    output1 = json_data.get('output1', {})
                    next_key = output1.get('next', "") if isinstance(output1, dict) else ""
                    if not next_key: break
                else:
                    all_chunks.append(df_chunk)
                    target_time = data[-1]['stck_cntg_hour'] 
                    if int(target_time) <= 90000: break
                    
                time.sleep(0.1) 
            else:
                try: err_msg = res.json().get('msg1', '알 수 없는 에러')
                except: err_msg = f"HTTP 상태코드 {res.status_code}"
                self.send_log(f"❌ [{stock_code}] 데이터 조회 끝 (사유: {err_msg})", "warning")
                time.sleep(0.5) 
                break
            
        if not all_chunks: return None
        
        df = pd.concat(all_chunks).drop_duplicates()
        
        if 'date' in df.columns and 'time' in df.columns:
            df = df.sort_values(by=['date', 'time'])
        elif 'stck_bsop_date' in df.columns:
            df = df.sort_values(by=['stck_bsop_date', 'stck_cntg_hour'])

        df['code'] = stock_code 
        
        required_cols = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
        if len(df.columns) >= len(required_cols):
            df = df[['date', 'time', 'open', 'high', 'low', 'close', 'volume', 'code']]
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
            return df.reset_index(drop=True)
        else:
            return None

    def make_ai_dataset(self, df):
        if df is None or len(df) < 30: return None
        
        df['return'] = df['close'].pct_change() * 100 
        df['vol_change'] = df['volume'].pct_change() 

        delta = df['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.ewm(com=13).mean())))
        df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        
        df['MA20'] = df['close'].rolling(20).mean()
        df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
        df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['MA20']

        df['MA5'] = df['close'].rolling(5).mean()
        df['Disparity_5'] = (df['close'] / df['MA5']) * 100
        df['Disparity_20'] = (df['close'] / df['MA20']) * 100

        df['Vol_MA5'] = df['volume'].rolling(5).mean()
        df['Vol_Energy'] = np.where(df['Vol_MA5'] > 0, df['volume'] / df['Vol_MA5'], 1)

        df['OBV'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        df['OBV_Trend'] = df['OBV'].pct_change()

        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = true_range.rolling(14).mean()

        df['High_Tail'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['Low_Tail'] = df[['open', 'close']].min(axis=1) - df['low']

        df['Buying_Pressure'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
        df['Market_Return_1m'] = df['time'].map(self.market_dict).fillna(0.0)

        df['future_max_10'] = df['close'].rolling(window=10).max().shift(-10)
        df['future_min_10'] = df['close'].rolling(window=10).min().shift(-10)

        df['Target_Buy'] = np.where(df['future_max_10'] >= df['close'] * 1.01, 1, 0)
        df['Target_Sell'] = np.where((df['future_min_10'] <= df['close'] * 0.99) | 
                                     (df['future_max_10'] < df['close'] * 1.002), 1, 0)

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return df.dropna().reset_index(drop=True)

    def run_collection(self, stock_list):
        if SystemConfig.MARKET_MODE == "DOMESTIC":
            market_ticker = '114800' 
            self.send_log(f"📈 [시장 지수 맵핑] 코스닥 지표({market_ticker})를 생성합니다...", "info")
        else:
            market_ticker = 'QQQ' 
            self.send_log(f"📈 [시장 지수 맵핑] 미국 나스닥 ETF({market_ticker}) 지표를 생성합니다...", "info")

        market_df = self.fetch_full_day_data(market_ticker, is_market_index=True)
        if market_df is not None:
            market_df['Market_Return_1m'] = market_df['close'].pct_change() * 100
            self.market_dict = dict(zip(market_df['time'], market_df['Market_Return_1m'].fillna(0)))
            self.send_log("✅ 시장 지수 맵핑 완료! 개별 종목 수집을 시작합니다.", "success")
        else:
            self.send_log("⚠️ 시장 지수 수집 실패. 지수 등락률은 0으로 고정됩니다.", "warning")

        final_combined_data = []
        consecutive_errors = 0 
        
        self.send_log(f"📊 총 {len(stock_list)}개 종목 사냥 시작! (모드: {SystemConfig.MARKET_MODE}, 기간: 5거래일 최대치)", "info")
        
        for idx, code in enumerate(stock_list):
            try:
                raw = self.fetch_full_day_data(code)
                if raw is not None:
                    processed = self.make_ai_dataset(raw)
                    if processed is not None:
                        final_combined_data.append(processed)
                        consecutive_errors = 0 
                        
                        if (idx + 1) % 10 == 0:
                            current_count = sum(len(d) for d in final_combined_data)
                            self.send_log(f"✅ {idx + 1}번째 완료! (누적 데이터: {current_count:,}줄)", "success")
                    else:
                        consecutive_errors += 1
                else:
                    consecutive_errors += 1
                    
            except Exception as e:
                consecutive_errors += 1
                self.send_log(f"⚠️ [{code}] 사냥 실패: {e}", "warning")

            if consecutive_errors >= 20:
                self.send_log("🚨 [오류] 서버 거절 20번 연속 발생. 수집망 강제 종료.", "error")
                break

        if final_combined_data:
            master_df = pd.concat(final_combined_data).reset_index(drop=True)
            
            file_name = "AI_Ultra_Master_Train_Data_V3.csv" if SystemConfig.MARKET_MODE == "DOMESTIC" else "AI_Ultra_Master_Train_Data_Overseas.csv"
            save_path = os.path.join(root_dir, file_name)
            
            master_df.to_csv(save_path, index=False, encoding="utf-8-sig")
            
            self.send_log(f"💎 [대성공!] 총 {len(master_df):,}줄의 압도적인 지표 족보 완성!", "buy")
            self.send_log(f"📍 파일 저장 위치: {save_path}", "info")
            return save_path
        else:
            self.send_log("🚨 수집된 데이터가 하나도 없습니다!", "error")
            return None


if __name__ == "__main__":
    APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    ACCOUNT = "50172151"

    dict_path = os.path.join(root_dir, "stock_dict.csv")
    
    if SystemConfig.MARKET_MODE == "DOMESTIC":
        print("📡 한국 거래소(KRX)에서 시가총액 상위 1000개 종목 명단을 다운로드합니다...")
        krx_df = fdr.StockListing('KRX')
        krx_df = krx_df[(krx_df['Market'] == 'KOSPI') | (krx_df['Market'] == 'KOSDAQ')]
        top_df = krx_df.sort_values('Marcap', ascending=False).head(1000)
        
        stock_list = top_df['Code'].tolist()
        top_df[['Code', 'Name']].to_csv(dict_path, index=False, encoding="utf-8-sig")
        
    elif SystemConfig.MARKET_MODE == "OVERSEAS":
        print("📡 미국 나스닥(NASDAQ) 상위 종목 명단을 다운로드합니다...")
        nasdaq_df = fdr.StockListing('NASDAQ')
        
        top_df = nasdaq_df.head(1000) 
        stock_list = top_df['Symbol'].tolist()
        top_df[['Symbol', 'Name']].rename(columns={'Symbol':'Code'}).to_csv(dict_path, index=False, encoding="utf-8-sig")

    print(f"✅ 명단 저장 완료! (모드: {SystemConfig.MARKET_MODE})")

    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    collector.run_collection(stock_list)