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
    # 💡 [핵심 수정] 교과서 데이터가 19개이므로 뇌의 입력선(input_size)도 19개로 늘려야 합니다!
    def __init__(self, input_size=19, hidden_size=64, num_layers=2): 
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
                    # 💡 [핵심 수정] 여기서도 19개로 지정해 줍니다!
                    self.lstm_model = JubbyLSTM(input_size=19).to(self.device)
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

    # [Strategy.py 수정 부분]
    
    # =====================================================================
    # ⚖️ [궁극의 2차 방어막] 실시간 호가창 매도/매수 잔량 비율 검사
    # =====================================================================
    def check_orderbook_imbalance(self, code):
        """ 
        [1차 방어: LSTM 패턴]을 통과한 종목에 대해 
        [2차 방어: 실시간 수급]을 확인하여 '가짜 돌파(휩쏘)'를 완벽히 걸러냅니다.
        """
        try:
            # 💡 [핵심 수정] DB_Manager의 만능 래퍼를 사용하여 Lock 충돌을 100% 방어합니다!
            row = self.db.execute_with_retry(
                self.db.shared_db_path, 
                "SELECT ask_size, bid_size FROM MarketStatus WHERE symbol = ?", 
                (code,), 
                fetch='one'
            )

            if row:
                ask_size = float(row[0])
                bid_size = float(row[1])

                if ask_size > 0 and bid_size > 0:
                    imbalance_ratio = ask_size / bid_size
                    
                    # 목표 매도벽 비율 (기본 2.0배 - 매도 잔량이 매수 잔량보다 2배 많아야 진짜 상승)
                    try: target_ratio = float(self.db.get_shared_setting("TRADE", "ORDERBOOK_RATIO", "2.0"))
                    except: target_ratio = 2.0

                    if imbalance_ratio >= target_ratio:
                        # 🚀 [매도벽 두꺼움] 개미들이 팔고 나가는 물량을 세력이 다 받아먹으면서 올릴 준비! (찐상승)
                        self.send_log(f"🔥 [최종 승인] {self.get_pretty_name(code)} 실시간 호가 수급 완벽! (매도벽 {imbalance_ratio:.1f}배). 🚀발사!", "success")
                        return True 
                    else:
                        # 🛑 [매수벽 두꺼움] 누군가 아래에 매수 물량을 엄청 깔아두고 개미 꼬시는 중! (가짜 상승)
                        self.send_log(f"🛡️ [2차 방어막 작동] {self.get_pretty_name(code)} 호가 수급 불량 (매도벽 {imbalance_ratio:.1f}배 < {target_ratio}배). 개미 꼬시기 차단!", "warning")
                        return False 
        except Exception as e:
            pass 
        
        # 데이터 오류 시 안전을 위해 우선 통과 (1차 LSTM 방어막이 있으므로)
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

            # 💡 [알고리즘 추가 1] VWAP 이격도: 현재 주가가 오늘 하루 평균 매매가보다 얼마나 높은지/낮은지 비율
            # 100보다 크면 세력도 수익중, 100보다 작으면 세력도 물려있음을 의미함
            df['VWAP_Disparity'] = (df['close'] / (df['VWAP'] + 1e-9)) * 100

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
            df['BB_PctB'] = (df['close'] - df['BB_Lower']) / (df['BB_Upper'] - df['BB_Lower'] + 1e-9)

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
            'return', 'vol_change', 'RSI', 'MACD', 'BB_PctB', 'BB_Width', # 👈 BB_Lower를 BB_PctB로 이름 변경!
            'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
            'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m',
            'Disparity_60', 'Disparity_120', 'Macro_Trend', 'VWAP_Disparity' 
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
        
        # 💡 [핵심 수정] LSTM 뇌에 들어가는 데이터 순서도 완벽하게 똑같이 맞춰줍니다!
        features = [
            'return', 'vol_change', 'RSI', 'MACD', 'BB_PctB', 'BB_Width', # 👈 여기도 BB_Lower를 BB_PctB로 이름 변경!
            'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
            'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m',
            'Disparity_60', 'Disparity_120', 'Macro_Trend', 'VWAP_Disparity' 
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
            dynamic_stop = avg_buy_price - (atr * atr_stop_multi)
            
            # 🔥 [수정] ATR 변동성이 아무리 커도, 절대 사용자가 설정한 '기본 손절선' 밑으로 내려가지 못하게 강제 고정!
            max_loss_price = avg_buy_price * (1.0 - stop_rate) 
            stop_price = max(dynamic_stop, max_loss_price) # 둘 중 더 높은 가격(덜 잃는 가격)을 선택
            
        return target_price, stop_price
    
    # =====================================================================
    # 🚀 [최종 통합본] 실전 매수/매도 타점 판독 (AI 3중 필터 + 매도 비상 탈출)
    # =====================================================================
    # 🔥 [핵심 1] is_sell_mode=False 라는 스위치를 추가합니다.
    def check_trade_signal(self, df, code, is_sell_mode=False):
        if len(df) < 26: return "WAIT"
        
        current = df.iloc[-1]
        curr_price = float(current['close']) 
        ai_prob = 0.0 
        buy_signal = False 
        pretty_name = self.get_pretty_name(code)

        # =================================================================
        # 🚨 [최우선 판단] 초단타 비상 탈출구 (매수 조건보다 무조건 먼저 검사!)
        # 만약 차트가 박살나고 있다면, AI가 당장 사라고 해도 무조건 팔아야 합니다.
        # =================================================================
        # 1. 추세 붕괴 신호 (데드크로스 + 이평선 이탈)
        if current['MACD'] < current['Signal_Line'] and curr_price < current.get('MA5', curr_price):
            # 로그 없이 즉각 SELL 반환 (속도가 생명)
            return "SELL"
            
        # 2. 고점 과열 및 매도 폭탄(긴 윗꼬리) 감지
        try: sell_rsi = float(self.db.get_shared_setting("TRADE", "SELL_RSI", "75.0"))
        except: sell_rsi = 75.0

        body_size = abs(current['open'] - current['close'])
        # 윗꼬리가 몸통보다 길면 누군가 위에서 강하게 찍어누르고 있다는 뜻!
        is_heavy_selling_pressure = current['High_Tail'] > body_size and current['High_Tail'] > 0
        
        if current['RSI'] >= sell_rsi and is_heavy_selling_pressure:
            # 🔥 [도배 방지] 여기서 무한으로 로그를 찍지 않고 조용히 결과만 넘깁니다!
            return "SELL"

        # =================================================================
        # 🔥 [핵심 2 버그 완벽 해결] 
        # 매도 감시 일꾼이 호출한 경우, 여기까지만 (팔지 말지만) 검사하고 빠져나갑니다!
        # 이렇게 하면 무거운 AI 연산을 생략하여 컴퓨터 렉을 방지하고, 매수 로그 무한 도배를 차단합니다.
        # =================================================================
        if is_sell_mode:
            return "WAIT"

        # -----------------------------------------------------------------
        # 🤖 [1단계] AI 모델 및 기술적 지표 1차 판독 (매수 탐색)
        # -----------------------------------------------------------------
        if self.ai_model is not None:
            features = self.get_ai_features(df)
            if features is not None:
                ai_prob = self.ai_model.predict_proba(features)[0][1]
                try: ai_threshold = float(self.db.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0
                except: ai_threshold = 0.70
                
                if ai_prob >= ai_threshold:
                    is_above_vwap = curr_price >= current.get('VWAP', curr_price)
                    is_above_ma5 = curr_price >= current.get('MA5', curr_price)
                    is_macd_good = current.get('MACD', 0) >= current.get('Signal_Line', 0)
                    is_rsi_oversold = current.get('RSI', 50) <= 40.0 

                    if is_above_vwap or is_above_ma5 or is_macd_good or is_rsi_oversold:
                        self.send_log(f"🤖 [AI 1차 승인] {pretty_name} 포착! (확률: {ai_prob*100:.1f}%)", "buy")
                        buy_signal = True 

        # -----------------------------------------------------------------
        # 🛡️ [2단계] LSTM 시계열 패턴 방어막
        # -----------------------------------------------------------------
        if buy_signal:
            if self.lstm_model is not None and self.scaler is not None and len(df) >= 10:
                seq_features = self.get_ai_sequence_features(df, seq_length=10)
                if seq_features is not None and len(seq_features) == 10:
                    # 🔴 [여기를 추가하세요] 데이터 결측치(NaN)를 0으로 강제 변환
                    seq_features = np.nan_to_num(seq_features, nan=0.0) 
                    
                    # 데이터 스케일링 (transform 사용)
                    seq_features_scaled = self.scaler.transform(seq_features)
                    
                    # 🔴 [여기를 추가하세요] 값이 너무 튀지 않게 0~1 사이로 제한
                    seq_features_scaled = np.clip(seq_features_scaled, 0.0, 1.0)
                    
                    seq_tensor = torch.tensor(seq_features_scaled, dtype=torch.float32).unsqueeze(0).to(self.device)
                    
                    with torch.no_grad():
                        lstm_prob = self.lstm_model(seq_tensor).item()
                    
                    try: lstm_threshold = float(self.db.get_shared_setting("AI", "LSTM_THRESHOLD", "30.0")) / 100.0
                    except: lstm_threshold = 0.30

                    if lstm_prob < lstm_threshold:
                        self.send_log(f"🛑 [LSTM 매수취소] {pretty_name} 패턴 불량 ({lstm_prob*100:.1f}%). 진입 포기!", "error")
                        buy_signal = False 
                    else:
                        self.send_log(f"✅ [2차 승인] {pretty_name} 시계열 패턴 우수 ({lstm_prob*100:.1f}%)", "success")

        # -----------------------------------------------------------------
        # ⚖️ [3단계] 최종 관문: 실시간 호가 수급 비율 검사
        # -----------------------------------------------------------------
        if buy_signal:
            if self.check_orderbook_imbalance(code):
                self.send_log(f"🚀 [최종 승인] {pretty_name} 모든 조건 충족! 강력 매수 진입!", "success")
                try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "🔥 강력 매수 신호!")
                except: pass
                return "BUY" 
            else:
                self.send_log(f"🛡️ [수급 불량 취소] {pretty_name} 매수 잔량 과다(개미 꼬시기). 진입 취소!", "warning")
                buy_signal = False

        # -----------------------------------------------------------------
        # 모든 조건이 아니면 대기
        # -----------------------------------------------------------------
        try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "분석 및 탐색 중...")
        except: pass
        
        return "WAIT"