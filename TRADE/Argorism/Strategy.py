import pandas as pd
import numpy as np
import joblib
import os

# 🌐 시장 모드(DOMESTIC/OVERSEAS) 및 DB 매니저 가져오기
from COMMON.Flag import SystemConfig
from COMMON.DB_Manager import JubbyDB_Manager # 🔥 [DB 연동] 추가

class JubbyStrategy:
    """
    [주삐 메인 인공지능 (AI 전략 엔진)]
    15가지 퀀트 지표를 계산하고, 학습된 AI 모델(앙상블)을 통해 실시간 매수/매도를 판단합니다.
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
    # 🧠 [핵심 수정] 모드에 따라 국내용/해외용 AI 뇌(PKL)를 바꿔 끼우는 함수
    # =========================================================================
    def load_ai_brain(self):
        """ 미국장인지 한국장인지 파악해서 알맞은 뇌(Model)를 머리에 끼웁니다. """
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            # 현재 선택된 시장 모드를 확인합니다.
            if SystemConfig.MARKET_MODE == "DOMESTIC":
                model_name = "jubby_brain.pkl"
                market_title = "🇰🇷 국내 주식"
            else:
                model_name = "jubby_brain_overseas.pkl"
                market_title = "🌐 미국(해외) 주식"
                
            model_path = os.path.join(root_dir, model_name)
            
            if os.path.exists(model_path):
                self.ai_model = joblib.load(model_path)
                self.send_log(f"🧠 [전략엔진] {market_title} 특화 주삐 AI 뇌({model_name}) 장착 완료! 실전 퀀트 매매를 시작합니다.", "success")
            else:
                self.ai_model = None # 파일이 없으면 기존 모델 비우기
                self.send_log(f"⚠️ [전략엔진] {market_title} 전용 AI 뇌 파일({model_name})이 없습니다. 우선 일반 지표 매매로 동작합니다.", "warning")
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
        """ 가져온 차트 데이터에 보조지표 선들을 쭉쭉 긋는 작업입니다. """
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
        """ 15개의 지표만 쏙 뽑아서 AI에게 먹여줄 모양으로 압축합니다. """
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
        """ 종목의 변동성(ATR)과 사용자가 지정한 배수를 결합해 완벽한 탈출선을 긋습니다. """
        if len(df) == 0 or avg_buy_price <= 0:
            return avg_buy_price * 1.05, avg_buy_price * 0.97 

        current = df.iloc[-1]
        atr = current['ATR']

        if pd.isna(atr) or atr == 0:
            return avg_buy_price * 1.05, avg_buy_price * 0.97
        
        # 🔥 [핵심 연동] C# UI에서 사용자가 설정한 배수(Multiplier)를 실시간으로 가져옵니다!
        try:
            atr_tp = float(self.db.get_shared_setting("TRADE", "ATR_TP_MULT", "4.0"))
            atr_sl = float(self.db.get_shared_setting("TRADE", "ATR_SL_MULT", "3.0"))
        except:
            atr_tp, atr_sl = 4.0, 3.0 # DB를 읽지 못하면 기본 방어막 전개
        
        target_price = avg_buy_price + (atr * atr_tp)  
        stop_price = avg_buy_price - (atr * atr_sl)    

        return target_price, stop_price

    # =====================================================================
    # 🚀 4. 실전 매수/매도 타점 판독 (AI 예측)
    # =====================================================================
    def check_trade_signal(self, df, code):
        """ 실시간 데이터를 보고 매수/매도할지 결정하는 가장 중요한 두뇌입니다. """
        if len(df) < 26: return "WAIT"
        
        current = df.iloc[-1]
        
        # [버그 수정 1] int로 변환하면 해외(미국) 주식의 소수점이 다 날아가서 계산이 망가집니다! float 유지!
        curr_price = float(current['close']) 
        ai_prob = 0.0 # [치명적 버그 수정] 에러가 나지 않도록 확률 초기값을 0으로 잡아둡니다.
        
        # -------------------------------------------------------------
        # 💰 [매수 조건] : AI 뇌가 있을 경우 AI의 판단을 100% 신뢰합니다.
        # -------------------------------------------------------------
        if self.ai_model is not None:
            features = self.get_ai_features(df)
            if features is not None:
                # 앙상블 모델을 통해 주가가 상승할 확률(%)을 계산합니다.
                ai_prob = self.ai_model.predict_proba(features)[0][1]
                
                # 🔥 [핵심 연동] 사용자가 설정한 'AI 확신도 기준점'을 DB에서 읽어옵니다. (없으면 70% 기본값)
                try: 
                    ai_threshold = float(self.db.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
                except: 
                    ai_threshold = 0.70
                
                # 💡 DB에서 가져온 기준 확률 이상일 때만 매수 버튼을 누릅니다!
                if ai_prob >= ai_threshold:
                    self.send_log(f"🤖 [AI 시그널] {code} 떡상 징후 포착! (상승 확률: {ai_prob*100:.1f}% / 기준: {ai_threshold*100:.0f}%) -> 강력 매수!", "buy")
                    
                    # 🔥 [치명적 버그 수정 2] 리턴(return)해버리면 밑에 있는 DB 업데이트 코드를 영원히 실행하지 못합니다!
                    # DB에 먼저 알리고 나서 리턴해야 합니다.
                    try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "AI 강력 매수 신호 발생!")
                    except: pass
                    
                    return "BUY"
        else:
            # AI 뇌가 없을 경우 과거 아날로그 방식으로 동작
            prev = df.iloc[-2]
            if current['RSI'] > 30 and prev['RSI'] <= 30 and current['Vol_Energy'] >= 1.5:
                return "BUY"

        # 🔥 C# 메인 감시판 업데이트용 데이터 전송
        # (ai_prob가 0으로 세팅되어 있으므로 NameError 없이 무사히 통과합니다!)
        try:
            self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "AI 뇌 풀가동 분석 중...")
        except:
            pass

        # -------------------------------------------------------------
        # 💸 [매도 조건] : 시장이 붕괴되거나 차트가 망가지면 던집니다.
        # -------------------------------------------------------------
        is_rsi_overbought = current['RSI'] >= 75
        body_size = abs(current['open'] - current['close'])
        is_heavy_selling_pressure = current['High_Tail'] > body_size and current['High_Tail'] > 0
        
        if is_rsi_overbought and is_heavy_selling_pressure:
            self.send_log(f"💡 [전략엔진] {code} 단기 과열 및 매도 폭탄(긴 윗꼬리) 발생 -> 긴급 탈출!", "sell")
            return "SELL"
            
        return "WAIT"