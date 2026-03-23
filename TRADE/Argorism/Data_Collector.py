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
        
        # 💡 시장 지수 매핑을 위한 딕셔너리 준비
        self.market_dict = {} 

        if not self.api.access_token:
            self.send_log("🚨 [경고] 토큰 발급에 실패했습니다. API Key나 모의/실전 여부를 다시 확인하세요!", "error")
        else:
            self.send_log(f"🔑 발급된 토큰 확인: {self.api.access_token[:15]}... (보안상 일부만 표시)", "info")
        
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
            
            if res.status_code == 200 and res.json().get('rt_cd') == '0':
                data = res.json().get('output2', [])
                if not data: break 
                
                df_chunk = pd.DataFrame(data)
                all_chunks.append(df_chunk)
                
                target_time = data[-1]['stck_cntg_hour'] 
                time.sleep(0.5) 
            else:
                try:
                    err_msg = res.json().get('msg1', '알 수 없는 에러')
                except:
                    err_msg = f"HTTP 상태코드 {res.status_code}"
                
                self.send_log(f"❌ [{stock_code}] 한투 서버 거절 사유: {err_msg}", "error")
                time.sleep(0.5) 
                break
            
        if not all_chunks: return None
        
        df = pd.concat(all_chunks).drop_duplicates().sort_values('stck_cntg_hour')
        df['code'] = stock_code 
        
        required_cols = ['date', 'time', 'open', 'high', 'low', 'close', 'volume']
        if len(df.columns) >= len(required_cols):
            df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume', 'acc_volume', 'extra', 'code'][:len(df.columns)]
            df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
            return df.reset_index(drop=True)
        else:
            return None

    def make_ai_dataset(self, df):
        if df is None or len(df) < 30: return None
        
        df['return'] = df['close'].pct_change() * 100 # 퍼센트로 스케일 맞춤
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

        # =========================================================================
        # 🚀 [추가된 1단계 핵심 지표]
        # =========================================================================
        # 1. 매수 압력 (Buying Pressure): 호가창 매수/매도 잔량 비율을 대체하는 실전 차트 지표
        # (종가 - 저가) / (고가 - 저가) -> 1.0에 가까울수록 누군가 멱살 잡고 끌어올린 것!
        df['Buying_Pressure'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)

        # 2. 시장 1분 등락률 매핑 (Market_Return_1m)
        # 사전에 만들어둔 market_dict에서 현재 캔들의 'time'과 일치하는 시장 수익률을 꽂아 넣음
        df['Market_Return_1m'] = df['time'].map(self.market_dict).fillna(0.0)
        # =========================================================================

        df['future_max_10'] = df['close'].rolling(window=10).max().shift(-10)
        df['future_min_10'] = df['close'].rolling(window=10).min().shift(-10)

        df['Target_Buy'] = np.where(df['future_max_10'] >= df['close'] * 1.01, 1, 0)
        df['Target_Sell'] = np.where((df['future_min_10'] <= df['close'] * 0.99) | 
                                     (df['future_max_10'] < df['close'] * 1.002), 1, 0)

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        return df.dropna().reset_index(drop=True)

    def run_collection(self, stock_list):
        # 💡 [핵심] 1000개 종목을 돌기 전에, '코스닥 150 ETF(114800)' 데이터를 먼저 싹 긁어와서 시장 지도를 만듭니다.
        self.send_log("📈 [시장 지수 맵핑] 코스닥150 ETF(114800) 데이터를 수집하여 시장 등락률 지표를 생성합니다...", "info")
        market_df = self.fetch_full_day_data('114800')
        if market_df is not None:
            market_df['Market_Return_1m'] = market_df['close'].pct_change() * 100
            # 시간을 키(Key)로, 1분 수익률을 값(Value)으로 하는 딕셔너리(지도) 생성
            self.market_dict = dict(zip(market_df['time'], market_df['Market_Return_1m'].fillna(0)))
            self.send_log("✅ 시장 지수 기준 데이터 맵핑 완료! 개별 종목 수집을 시작합니다.", "success")
        else:
            self.send_log("⚠️ 시장 지수 수집 실패. 지수 등락률 지표는 0으로 고정됩니다.", "warning")

        final_combined_data = []
        consecutive_errors = 0 
        
        self.send_log(f"📊 총 {len(stock_list)}개 종목 사냥 시작! 예상 시간 약 1.5시간~2시간", "info")
        
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
                            self.send_log(f"✅ {idx + 1}번째 종목 완료! (수집 데이터: {current_count:,}줄)", "success")
                    else:
                        consecutive_errors += 1
                else:
                    consecutive_errors += 1
                    
            except Exception as e:
                consecutive_errors += 1
                self.send_log(f"⚠️ [{code}] 사냥 실패(건너뜀): {e}", "warning")

            if consecutive_errors >= 20:
                self.send_log("🚨 [치명적 오류] 서버 거절(Bearer 등)이 20번 연속 발생했습니다. 수집망을 강제 종료합니다.", "error")
                break

        if final_combined_data:
            master_df = pd.concat(final_combined_data).reset_index(drop=True)
            save_path = os.path.join(root_dir, "AI_Ultra_Master_Train_Data_V3.csv")
            master_df.to_csv(save_path, index=False, encoding="utf-8-sig")
            
            self.send_log(f"💎 [대성공!] 총 {len(master_df):,}줄의 15가지 고급 지표 족보 완성!", "buy")
            self.send_log(f"📍 파일 저장 위치: {save_path}", "info")
            return save_path
        else:
            self.send_log("🚨 수집된 데이터가 하나도 없습니다!", "error")
            return None


if __name__ == "__main__":
    APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    ACCOUNT = "50172151"

    print("📡 한국 거래소(KRX)에서 시가총액 상위 1000개 종목 명단을 다운로드합니다...")
    krx_df = fdr.StockListing('KRX')
    
    krx_df = krx_df[(krx_df['Market'] == 'KOSPI') | (krx_df['Market'] == 'KOSDAQ')]
    top_1000_df = krx_df.sort_values('Marcap', ascending=False).head(1000)
    
    dict_path = os.path.join(root_dir, "stock_dict.csv")
    top_1000_df[['Code', 'Name']].to_csv(dict_path, index=False, encoding="utf-8-sig")
    print(f"✅ 명단 저장 완료! 실전 매매 시 이 명단을 그대로 사용합니다. ({dict_path})")

    stock_list = top_1000_df['Code'].tolist()
    
    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    collector.run_collection(stock_list)