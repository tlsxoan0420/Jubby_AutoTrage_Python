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
    # 🧠 [핵심 수정] 모드에 따라 국내/해외/해외선물 AI 뇌(PKL)를 바꿔 끼우는 함수
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
                msg = f"🧠 {market_icon} 맞춤형 주삐 AI 뇌({os.path.basename(model_path)}) 장착 완료!"
                if self.log_callback: self.log_callback(msg, "success")
                else: print(msg)
            else:
                self.ai_model = None
                msg = f"⚠️ {market_icon} 맞춤형 AI 뇌 파일이 없습니다. (Jubby AI Trainer를 먼저 돌려주세요!)"
                if self.log_callback: self.log_callback(msg, "warning")
                else: print(msg)
                
        except Exception as e:
            msg = f"🚨 AI 뇌 로드 중 에러 발생: {e}"
            if self.log_callback: self.log_callback(msg, "error")
            else: print(msg)
            self.ai_model = None
            
    def send_log(self, msg, log_type="info"):
        if self.log_callback:
            self.log_callback(msg, log_type)
        else:
            print(msg)

    # =====================================================================
    # 📊 1. [퀀트급 보조지표 15개] 실시간 계산 
    # =====================================================================
    def calculate_indicators(self, df):
        """ 실시간 1분봉 데이터를 받아 15개의 고급 AI 보조지표를 계산합니다. """
        if df is None or len(df) < 30: return df
        
        try:
            df['return'] = df['close'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) * 100 
            df['vol_change'] = df['volume'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) 

            delta = df['close'].diff()
            up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
            rs = up.ewm(com=13).mean() / (down.ewm(com=13).mean() + 1e-9)
            df['RSI'] = 100 - (100 / (1 + rs))
            
            df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
            df['Signal_Line'] = df['MACD'].ewm(span=9).mean() # 매도 시그널용
            
            # 🔥 [복원] 누락되었던 5가지 고급 지표 실시간 계산 로직 추가!
            df['MA5'] = df['close'].rolling(5).mean()
            df['MA20'] = df['close'].rolling(20).mean()
            
            df['BB_Upper'] = df['MA20'] + (df['close'].rolling(20).std() * 2)
            df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
            df['BB_Width'] = ((df['BB_Upper'] - df['BB_Lower']) / df['MA20']) * 100
            
            df['Disparity_5'] = (df['close'] / df['MA5']) * 100
            df['Disparity_20'] = (df['close'] / df['MA20']) * 100

            df['Vol_Energy'] = df['volume'] / (df['volume'].rolling(20).mean() + 1e-9)

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
            
            # 실시간 시장 대장주(지수)의 1분 등락률을 꽂아줍니다 (FormMain에서 주입됨)
            df['Market_Return_1m'] = getattr(self, 'market_return_1m', 0.0)

            return df.fillna(0)
        except Exception as e:
            if self.log_callback: self.log_callback(f"🚨 지표 계산 중 오류: {e}", "error")
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