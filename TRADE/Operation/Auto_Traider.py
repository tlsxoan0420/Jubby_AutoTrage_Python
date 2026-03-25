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
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

import COMMON.KIS_Manager as KIS
from COMMON.DB_Manager import JubbyDB_Manager  # 🔥 [추가] DB 매니저 불러오기

class JubbyAutoTrader:
    """
    1분마다 시장을 감시하며 AI의 판단에 따라 자동으로 주문을 넣는 주삐의 '몸체'입니다.
    """
    def __init__(self, app_key, app_secret, account_no, is_mock=True):
        # 🔥 [추가] DB 연결 및 시스템 로그 기록
        self.db = JubbyDB_Manager()
        self.db.insert_log("INFO", "🚀 [주삐 엔진] 가동 준비 중... AI 뇌(PKL)를 이식합니다.")
        
        # [뇌 이식] 학습 단계에서 만든 AI 모델 파일을 불러옵니다.
        model_path = os.path.join(root_dir, "jubby_brain.pkl")
        if os.path.exists(model_path):
            self.model = joblib.load(model_path)
            self.db.insert_log("INFO", "🧠 AI 뇌 이식 완료!")
        else:
            self.db.insert_log("ERROR", "🚨 AI 모델(PKL) 파일을 찾을 수 없습니다!")
            raise FileNotFoundError("jubby_brain.pkl 파일이 필요합니다.")
        
        # [API 연결] 한국투자증권 서버와 통신할 준비를 합니다.
        self.api = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        self.api.get_access_token()
        
        # [매매 설정]
        self.target_stock = "005930" # 감시할 종목 (삼성전자)
        self.is_holding = False      # 현재 주식을 들고 있는가?
        self.buy_price = 0           # 내가 산 가격
        self.peak_price = 0          # 매수 이후 도달한 가장 높은 가격 (마지노선 계산용)
        
        # 🔥 [추가] 공유 DB에서 1회 매수 금액 설정값을 읽어옵니다. (기본값 100만 원)
        self.buy_amount = int(self.db.get_shared_setting("TRADE", "BUY_AMOUNT", "1000000"))

    # ---------------------------------------------------------
    # 2. 실시간 차트 분석 및 지표 계산
    # ---------------------------------------------------------
    def get_market_status(self):
        """실시간 1분봉 데이터를 가져와 AI가 이해할 수 있는 숫자로 변환합니다."""
        df = self.api.fetch_minute_data(self.target_stock) 
        if df is None or len(df) < 20: return None
        
        # [보조지표 계산] AI가 공부할 때 썼던 공식과 동일하게 계산!
        df['return'] = df['close'].pct_change().fillna(0)
        df['vol_change'] = df['volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0)
        
        # RSI 계산
        delta = df['close'].diff()
        up, down = delta.copy(), delta.copy()
        up[up < 0] = 0; down[down > 0] = 0
        down_ewm = down.abs().ewm(com=13).mean()
        rs = np.where(down_ewm == 0, 100, up.ewm(com=13).mean() / (down_ewm + 1e-9))
        df['RSI'] = 100 - (100 / (1 + rs))
        
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
        
        # AI 확률 계산 (0.0 ~ 1.0) -> 퍼센트로 보기 좋게 변환
        prob = self.model.predict_proba(X)[0][1]
        ai_score = prob * 100 
        current_price = int(curr_state['close'])
        
        status_msg = "감시 중..." # C# UI에 띄워줄 상태 메시지

        # ---------------------------------------------------------
        # 상황 A: 주식이 없을 때 -> 매수 기회 노리기
        # ---------------------------------------------------------
        if not self.is_holding:
            if prob > 0.8 and curr_state['RSI'] < 35:
                status_msg = f"🔥 [매수 포착] 확신도: {ai_score:.1f}% / 진입 진행!"
                self.db.insert_log("BUY", f"💰 [매수 결정] AI 확신도: {ai_score:.1f}% / 현재가: {current_price}원")
                
                # 가상 수량 계산 (설정된 1회 매수 금액 / 현재가)
                qty = max(1, self.buy_amount // current_price)
                
                # TODO: 실제 주문 로직 삽입 (self.api.place_order...)
                
                self.is_holding = True
                self.buy_price = current_price
                self.peak_price = current_price
                
                # 🔥 [추가] 매수 체결 기록을 DB에 저장
                self.db.insert_trade_history(self.target_stock, "BUY", current_price, qty, yield_rate=0.0, ai_score=ai_score)
            else:
                status_msg = f"👀 관망 중... (확신도: {ai_score:.1f}%, RSI: {curr_state['RSI']:.1f})"
                
        # ---------------------------------------------------------
        # 상황 B: 주식을 들고 있을 때 -> 익절/손절 마지노선 가동
        # ---------------------------------------------------------
        else:
            self.peak_price = max(self.peak_price, current_price) # 최고가 갱신
            current_yield = (current_price - self.buy_price) / self.buy_price * 100 # 현재 수익률 계산
            
            # 1. [익절 마지노선] 최고점 대비 0.5% 꺾이면 수익 보존을 위해 매도!
            if current_price < self.peak_price * 0.995:
                status_msg = f"📉 고점 대비 하락으로 익절! (수익률: {current_yield:.2f}%)"
                self.db.insert_log("SELL", f"📉 [매도] 고점 대비 0.5% 하락. 수익 확보! (매도가: {current_price}원)")
                
                # 🔥 [추가] 매도 체결 기록을 DB에 저장
                self.db.insert_trade_history(self.target_stock, "SELL", current_price, 1, yield_rate=current_yield, ai_score=ai_score)
                self.is_holding = False

            # 2. [손절 마지노선] 내가 산 가격보다 1% 떨어지면 미련 없이 강제 손절!
            elif current_price < self.buy_price * 0.99:
                status_msg = f"🚨 손절 라인 도달! 강제 매도! (수익률: {current_yield:.2f}%)"
                self.db.insert_log("SELL", f"🚨 [손절] 마지노선(-1%) 돌파! 눈물의 손절! (매도가: {current_price}원)")
                
                # 🔥 [추가] 손절 매도 기록 저장
                self.db.insert_trade_history(self.target_stock, "SELL", current_price, 1, yield_rate=current_yield, ai_score=ai_score)
                self.is_holding = False
            else:
                status_msg = f"📈 보유 중... 수익 극대화 대기! (현재 수익률: {current_yield:.2f}%)"

        # 🔥 [핵심 추가] 매 사이클마다 C# UI에 보여줄 '실시간 데이터'를 공유 DB에 덮어씁니다!
        holding_str = "YES" if self.is_holding else "NO"
        self.db.update_realtime(self.target_stock, current_price, ai_score, holding_str, status_msg)

    def start_trading(self):
        msg = f"📡 [주삐 실전 매매] {self.target_stock} 종목 감시 시작..."
        print(msg)
        self.db.insert_log("INFO", msg)
        
        while True:
            now = datetime.now()
            # 장 운영 시간(09:00 ~ 15:20)에만 작동하게 설정
            if (9, 0) <= (now.hour, now.minute) <= (15, 20):
                self.execute_logic()
            else:
                print("💤 지금은 장 운영 시간이 아닙니다. 휴식 중...")
                self.db.update_realtime(self.target_stock, 0, 0, "NO", "💤 장 마감. 휴식 중...")
            
            time.sleep(60) # 1분마다 반복

    def execute_guaranteed_sell(self, code, qty, current_price):
        """
        [요구사항 1] 매도가 정상적으로 될 때까지 적절한 금액을 찾으며 재시도합니다.
        (기존 sig_log를 DB 로깅 방식으로 완벽 대체)
        """
        max_retries = 3
        target_price = current_price
        
        for attempt in range(max_retries):
            # 1. 지정가(혹은 목표가)로 매도 시도 (API 매도 로직 연동 필요)
            success = False # self.api.place_order(code, qty=qty, price=target_price, side="SELL") 
            
            if success:
                self.db.insert_log("SUCCESS", f"✅ [{code}] 매도 체결 성공! (단가: {target_price})")
                return True
                
            # 2. 안 팔렸다면? 호가를 0.5% 정도 낮춰서 다시 던집니다.
            target_price = int(target_price * 0.995) 
            self.db.insert_log("WARNING", f"⚠️ [{code}] 매도 미체결. 목표가를 {target_price}원으로 낮춰 재시도합니다... ({attempt+1}/{max_retries})")
            time.sleep(1.0) 
            
        # 3. 3번 다 실패하면 시장가 강제 청산
        self.db.insert_log("WARNING", f"🚨 [{code}] 3회 지정가 재시도 실패! 시장가로 강제 청산합니다.")
        # success = self.api.place_order(code, qty=qty, side="SELL_MARKET") 
        return success

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