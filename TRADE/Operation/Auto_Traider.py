import os
import sys
import time
import pandas as pd
import numpy as np
import joblib
from datetime import datetime

# ---------------------------------------------------------------------
# 1. [경로 설정] 두 단계 위(최상위 폴더)로 올라가서 필요한 파일들을 찾습니다.
# ---------------------------------------------------------------------
# 현재 파일: TRADE/Operation/Auto_Traider.py
# 1단계 위: TRADE
# 2단계 위: Jubby_AutoTrage_Python (최상위)
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

import COMMON.KIS_Manager as KIS

class JubbyAutoTrader:
    """
    1분마다 시장을 감시하며 AI의 판단에 따라 자동으로 주문을 넣는 주삐의 '몸체'입니다.
    """
    def __init__(self, app_key, app_secret, account_no, is_mock=True):
        print("🚀 [주삐 엔진] 가동 준비 중... AI 뇌(PKL)를 이식합니다.")
        
        # [뇌 이식] 학습 단계에서 만든 AI 모델 파일을 불러옵니다.
        model_path = os.path.join(root_dir, "jubby_brain.pkl")
        self.model = joblib.load(model_path)
        
        # [API 연결] 한국투자증권 서버와 통신할 준비를 합니다.
        self.api = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        self.api.get_access_token()
        
        # [매매 설정]
        self.target_stock = "005930" # 감시할 종목 (삼성전자)
        self.is_holding = False      # 현재 주식을 들고 있는가?
        self.buy_price = 0           # 내가 산 가격
        self.peak_price = 0          # 매수 이후 도달한 가장 높은 가격 (마지노선 계산용)

    # ---------------------------------------------------------
    # 2. 실시간 차트 분석 및 지표 계산
    # ---------------------------------------------------------
    def get_market_status(self):
        """실시간 1분봉 데이터를 가져와 AI가 이해할 수 있는 숫자로 변환합니다."""
        # KIS_Manager를 통해 최근 차트 데이터를 가져옵니다.
        df = self.api.fetch_minute_data(self.target_stock) 
        
        if df is None or len(df) < 20: return None
        
        # [보조지표 계산] AI가 공부할 때 썼던 공식과 '완벽하게 동일'해야 합니다!
        df['return'] = df['close'].pct_change()
        df['vol_change'] = df['volume'].pct_change()
        
        # RSI 계산
        delta = df['close'].diff()
        up, down = delta.copy(), delta.copy()
        up[up < 0] = 0; down[down > 0] = 0
        df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.abs().ewm(com=13).mean())))
        
        # MACD & 볼린저 밴드
        df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        df['MA20'] = df['close'].rolling(20).mean()
        df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
        
        return df.iloc[-1] # 가장 최신(현재 1분) 데이터만 반환

    # ---------------------------------------------------------
    # 3. 매매 판단 로직 (AI 판독 + 마지노선 감시)
    # ---------------------------------------------------------
    def execute_logic(self):
        curr_state = self.get_market_status()
        if curr_state is None: return

        # AI에게 물어볼 준비 (특징 데이터 추출)
        features = ['return', 'vol_change', 'RSI', 'MACD', 'BB_Lower']
        X = curr_state[features].values.reshape(1, -1)
        
        # AI가 "지금 사면 오를 확률"을 계산합니다 (0.0 ~ 1.0)
        prob = self.model.predict_proba(X)[0][1]

        # ---------------------------------------------------------
        # 상황 A: 주식이 없을 때 -> 매수 기회 노리기
        # ---------------------------------------------------------
        if not self.is_holding:
            # ✨ [신중함 필터] AI 확신이 80% 이상이고, RSI가 바닥(35 미만)일 때만 매수!
            if prob > 0.8 and curr_state['RSI'] < 35:
                print(f"💰 [매수 결정] 확신도: {prob:.2f} / 현재가: {curr_state['close']}원")
                # 실제로 주문을 넣습니다 (KIS_Manager에 구현 필요)
                # self.api.place_order(self.target_stock, qty=1, side="BUY")
                
                self.is_holding = True
                self.buy_price = curr_state['close']
                self.peak_price = curr_state['close']
        
        # ---------------------------------------------------------
        # 상황 B: 주식을 들고 있을 때 -> 익절/손절 마지노선 가동
        # ---------------------------------------------------------
        else:
            current_price = curr_state['close']
            self.peak_price = max(self.peak_price, current_price) # 최고가 갱신
            
            # 1. [익절 마지노선] 최고점 대비 0.5% 꺾이면 수익 보존을 위해 매도!
            if current_price < self.peak_price * 0.995:
                print(f"📉 [매도] 고점 대비 0.5% 하락! 수익 확보. 매도가: {current_price}")
                # self.api.place_order(self.target_stock, qty=1, side="SELL")
                self.is_holding = False

            # 2. [손절 마지노선] 내가 산 가격보다 1% 떨어지면 미련 없이 매도!
            elif current_price < self.buy_price * 0.99:
                print(f"🚨 [매도] 손절 마지노선(-1%) 돌파! 매도가: {current_price}")
                # self.api.place_order(self.target_stock, qty=1, side="SELL")
                self.is_holding = False

    def start_trading(self):
        print(f"📡 [주삐 실전 매매] {self.target_stock} 종목 감시 시작...")
        while True:
            now = datetime.now()
            # 장 운영 시간(09:00 ~ 15:20)에만 작동하게 설정 (나중에 더 정밀하게 수정 가능)
            if (9, 0) <= (now.hour, now.minute) <= (15, 20):
                self.execute_logic()
            else:
                print("💤 지금은 장 운영 시간이 아닙니다. 휴식 중...")
            
            time.sleep(60) # 1분마다 반복

# ---------------------------------------------------------------------
# 🚀 실행부
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # 본인의 API 키 정보
    APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    ACCOUNT = "50172151"
    
    trader = JubbyAutoTrader(APP_KEY, APP_SECRET, ACCOUNT, is_mock=True)
    trader.start_trading()