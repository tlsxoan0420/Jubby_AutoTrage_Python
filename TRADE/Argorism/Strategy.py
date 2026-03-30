import pandas as pd
import numpy as np
import joblib
import os

# 🌐 시장 모드(DOMESTIC/OVERSEAS) 및 DB 매니저 가져오기
from COMMON.Flag import SystemConfig
from COMMON.DB_Manager import JubbyDB_Manager # 🔥 [DB 연동] 추가

class JubbyStrategy:
    """
    [주삐 메인 인공지능 (AI 전략 엔진) - 🚀 스캘핑(초단타) 머신건 모드]
    15가지 퀀트 지표(VWAP, 돌파 에너지 포함)를 계산하고, 학습된 AI 모델(앙상블)을 통해 실시간 매수/매도를 판단합니다.
    """
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.market_return_1m = 0.0 
        
        # 🔥 [DB 연동] DB 객체 생성
        self.db = JubbyDB_Manager()
        
        # 🧠 프로그램이 켜질 때 AI 뇌를 자동으로 불러옵니다!
        self.ai_model = None
        self.load_ai_brain()

    # =========================================================================
    # 🧠 모드에 따라 국내/해외/해외선물 AI 뇌(PKL)를 바꿔 끼우는 함수
    # =========================================================================
    def load_ai_brain(self):
        """ 미국장인지 한국장인지 파악해서 알맞은 뇌(Model)를 머리에 끼웁니다. """
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            # 🔥 모드에 따른 분기 처리!
            if SystemConfig.MARKET_MODE == "DOMESTIC":
                model_path = os.path.join(root_dir, "jubby_brain.pkl")
                market_icon = "🇰🇷"
            elif SystemConfig.MARKET_MODE == "OVERSEAS":
                model_path = os.path.join(root_dir, "jubby_brain_overseas.pkl")
                market_icon = "🌐"
            elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES":
                model_path = os.path.join(root_dir, "jubby_brain_futures.pkl")
                market_icon = "🚀"
            else:
                model_path = os.path.join(root_dir, "jubby_brain.pkl")
                market_icon = "❓"

            if os.path.exists(model_path):
                self.ai_model = joblib.load(model_path)
                msg = f"🧠 {market_icon} 맞춤형 주삐 AI 뇌({os.path.basename(model_path)}) 장착 완료! (초단타 모드)"
                self.send_log(msg, "success")
            else:
                self.ai_model = None
                msg = f"⚠️ {market_icon} 맞춤형 AI 뇌 파일이 없습니다. (Jubby AI Trainer를 먼저 돌려주세요!)"
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
        """ 실시간 1분봉 데이터를 받아 초단타에 특화된 15개 지표를 계산합니다. """
        if df is None or len(df) < 30: return df
        df = df.copy() # 원본 훼손 방지
        
        try:
            df['return'] = df['close'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) * 100 
            
            # 🌊 [전략 B] VWAP (거래량 가중 평균가 = 세력/당일 평단가) 추가
            df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
            df['TP_Volume'] = df['Typical_Price'] * df['volume']
            df['VWAP'] = df['TP_Volume'].cumsum() / (df['volume'].cumsum() + 1e-9)

            # 🚀 [전략 A] 거래량 터짐(떡상) 에너지 지표 추가
            df['MA5_Vol'] = df['volume'].rolling(window=5).mean()
            df['Vol_Energy'] = df['volume'] / (df['MA5_Vol'] + 1e-9) # 현재 거래량이 5분 평균의 몇 배인가?
            df['vol_change'] = df['volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) 

            # 기존 지표들
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
            
            df['Market_Return_1m'] = getattr(self, 'market_return_1m', 0.0)

            return df.fillna(0)
        except Exception as e:
            self.send_log(f"🚨 지표 계산 중 오류: {e}", "error")
            return df

    # =====================================================================
    # 🤖 2. [AI 입력용 데이터 변환기] (AI 뇌와 차트 지표의 톱니바퀴 맞추기)
    # =====================================================================
    def get_ai_features(self, df):
        if len(df) == 0: return None
        # 주의: 여기서 뽑아주는 15개 지표는 Trainer.py에서 학습할 때 쓴 지표와 '순서/이름'이 100% 동일해야 함
        features = [
            'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 'BB_Width', 
            'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
            'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m'
        ]
        current_data = df.iloc[-1][features].values.astype(float)
        return current_data.reshape(1, -1)

    # =====================================================================
    # 🛡️ 3. [초단타 특화 방어막] 매우 짧고 굵은 익절/손절가 세팅
    # =====================================================================
    def get_dynamic_exit_prices(self, df, avg_buy_price):
        """ 스캘핑(초단타)에 맞게 익절은 1.2%, 손절은 -1.0%로 매우 짧게 잡아 회전율을 극대화합니다. """
        
        # ✅ DB에 없으면 기존 세팅값인 1.2, 1.0, 1.5, 1.0을 DB에 자동 등록합니다!
        try:
            profit_rate = float(self.db.get_shared_setting("TRADE", "PROFIT_RATE", "1.2")) / 100.0
            stop_rate = float(self.db.get_shared_setting("TRADE", "STOP_RATE", "1.0")) / 100.0
            atr_target_multi = float(self.db.get_shared_setting("TRADE", "ATR_TARGET_MULTI", "1.5"))
            atr_stop_multi = float(self.db.get_shared_setting("TRADE", "ATR_STOP_MULTI", "1.0"))
        except:
            profit_rate, stop_rate = 0.012, 0.010
            atr_target_multi, atr_stop_multi = 1.5, 1.0

        if len(df) == 0 or avg_buy_price <= 0:
            return avg_buy_price * (1.0 + profit_rate), avg_buy_price * (1.0 - stop_rate)

        current = df.iloc[-1]
        atr = current['ATR']

        target_price = avg_buy_price * (1.0 + profit_rate)
        stop_price = avg_buy_price * (1.0 - stop_rate)
        
        # 시장 변동성(ATR)이 미쳐 날뛸 때만 위아래 폭을 살짝 넓혀줍니다.
        if atr > avg_buy_price * 0.01:
            target_price = avg_buy_price + (atr * atr_target_multi)
            stop_price = avg_buy_price - (atr * atr_stop_multi)
            
        return target_price, stop_price

    # =====================================================================
    # 🚀 4. 실전 매수/매도 타점 판독 (AI 예측 + 돌파 알고리즘 결합)
    # =====================================================================
    def check_trade_signal(self, df, code):
        """ 실시간 데이터를 보고 매수/매도할지 결정하는 가장 중요한 두뇌입니다. """
        if len(df) < 26: return "WAIT"
        
        current = df.iloc[-1]
        curr_price = float(current['close']) 
        ai_prob = 0.0 
        
        # -------------------------------------------------------------
        # 💰 [매수 조건] : AI 확률 통과 OR 확실한 거래량 돌파(스캘핑 타점)
        # -------------------------------------------------------------
        buy_signal = False
        
        # 1. AI 뇌의 예측 (확률)
        if self.ai_model is not None:
            features = self.get_ai_features(df)
            if features is not None:
                ai_prob = self.ai_model.predict_proba(features)[0][1]
                
                # ✅ AI 임계값 DB 연동
                try: ai_threshold = float(self.db.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
                except: ai_threshold = 0.70
                
                if ai_prob >= ai_threshold:
                    self.send_log(f"🤖 [AI 시그널] {code} 떡상 징후 포착! (상승 확률: {ai_prob*100:.1f}% / 기준: {ai_threshold*100:.0f}%) -> 강력 매수!", "buy")
                    buy_signal = True
        
        # 2. [전략 A & B] 아날로그 돌파/추세 매매 로직 (DB에서 기준값 로드)
        # ✅ DB에 돌파 기준값이 없으면 기존값인 거래량 2.0배, 등락률 0.5%를 등록합니다.
        try:
            breakout_vol = float(self.db.get_shared_setting("TRADE", "BREAKOUT_VOL", "2.0")) 
            breakout_ret = float(self.db.get_shared_setting("TRADE", "BREAKOUT_RET", "0.5")) 
        except:
            breakout_vol, breakout_ret = 2.0, 0.5

        # 조건: 거래량이 평균 대비 돌파 배수 이상 터지고 + 세력 평단가(VWAP) 뚫고 + 기준 % 이상 오를 때
        if not buy_signal and current['Vol_Energy'] >= breakout_vol and curr_price > current['VWAP'] and current['return'] > breakout_ret:
            self.send_log(f"🔥 [돌파 매매] {code} 거래량 폭발 & 세력선(VWAP) 돌파 포착! -> 추격 매수!", "buy")
            buy_signal = True

        if buy_signal:
            try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "강력 매수 신호 발생!")
            except: pass
            return "BUY"

        # 화면 업데이트용 데이터 전송
        try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "탐색 및 분석 중...")
        except: pass

        # -------------------------------------------------------------
        # 💸 [매도 조건] : 초단타에 맞게 위험 신호 발생 시 즉각 던집니다.
        # -------------------------------------------------------------
        # 1. 데드크로스 발생 시 무조건 칼손절 (추세 꺾임)
        if current['MACD'] < current['Signal_Line'] and curr_price < current['MA5']:
            return "SELL"
            
        # ✅ 매도 폭탄 감지를 위한 RSI 과열 기준치 DB 연동 (기존 75.0)
        try: sell_rsi = float(self.db.get_shared_setting("TRADE", "SELL_RSI", "75.0"))
        except: sell_rsi = 75.0

        # 2. 거래량이 말라버린 채로 긴 윗꼬리를 달고 내려꽂을 때 (매도 폭탄)
        body_size = abs(current['open'] - current['close'])
        is_heavy_selling_pressure = current['High_Tail'] > body_size and current['High_Tail'] > 0
        if current['RSI'] >= sell_rsi and is_heavy_selling_pressure:
            # 💡 텍스트를 스캔/보유 상황 모두 어울리게 변경합니다.
            self.send_log(f"💡 [전략엔진] {code} 고점 매도 폭탄(긴 윗꼬리) 차트 감지 -> 매수 차단 및 탈출 신호!", "sell")
            return "SELL"
        
        return "WAIT"