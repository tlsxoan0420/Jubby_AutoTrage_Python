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

class UltraDataCollector:
    def __init__(self, app_key, app_secret, account_no, is_mock=True, log_callback=None):
        self.log_callback = log_callback
        self.send_log("🔥 [주삐 울트라 컬렉터] 시스템 가동! 시가총액 상위 1000대 종목 사냥을 준비합니다.", "success")
        
        self.api = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        self.api.get_access_token()
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"

    def send_log(self, msg, log_type="info"):
        if self.log_callback:
            self.log_callback(msg, log_type)
        else:
            print(msg) 

    def fetch_full_day_data(self, stock_code):
        all_chunks = []
        target_time = "153000" 

        for i in range(15):
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {self.api.access_token}",
                "appKey": self.api.app_key,
                "appSecret": self.api.app_secret,
                "tr_id": "FHKST03010200", 
                "custtype": "P"
            }
            params = {
                "FID_ETC_CLS_CODE": "", 
                "FID_COND_MRKT_DIV_CODE": "J", 
                "FID_INPUT_ISCD": stock_code,  
                "FID_INPUT_HOUR_1": target_time, 
                "FID_PW_DATA_INCU_YN": "Y"  
            }
            
            res = requests.get(url, headers=headers, params=params)
            
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                data = res.json()['output2']
                if not data: break 
                
                df_chunk = pd.DataFrame(data)
                all_chunks.append(df_chunk)
                
                target_time = data[-1]['stck_cntg_hour'] 
                time.sleep(0.5) 
            else:
                self.send_log(f"❌ [{stock_code}] 수집 중 서버 에러 발생. 건너뜁니다.", "error")
                break
            
        if not all_chunks: return None
        
        df = pd.concat(all_chunks).drop_duplicates().sort_values('stck_cntg_hour')
        df['code'] = stock_code 
        
        df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume', 'acc_volume', 'extra', 'code'][:len(df.columns)]
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        
        return df.reset_index(drop=True)

    def make_ai_dataset(self, df):
        if df is None or len(df) < 30: return None
        
        df['return'] = df['close'].pct_change() 
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

        df['future_max_10'] = df['close'].rolling(window=10).max().shift(-10)
        df['future_min_10'] = df['close'].rolling(window=10).min().shift(-10)

        df['Target_Buy'] = np.where(df['future_max_10'] >= df['close'] * 1.01, 1, 0)
        df['Target_Sell'] = np.where((df['future_min_10'] <= df['close'] * 0.99) | 
                                     (df['future_max_10'] < df['close'] * 1.002), 1, 0)

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return df.dropna().reset_index(drop=True)

    def run_collection(self, stock_list):
        final_combined_data = []
        # 1000개 수집은 시간이 꽤 걸리므로 미리 알려줍니다.
        self.send_log(f"📊 총 {len(stock_list)}개 종목 사냥 시작! 예상 시간 약 1.5시간~2시간", "info")
        
        for idx, code in enumerate(stock_list):
            try:
                raw = self.fetch_full_day_data(code)
                if raw is not None:
                    processed = self.make_ai_dataset(raw)
                    if processed is not None:
                        final_combined_data.append(processed)
                        
                        if (idx + 1) % 10 == 0:
                            current_count = sum(len(d) for d in final_combined_data)
                            self.send_log(f"✅ {idx + 1}번째 종목 완료! (수집 데이터: {current_count:,}줄)", "success")
            except Exception as e:
                self.send_log(f"⚠️ [{code}] 사냥 실패(건너뜀): {e}", "warning")
                continue

        if final_combined_data:
            master_df = pd.concat(final_combined_data).reset_index(drop=True)
            save_path = os.path.join(root_dir, "AI_Ultra_Master_Train_Data_V3.csv")
            master_df.to_csv(save_path, index=False, encoding="utf-8-sig")
            
            self.send_log(f"💎 [대성공!] 총 {len(master_df):,}줄의 1000종목 거대 족보 완성!", "buy")
            self.send_log(f"📍 파일 저장 위치: {save_path}", "info")
            return save_path
        else:
            self.send_log("🚨 수집된 데이터가 하나도 없습니다!", "error")
            return None


if __name__ == "__main__":
    APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    ACCOUNT = "50172151"

    # 💡 [핵심] 수동 하드코딩 제거! 시총 상위 1000개 종목을 자동으로 긁어옵니다.
    print("📡 한국 거래소(KRX)에서 시가총액 상위 1000개 종목 명단을 다운로드합니다...")
    krx_df = fdr.StockListing('KRX')
    
    # 스팩, 리츠 등 이상한 주식 제외하고 진짜 주식만 필터링 후 1000개 추출
    krx_df = krx_df[(krx_df['Market'] == 'KOSPI') | (krx_df['Market'] == 'KOSDAQ')]
    top_1000_df = krx_df.sort_values('Marcap', ascending=False).head(1000)
    
    # 💡 [매우 중요] FormMain.py가 나중에 읽어볼 수 있도록 사전(Dictionary) 파일로 저장해둡니다!
    dict_path = os.path.join(root_dir, "stock_dict.csv")
    top_1000_df[['Code', 'Name']].to_csv(dict_path, index=False, encoding="utf-8-sig")
    print(f"✅ 명단 저장 완료! 실전 매매 시 이 명단을 그대로 사용합니다. ({dict_path})")

    # 추출한 1000개 종목 코드를 리스트로 변환하여 수집기에 던져줍니다.
    stock_list = top_1000_df['Code'].tolist()
    
    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    collector.run_collection(stock_list)