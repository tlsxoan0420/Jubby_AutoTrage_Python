import pandas as pd
import numpy as np
import joblib
import os
import sys

# 🌐 시장 모드(DOMESTIC/OVERSEAS) 및 DB 매니저 가져오기
from COMMON.Flag import SystemConfig
from COMMON.DB_Manager import JubbyDB_Manager 

class JubbyStrategy:
    """
    [주삐 메인 인공지능 (AI 전략 엔진) - 🚀 스캘핑(초단타) 머신건 모드]
    15가지 퀀트 지표(VWAP, 돌파 에너지 포함)를 계산하고, 학습된 AI 모델(앙상블)을 통해 실시간 매수/매도를 판단합니다.
    """
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.market_return_1m = 0.0 
        
        self.db = JubbyDB_Manager()
        
        self.ai_model = None
        self.load_ai_brain()

    # =========================================================================
    # 🧠 모드에 따라 국내/해외/해외선물 AI 뇌(PKL)를 바꿔 끼우는 함수
    # =========================================================================
    def load_ai_brain(self):
        """ 미국장인지 한국장인지 파악해서 알맞은 뇌(Model)를 머리에 끼웁니다. """
        try:
            def get_smart_path(filename):
                return os.path.join(SystemConfig.PROJECT_ROOT, filename)
            
            if SystemConfig.MARKET_MODE == "DOMESTIC":
                model_path = get_smart_path("jubby_brain.pkl")
                market_icon = "🇰🇷"
            elif SystemConfig.MARKET_MODE == "OVERSEAS":
                model_path = get_smart_path("jubby_brain_overseas.pkl")
                market_icon = "🌐"
            elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
                model_path = get_smart_path("jubby_brain_futures.pkl")
                market_icon = "🚀"
            else:
                model_path = get_smart_path("jubby_brain.pkl")
                market_icon = "❓"

            if os.path.exists(model_path):
                self.ai_model = joblib.load(model_path)
                msg = f"🧠 {market_icon} 맞춤형 주삐 AI 뇌({os.path.basename(model_path)}) 장착 완료! (초단타 모드)"
                self.send_log(msg, "success")
            else:
                self.ai_model = None
                msg = f"⚠️ {market_icon} AI 뇌 파일 없음!\n👉 찾는 위치: {model_path}"
                self.send_log(msg, "warning")
                
        except Exception as e:
            msg = f"🚨 AI 뇌 로드 중 에러 발생: {e}"
            self.send_log(msg, "error")
            self.ai_model = None
            
    def send_log(self, msg, log_type="info"):
        if self.log_callback:
            self.log_callback(msg, log_type)
        else:
            print(msg)

    # =====================================================================
    # 📊 1. [초단타 퀀트 지표] VWAP, 거래량 돌파 에너지 등 실시간 계산
    # =====================================================================
    def calculate_indicators(self, df):
        if df is None or len(df) < 26: return df
        df = df.copy() 
        
        try:
            df['return'] = df['close'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) * 100 
            
            df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
            df['TP_Volume'] = df['Typical_Price'] * df['volume']
            df['VWAP'] = df['TP_Volume'].cumsum() / (df['volume'].cumsum() + 1e-9)

            df['MA5_Vol'] = df['volume'].rolling(window=5).mean()
            df['Vol_Energy'] = df['volume'] / (df['MA5_Vol'] + 1e-9)
            df['vol_change'] = df['volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) 

            delta = df['close'].diff()
            up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13).mean() / (down.ewm(com=13).mean() + 1e-9)
            df['RSI'] = 100 - (100 / (1 + rs))
            df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
            df['Signal_Line'] = df['MACD'].ewm(span=9).mean()
            
            df['MA5'] = df['close'].rolling(5).mean()
            df['MA20'] = df['close'].rolling(20).mean()
            df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
            df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
            df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / (df['MA20'] + 1e-9)) * 100
            
            df['Disparity_5'] = (df['close'] / (df['MA5'] + 1e-9)) * 100
            df['Disparity_20'] = (df['close'] / (df['MA20'] + 1e-9)) * 100

            direction = np.where(df['close'] > df['close'].shift(1), 1, -1)
            direction = np.where(df['close'] == df['close'].shift(1), 0, direction)
            obv = (df['volume'] * direction).cumsum()
            df['OBV_Trend'] = obv.pct_change().replace([np.inf, -np.inf], 0).fillna(0)

            tr1 = df['high'] - df['low']
            tr2 = (df['high'] - df['close'].shift(1)).abs()
            tr3 = (df['low'] - df['close'].shift(1)).abs()
            df['ATR'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean()

            df['High_Tail'] = df['high'] - df[['open', 'close']].max(axis=1)
            df['Low_Tail'] = df[['open', 'close']].min(axis=1) - df['low']
            df['Buying_Pressure'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
            
            # 다중 시간대(Multi-Timeframe) 거시 추세 피처
            df['MA60'] = df['close'].rolling(60).mean()   
            df['MA120'] = df['close'].rolling(120).mean() 
            df['Disparity_60'] = (df['close'] / (df['MA60'] + 1e-9)) * 100
            df['Disparity_120'] = (df['close'] / (df['MA120'] + 1e-9)) * 100
            df['Macro_Trend'] = np.where((df['close'] > df['MA60']) & (df['MA60'] > df['MA120']), 1, 0)

            return df.fillna(0)
        except Exception as e:
            self.send_log(f"🚨 지표 계산 중 오류: {e}", "error")
            return df

    # =====================================================================
    # 🤖 2. [AI 입력용 데이터 변환기] 
    # =====================================================================
    def get_ai_features(self, df):
        if df is None or len(df) < 26: return None
        
        features = [
            'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 'BB_Width', 
            'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
            'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m',
            'Disparity_60', 'Disparity_120', 'Macro_Trend'
        ]
        
        if 'Disparity_60' not in df.columns: df['Disparity_60'] = 100.0
        if 'Disparity_120' not in df.columns: df['Disparity_120'] = 100.0
        if 'Macro_Trend' not in df.columns: df['Macro_Trend'] = 0.0
        
        if 'Market_Return_1m' not in df.columns:
            df['Market_Return_1m'] = getattr(self, 'market_return_1m', 0.0)
            
        df = df.bfill().fillna(0.0)

        missing_cols = [col for col in features if col not in df.columns]
        if missing_cols:
            self.send_log(f"🚨 [AI 변환 실패] AI가 요구한 데이터 중 다음이 누락되었습니다: {missing_cols}", "error")
            return None
            
        try:
            current_data = df.iloc[-1][features].values.astype(float)
            return current_data.reshape(1, -1)
        except Exception as e:
            self.send_log(f"🚨 AI 피처 변환 에러: {e}", "error")
            return None

    # =====================================================================
    # 🛡️ 3. [초단타 특화 방어막] 매우 짧고 굵은 익절/손절가 세팅
    # =====================================================================
    def get_dynamic_exit_prices(self, df, avg_buy_price):
        try:
            profit_rate = float(self.db.get_shared_setting("TRADE", "PROFIT_RATE", "1.2")) / 100.0
            stop_rate = float(self.db.get_shared_setting("TRADE", "STOP_RATE", "1.0")) / 100.0
            atr_target_multi = float(self.db.get_shared_setting("TRADE", "ATR_TARGET_MULTI", "1.5"))
            atr_stop_multi = float(self.db.get_shared_setting("TRADE", "ATR_STOP_MULTI", "1.0"))
        except:
            profit_rate, stop_rate = 0.012, 0.010
            atr_target_multi, atr_stop_multi = 1.5, 1.0

        if len(df) < 26 or avg_buy_price <= 0:
            return avg_buy_price * (1.0 + profit_rate), avg_buy_price * (1.0 - stop_rate)

        current = df.iloc[-1]
        atr = current['ATR']

        target_price = avg_buy_price * (1.0 + profit_rate)
        stop_price = avg_buy_price * (1.0 - stop_rate)
        
        if atr > avg_buy_price * 0.01:
            target_price = avg_buy_price + (atr * atr_target_multi)
            stop_price = avg_buy_price - (atr * atr_stop_multi)
            
        return target_price, stop_price

    # =====================================================================
    # 🚀 4. 실전 매수/매도 타점 판독 (AI 예측 + 돌파 알고리즘 결합)
    # =====================================================================
    def check_trade_signal(self, df, code):
        if len(df) < 26: return "WAIT"
        
        current = df.iloc[-1]
        curr_price = float(current['close']) 
        ai_prob = 0.0 
        buy_signal = False
        features = None
        
        # 1. AI 뇌의 예측 (확률 계산)
        if self.ai_model is not None:
            features = self.get_ai_features(df)
            
            # 🔥 [안전장치 1] 데이터 누락으로 AI 분석이 불가능하면 묻지마 매수 방지!
            if features is None:
                return "WAIT"
                
            ai_prob = self.ai_model.predict_proba(features)[0][1]
            try: ai_threshold = float(self.db.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
            except: ai_threshold = 0.70
            
            if ai_prob >= ai_threshold:
                self.send_log(f"🤖 [AI 시그널] {code} 떡상 징후 포착! (상승 확률: {ai_prob*100:.1f}%) -> 강력 매수!", "buy")
                buy_signal = True
        
        # 2. [전략 A & B] 아날로그 돌파/추세 매매 로직
        try:
            breakout_vol = float(self.db.get_shared_setting("TRADE", "BREAKOUT_VOL", "2.0")) 
            breakout_ret = float(self.db.get_shared_setting("TRADE", "BREAKOUT_RET", "0.5")) 
            # 🟢 [핵심 추가] 돌파 신호 발생 시 AI가 허락해 주는 '최소 컷트라인' DB 연동! (기본 50%)
            ai_min_pass = float(self.db.get_shared_setting("AI", "MIN_PASS_RATE", "50.0")) / 100.0
        except:
            breakout_vol, breakout_ret = 2.0, 0.5
            ai_min_pass = 0.50

        if not buy_signal and current['Vol_Energy'] >= breakout_vol and curr_price > current['VWAP'] and current['return'] > breakout_ret:
            # 🔥 [수정] 하드코딩된 0.50 대신 DB에서 가져온 ai_min_pass 변수를 사용합니다!
            if self.ai_model is not None and ai_prob < ai_min_pass:
                self.send_log(f"💡 [{code}] 전략엔진은 돌파 매수를 추천이나, AI 확신도 미달({ai_prob*100:.1f}% < {ai_min_pass*100:.0f}%)로 스킵", "info")
            else:
                self.send_log(f"🔥 [돌파 매매] {code} 거래량 폭발 & 세력선(VWAP) 돌파 포착! -> 추격 매수!", "buy")
                buy_signal = True

        if buy_signal:
            try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "강력 매수 신호 발생!")
            except: pass
            return "BUY"

        try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "탐색 및 분석 중...")
        except: pass

        # -------------------------------------------------------------
        # 💸 [매도 조건] : 초단타에 맞게 위험 신호 발생 시 즉각 던집니다.
        # -------------------------------------------------------------
        if current['MACD'] < current['Signal_Line'] and curr_price < current['MA5']:
            return "SELL"
            
        try: sell_rsi = float(self.db.get_shared_setting("TRADE", "SELL_RSI", "75.0"))
        except: sell_rsi = 75.0

        body_size = abs(current['open'] - current['close'])
        is_heavy_selling_pressure = current['High_Tail'] > body_size and current['High_Tail'] > 0
        if current['RSI'] >= sell_rsi and is_heavy_selling_pressure:
            self.send_log(f"💡 [전략엔진] {code} 고점 매도 폭탄(긴 윗꼬리) 차트 감지 -> 탈출 신호!", "sell")
            return "SELL"
        
        return "WAIT"