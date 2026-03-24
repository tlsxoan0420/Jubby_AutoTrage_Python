import pandas as pd
import numpy as np
import joblib
import os

class JubbyStrategy:
    """
    [주삐 메인 인공지능 (AI 전략 엔진)]
    15가지 퀀트 지표를 계산하고, 학습된 AI 모델(앙상블)을 통해 실시간 매수/매도를 판단합니다.
    """
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.market_return_1m = 0.0 
        
        # 🧠 1. 프로그램이 켜질 때 AI 뇌를 자동으로 불러옵니다!
        self.ai_model = None
        self.load_ai_brain()

    def load_ai_brain(self):
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            model_path = os.path.join(root_dir, "jubby_brain.pkl")
            
            if os.path.exists(model_path):
                self.ai_model = joblib.load(model_path)
                self.send_log("🧠 [전략엔진] 주삐 AI 뇌(앙상블 모델) 장착 완료! 실전 퀀트 매매를 시작합니다.", "success")
            else:
                self.send_log("⚠️ [전략엔진] AI 뇌 파일(jubby_brain.pkl)이 없습니다. 일반 지표 매매로 동작합니다.", "warning")
        except Exception as e:
            self.send_log(f"🚨 [전략엔진] AI 뇌 이식 실패: {e}", "error")

    def send_log(self, msg, log_type="info"):
        if self.log_callback:
            self.log_callback(msg, log_type)
        else:
            print(msg)

    # =====================================================================
    # 📊 1. [퀀트급 보조지표 15개] 실시간 계산 
    # =====================================================================
    def calculate_indicators(self, df):
        if len(df) < 26: 
            return df
            
        df['return'] = df['close'].pct_change() * 100     
        df['vol_change'] = df['volume'].pct_change() 
        
        df['MA5'] = df['close'].rolling(window=5).mean()   
        df['MA20'] = df['close'].rolling(window=20).mean() 
        
        delta = df['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        rs = up.ewm(com=13, adjust=False).mean() / down.ewm(com=13, adjust=False).mean()
        df['RSI'] = 100 - (100 / (1 + rs))

        df['MACD'] = df['close'].ewm(span=12, adjust=False).mean() - df['close'].ewm(span=26, adjust=False).mean()
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()

        df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
        df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / df['MA20']

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
        df['Market_Return_1m'] = self.market_return_1m

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.fillna(0, inplace=True)
        return df

    # =====================================================================
    # 🤖 2. [AI 입력용 데이터 변환기]
    # =====================================================================
    def get_ai_features(self, df):
        if len(df) == 0: return None
        features = [
            'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 'BB_Width', 
            'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
            'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m'
        ]
        current_data = df.iloc[-1][features].values.astype(float)
        return current_data.reshape(1, -1)

    # =====================================================================
    # 🛡️ 3. [동적 방어막] ATR 기반 유동적 익절/손절가 계산기
# =====================================================================
    def get_dynamic_exit_prices(self, df, avg_buy_price):
        """
        고정된 손절이 아니라, 종목의 성격(변동성)에 맞춰 손절가를 고무줄처럼 조절합니다!
        """
        if len(df) == 0 or avg_buy_price <= 0:
            # 🚨 [수정 1] ATR 계산이 안 될 때 쓰는 기본값도 넓혔습니다! (목표 +5%, 손절 -3%)
            return avg_buy_price * 1.05, avg_buy_price * 0.97 

        current = df.iloc[-1]
        atr = current['ATR']

        if pd.isna(atr) or atr == 0:
            return avg_buy_price * 1.05, avg_buy_price * 0.97
        
        # 💡 [수정 2] 곱해주는 배수를 팍! 늘렸습니다. 
        # 이제 자잘한 흔들기(개미털기)에는 콧방귀도 안 뀌고 묵직하게 버팁니다!
        target_price = avg_buy_price + (atr * 4.0)  # 기존 2.5 -> 4.0배 (길게 먹기)
        stop_price = avg_buy_price - (atr * 3.0)    # 기존 1.5 -> 3.0배 (깊게 버티기)

        return target_price, stop_price

    # =====================================================================
    # 🚀 4. 실전 매수/매도 타점 판독 (AI 예측)
    # =====================================================================
    def check_trade_signal(self, df, code):
        if len(df) < 26: return "WAIT"
        
        current = df.iloc[-1]
        
        # -------------------------------------------------------------
        # 💰 [매수 조건] : AI 뇌가 있을 경우 AI의 판단을 100% 신뢰합니다.
        # -------------------------------------------------------------
        if self.ai_model is not None:
            features = self.get_ai_features(df)
            if features is not None:
                # 앙상블 모델을 통해 주가가 상승할 확률(%)을 계산합니다.
                ai_prob = self.ai_model.predict_proba(features)[0][1]
                
                # 💡 확률이 70% 이상일 때만 매수 버튼을 누릅니다! (기준 빡빡하게)
                if ai_prob >= 0.70:
                    self.send_log(f"🤖 [AI 시그널] {code} 폭등 징후 포착! (상승 확률: {ai_prob*100:.1f}%) -> 강력 매수!", "buy")
                    return "BUY"
        else:
            # AI 뇌가 없을 경우 과거 아날로그 방식으로 동작
            prev = df.iloc[-2]
            if current['RSI'] > 30 and prev['RSI'] <= 30 and current['Vol_Energy'] >= 1.5:
                return "BUY"

        # -------------------------------------------------------------
        # 💸 [매도 조건] : 시장이 붕괴되거나 차트가 망가지면 던집니다.
        # (기본적인 1차 탈출이며, 찐 매도는 FormMain의 ATR 손절 로직이 처리합니다)
        # -------------------------------------------------------------
        is_rsi_overbought = current['RSI'] >= 75
        body_size = abs(current['open'] - current['close'])
        is_heavy_selling_pressure = current['High_Tail'] > body_size and current['High_Tail'] > 0
        
        if is_rsi_overbought and is_heavy_selling_pressure:
            self.send_log(f"💡 [전략엔진] {code} 단기 과열 및 매도 폭탄(긴 윗꼬리) 발생 -> 긴급 탈출!", "sell")
            return "SELL"
            
        return "WAIT"