import pandas as pd
import numpy as np
import joblib
import os
import sys

# 🔥 [핵심 추가] LSTM 딥러닝을 위한 PyTorch 모듈 임포트
import torch
import torch.nn as nn

# 🌐 시장 모드(DOMESTIC/OVERSEAS) 및 DB 매니저 가져오기
from COMMON.Flag import SystemConfig
from COMMON.DB_Manager import JubbyDB_Manager 

# =========================================================================
# 🛡️ [추가] LSTM 방어막(관측수) 클래스 구조 정의
# =========================================================================
class JubbyLSTM(nn.Module):
    # 🚨 [수정됨] 뇌 용량(64)과 층수(2)를 트레이너와 똑같이 맞춤
    def __init__(self, input_size, hidden_size=64, num_layers=2): 
        super(JubbyLSTM, self).__init__()
        # 🚨 [수정됨] dropout=0.2 도 똑같이 추가해줍니다.
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.2)
        self.fc = nn.Linear(hidden_size, 1)
        self.sigmoid = nn.Sigmoid()
        
    def forward(self, x):
        out, _ = self.lstm(x)
        out = self.fc(out[:, -1, :])
        return self.sigmoid(out)

class JubbyStrategy:
    """
    [주삐 메인 인공지능 (AI 전략 엔진) - 🚀 스캘핑(초단타) 머신건 모드]
    15가지 퀀트 지표(VWAP, 돌파 에너지 포함)를 계산하고, 학습된 AI 모델(앙상블+LSTM)을 통해 실시간 매수/매도를 판단합니다.
    """
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.market_return_1m = 0.0 

        # 종목명을 찾기 위한 딕셔너리 저장용 변수
        self.stock_dict = {} 
        self.db = JubbyDB_Manager()

        self.ai_model = None
        self.lstm_model = None 
        self.scaler = None # 🔥 스케일러 변수 추가
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        self.ai_model = None
        self.lstm_model = None 
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # 뇌(Model) 장착
        self.load_ai_brain()

    # =========================================================================
    # 📛 [추가] 종목명 매핑 도우미 함수들
    # =========================================================================
    def set_stock_dict(self, stock_dict):
        """ Main.py에서 넘겨주는 종목명 지도를 저장합니다. """
        self.stock_dict = stock_dict

    def get_pretty_name(self, code):
        """ 종목 코드만 보고 '이름(코드)' 형태로 예쁘게 바꿔줍니다. """
        name = self.stock_dict.get(code, "알수없음")
        return f"{name}({code})"

    # =========================================================================
    # 🧠 모드에 따라 국내/해외/해외선물 AI 뇌(PKL)를 바꿔 끼우는 함수
    # =========================================================================
    def load_ai_brain(self):
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

            # 1. 앙상블 뇌(XGBoost + LightGBM) 로드
            if os.path.exists(model_path):
                self.ai_model = joblib.load(model_path)
                msg = f"🧠 {market_icon} 맞춤형 주삐 AI 뇌({os.path.basename(model_path)}) 장착 완료! (초단타 모드)"
                self.send_log(msg, "success")
            else:
                self.ai_model = None
                msg = f"⚠️ {market_icon} AI 뇌 파일 없음!\n👉 찾는 위치: {model_path}"
                self.send_log(msg, "warning")

            # 2. 휩쏘 방어막 LSTM 관측수 뇌(.pth) 로드
            lstm_path = model_path.replace(".pkl", "_lstm.pth")
            scaler_path = model_path.replace(".pkl", "_scaler.pkl") # 🔥 스케일러 경로

            # 🔥 스케일러 파일 로드
            if os.path.exists(scaler_path):
                try:
                    self.scaler = joblib.load(scaler_path)
                except:
                    self.scaler = None

            if os.path.exists(lstm_path):
                try:
                    self.lstm_model = JubbyLSTM(input_size=18).to(self.device)
                    self.lstm_model.load_state_dict(torch.load(lstm_path, map_location=self.device))
                    self.lstm_model.eval() 
                    self.send_log(f"🛡️ [시스템] 휩쏘 방어용 LSTM 시계열 패턴 관측수({os.path.basename(lstm_path)}) 장착 완료!", "success")
                except Exception as e:
                    self.send_log(f"⚠️ LSTM 장착 실패: {e}", "warning")
                    self.lstm_model = None
            else:
                self.lstm_model = None
                
        except Exception as e:
            msg = f"🚨 AI 뇌 로드 중 에러 발생: {e}"
            self.send_log(msg, "error")
            self.ai_model = None
            self.lstm_model = None
            
    def send_log(self, msg, log_type="info"):
        if self.log_callback:
            self.log_callback(msg, log_type)
        else:
            print(msg)

    # =====================================================================
    # ⚖️ [핵심 추가] 실시간 호가창 매도/매수 잔량 비율(Orderbook Imbalance) 검사
    # =====================================================================
    def check_orderbook_imbalance(self, code):
        """ 
        [호가창 최후의 방어막] 
        매도 호가 잔량이 매수 호가 잔량보다 2배(기본값) 이상 많은지 검사하여 '가짜 돌파(휩쏘)'를 걸러냅니다.
        """
        try:
            # 메모리에 실시간으로 수집되고 있는 TradeData(UI 전송용)를 가로채서 읽어옵니다!
            from COMMON.Flag import TradeData
            market_df = TradeData.market.df
            
            if market_df is not None and not market_df.empty:
                stock_data = market_df[market_df['종목코드'] == code]
                
                if not stock_data.empty:
                    recent = stock_data.iloc[-1] # 가장 최근 찰나의 데이터
                    
                    # 콤마(,) 제거 후 숫자로 안전하게 변환
                    ask_size = float(str(recent.get('매도잔량', '0')).replace(',', ''))
                    bid_size = float(str(recent.get('매수잔량', '0')).replace(',', ''))

                    # 잔량 데이터가 모두 정상적으로 들어왔을 때만 비율 검사 진행
                    if ask_size > 0 and bid_size > 0:
                        imbalance_ratio = ask_size / bid_size
                        
                        # DB에서 설정값(배수)을 가져옵니다. 기본값은 2.0배입니다.
                        try: target_ratio = float(self.db.get_shared_setting("TRADE", "ORDERBOOK_RATIO", "2.0"))
                        except: target_ratio = 2.0

                        if imbalance_ratio >= target_ratio:
                            return True # 매도벽이 무거움 -> 진짜 상승! (통과)
                        else:
                            pretty_name = self.get_pretty_name(code)
                            self.send_log(f"🛡️ [호가창 휩쏘 방어] {pretty_name} 매도잔량 부족(비율: {imbalance_ratio:.1f}배 < {target_ratio}배). 가짜 돌파 의심되어 스킵!", "warning")
                            return False # 매수벽이 두껍거나 비율 미달 -> 개미 꼬시기 (차단)
        except Exception as e:
            pass 
        
        # 만약 통신 지연으로 호가창 데이터를 못 불러왔다면 기존 로직대로 1차 통과시킵니다.
        return True

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
            self.send_log(f"🚨 [AI 변환 실패] 누락 데이터: {missing_cols}", "error")
            return None
            
        try:
            current_data = df.iloc[-1][features].values.astype(float)
            return current_data.reshape(1, -1)
        except Exception as e:
            self.send_log(f"🚨 AI 피처 변환 에러: {e}", "error")
            return None

    def get_ai_sequence_features(self, df, seq_length=10):
        if df is None or len(df) < seq_length: return None
        
        features = [
            'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 'BB_Width', 
            'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
            'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m',
            'Disparity_60', 'Disparity_120', 'Macro_Trend'
        ]
        
        seq_df = df[features].tail(seq_length).copy()
        
        if 'Disparity_60' not in seq_df.columns: seq_df['Disparity_60'] = 100.0
        if 'Disparity_120' not in seq_df.columns: seq_df['Disparity_120'] = 100.0
        if 'Macro_Trend' not in seq_df.columns: seq_df['Macro_Trend'] = 0.0
        if 'Market_Return_1m' not in seq_df.columns:
            seq_df['Market_Return_1m'] = getattr(self, 'market_return_1m', 0.0)
            
        seq_df = seq_df.bfill().fillna(0.0)
        
        try:
            return seq_df.values.astype(float) 
        except Exception as e:
            return None

    # =====================================================================
    # 🛡️ 3. [초단타 특화 방어막] 매우 짧고 굵은 익절/손절가 세팅
    # =====================================================================
    def get_dynamic_exit_prices(self, df, avg_buy_price):
        try:
            # 🔥 [수정 1] DB에서 불러오는 기본값을 2.0% (익절), 1.5% (손절)로 상향 조절합니다.
            profit_rate = float(self.db.get_shared_setting("TRADE", "PROFIT_RATE", "2.0")) / 100.0
            stop_rate = float(self.db.get_shared_setting("TRADE", "STOP_RATE", "1.5")) / 100.0
            
            # 🔥 [추가 팁] 변동성이 클 때(ATR) 목표가도 같이 높아지도록 배수를 1.5 -> 2.0으로 올려줍니다.
            atr_target_multi = float(self.db.get_shared_setting("TRADE", "ATR_TARGET_MULTI", "2.0"))
            atr_stop_multi = float(self.db.get_shared_setting("TRADE", "ATR_STOP_MULTI", "1.0"))
        except:
            # 🔥 [수정 2] DB 연결 실패 시 백업용으로 쓰는 수치도 2.0%(0.020) / 1.5%(0.015)로 맞춰줍니다.
            profit_rate, stop_rate = 0.020, 0.015
            atr_target_multi, atr_stop_multi = 2.0, 1.0

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
    # 🚀 4. 실전 매수/매도 타점 판독 (AI 예측 + 돌파 + 호가창 이중방어)
    # =====================================================================
    def check_trade_signal(self, df, code):
        if len(df) < 26: return "WAIT"
        
        current = df.iloc[-1]
        curr_price = float(current['close']) 
        ai_prob = 0.0 
        buy_signal = False
        features = None
        
        pretty_name = self.get_pretty_name(code)
        
        # 1. AI 뇌(앙상블)의 1차 예측
        if self.ai_model is not None:
            features = self.get_ai_features(df)
            
            if features is None:
                return "WAIT"
                
            ai_prob = self.ai_model.predict_proba(features)[0][1]
            try: ai_threshold = float(self.db.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
            except: ai_threshold = 0.70
            
            if ai_prob >= ai_threshold:
                is_above_vwap = curr_price >= current.get('VWAP', curr_price)
                is_above_ma5 = curr_price >= current.get('MA5', curr_price)
                is_macd_good = current.get('MACD', 0) >= current.get('Signal_Line', 0)
                
                # 🔥 [수정됨] RSI가 40 이하로 과하게 떨어졌을 때(낙폭과대)도 예외적으로 통과시켜줌
                is_rsi_oversold = current.get('RSI', 50) <= 40.0 

                # if 조건문에 is_rsi_oversold 를 추가해 줍니다.
                if is_above_vwap or is_above_ma5 or is_macd_good or is_rsi_oversold:
                    if self.check_orderbook_imbalance(code):
                        self.send_log(f"🤖 [AI 1차 승인] {pretty_name} 떡상 징후 포착! (상승 확률: {ai_prob*100:.1f}%)", "buy")
                        buy_signal = True
                else:
                    self.send_log(f"🛡️ [AI 승인 거절] {pretty_name} 확률은 {ai_prob*100:.1f}% 이나, 추세 저항(세력선 이탈)으로 진입 포기", "warning")
       
        # 2. [전략 A & B] 아날로그 돌파/추세 매매 로직
        try:
            breakout_vol = float(self.db.get_shared_setting("TRADE", "BREAKOUT_VOL", "2.0")) 
            breakout_ret = float(self.db.get_shared_setting("TRADE", "BREAKOUT_RET", "0.5")) 
            ai_min_pass = float(self.db.get_shared_setting("AI", "MIN_PASS_RATE", "50.0")) / 100.0
        except:
            breakout_vol, breakout_ret = 2.0, 0.5
            ai_min_pass = 0.50

        if not buy_signal and current['Vol_Energy'] >= breakout_vol and curr_price > current['VWAP'] and current['return'] > breakout_ret:
            if self.ai_model is not None and ai_prob < ai_min_pass:
                self.send_log(f"💡 [전략엔진] {pretty_name} 돌파 매수를 추천이나, AI 확신도 미달({ai_prob*100:.1f}% < {ai_min_pass*100:.0f}%)로 스킵", "info")
            else:
                # 🔥 [새로운 방어막] 호가창 매도/매수 잔량 비율 검사
                if self.check_orderbook_imbalance(code):
                    self.send_log(f"🔥 [1차 승인] {pretty_name} 거래량 폭발 & 세력선(VWAP) 돌파 포착!", "buy")
                    buy_signal = True

        # =================================================================
        # 🛡️ 3. [이중 잠금장치] LSTM이 10분 차트 보고 최종 판단!
        # =================================================================
        if buy_signal:
            # 🔥 self.scaler is not None 조건이 추가되었습니다.
            if self.lstm_model is not None and self.scaler is not None and len(df) >= 10:
                seq_features = self.get_ai_sequence_features(df, seq_length=10)
                
                if seq_features is not None and len(seq_features) == 10:
                    
                    # 🚨 [핵심 버그 해결] 거대한 숫자의 실시간 차트 데이터를 0~1로 압축합니다!
                    seq_features_scaled = self.scaler.transform(seq_features)
                    
                    # 압축된 데이터를 텐서로 변환하여 모델에 입력
                    seq_tensor = torch.tensor(seq_features_scaled, dtype=torch.float32).unsqueeze(0).to(self.device)
                    
                    with torch.no_grad():
                        lstm_prob = self.lstm_model(seq_tensor).item()
                    
                    try: lstm_threshold = float(self.db.get_shared_setting("AI", "LSTM_THRESHOLD", "30.0")) / 100.0
                    except: lstm_threshold = 0.30

                    if lstm_prob < lstm_threshold:
                        self.send_log(f"🛑 [LSTM 방어막 발동] {pretty_name} 10분 시계열 패턴이 불량함 (통과율: {lstm_prob*100:.1f}%). 가짜 반등 방어!", "error")
                        buy_signal = False
                        return "WAIT"
                    else:
                        self.send_log(f"✅ [최종 승인] {pretty_name} 10분 시계열 패턴 우수! (통과율: {lstm_prob*100:.1f}%). 실전 매수 진입!", "success")

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
            self.send_log(f"💡 [전략엔진] {pretty_name} 고점 매도 폭탄(긴 윗꼬리) 차트 감지 -> 탈출 신호!", "info")
            return "SELL"
        
        return "WAIT"