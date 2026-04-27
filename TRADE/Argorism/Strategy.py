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
        self.settings_cache = {}
        self.last_settings_update = 0
        
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

    # =====================================================================
    # ⚖️ [궁극의 2차 방어막] 실시간 호가창 매도/매수 잔량 비율 검사
    # =====================================================================
    def check_orderbook_imbalance(self, code):
        try:
            row = self.db.execute_with_retry(
                self.db.shared_db_path, 
                "SELECT ask_size, bid_size FROM MarketStatus WHERE symbol = ?", 
                (code,), 
                fetch='one'
            )

            if row:
                ask_size = float(row[0])
                bid_size = float(row[1])

                # 🚀 [업그레이드 2] 텅텅 빈 호가창(사막화) 필터링! 
                # 비율이 아무리 좋아도, 호가창 잔량이 너무 적으면 시장가 매수 시 크게 손해 봅니다.
                if ask_size + bid_size < 2000: # 양쪽 합쳐서 잔량이 너무 적을 경우
                    self.send_log(f"🛡️ [2차 방어막 작동] {self.get_pretty_name(code)} 호가창이 너무 얇습니다(거래 가뭄). 휩쏘/슬리피지 위험 차단!", "warning")
                    return False

                if ask_size > 0 and bid_size > 0:
                    imbalance_ratio = ask_size / bid_size
                    
                    try: target_ratio = float(self.db.get_shared_setting("TRADE", "ORDERBOOK_RATIO", "2.0"))
                    except: target_ratio = 2.0

                    if imbalance_ratio >= target_ratio:
                        self.send_log(f"🔥 [최종 승인] {self.get_pretty_name(code)} 실시간 호가 수급 완벽! (매도벽 {imbalance_ratio:.1f}배). 🚀발사!", "success")
                        return True 
                    else:
                        self.send_log(f"🛡️ [2차 방어막 작동] {self.get_pretty_name(code)} 호가 수급 불량 (매도벽 {imbalance_ratio:.1f}배 < {target_ratio}배). 개미 꼬시기 차단!", "warning")
                        return False 
        except Exception as e:
            pass 
        
        return True
    
    def check_volume_power_and_money(self, code):
        try:
            # 주식 이름 가져오기
            pretty_name = code
            if hasattr(self, 'get_pretty_name'):
                pretty_name = self.get_pretty_name(code)
            elif hasattr(self.db, 'DYNAMIC_STOCK_DICT'):
                pretty_name = self.db.DYNAMIC_STOCK_DICT.get(code, code)

            real_vol_power = 0.0
            
            # 🚀 1. SQL(MarketStatus)에서 Ticker가 수집해둔 '진짜 체결강도'를 안전하게 가져옵니다.
            # 🔥 [DB 락 완벽 방어] 직접 conn을 열지 않고, 무조건 execute_with_retry를 사용합니다!
            try:
                # 먼저 vol_energy 컬럼으로 조회를 시도합니다.
                row = self.db.execute_with_retry(
                    self.db.shared_db_path,
                    "SELECT vol_energy FROM MarketStatus WHERE symbol = ?",
                    (code,),
                    fetch='one'
                )
            except:
                row = None
                
            # 🚀 [핵심 수정] 엉뚱한 vol_energy를 읽어와서 매수가 씹히는 현상을 막기 위해,
            # 오직 vol_power(Ticker가 저장한 순수 체결강도)만 검색하도록 코드를 단일화합니다.
            try:
                row = self.db.execute_with_retry(
                    self.db.shared_db_path,
                    "SELECT vol_power FROM MarketStatus WHERE symbol = ?",
                    (code,),
                    fetch='one'
                )
            except:
                row = None

            # SQL에서 값을 성공적으로 가져왔고, AI 가짜값(1~5)이 아닌 진짜 데이터(10.0 이상)라면 반영!
            if row and row[0] and float(row[0]) > 10.0:
                real_vol_power = float(row[0])

            # 🚀 2. 기준치 검사 (105.0 이상)
            threshold = 105.0
            
            # 만약 체결강도를 못 가져왔다면 팅기지 않고 융통성 있게 임시 통과
            if real_vol_power == 0.0:
                self.send_log(f"⚠️ [{pretty_name}] 실시간 체결강도 SQL 확인 지연. (임시 통과)", "warning")
                return True

            if real_vol_power >= threshold:
                return True
            else:
                self.send_log(f"🛡️ [3차 방어막 작동] {pretty_name} 체결강도 부족 ({real_vol_power:.1f} / 기준치: {threshold}). 가짜 반등 의심!", "warning")
                return False

        except Exception as e:
            self.send_log(f"🚨 체결강도 검사 에러: {e}", "error")
            return True

    # =====================================================================
    # 📊 1. [초단타 퀀트 지표] VWAP, 거래량 돌파 에너지 등 실시간 계산
    # =====================================================================
    def calculate_indicators(self, df):
        if df is None or len(df) < 26: return df
        df = df.copy() 
        
        try:
            df['return'] = df['close'].pct_change().replace([np.inf, -np.inf], 0).fillna(0) * 100 
            
            # 전형적 가격 (고가+저가+종가의 평균) 및 이를 활용한 거래대금(TP_Volume) 계산
            df['Typical_Price'] = (df['high'] + df['low'] + df['close']) / 3
            df['TP_Volume'] = df['Typical_Price'] * df['volume']
            
            # =====================================================================
            # 🚀 [VWAP 알고리즘 완벽 보정] 당일 전체 누적 수치 기반 진짜 세력 평단가 복원
            # =====================================================================
            # KIS_Manager에서 'total_vol'(당일 누적 거래량)과 'total_tr_pbmn'(당일 누적 거래대금)을 넘겨받았는지 확인합니다.
            if 'total_vol' in df.columns and 'total_tr_pbmn' in df.columns:
                # 1. API가 제공하는 가장 최신 시점의 '진짜 당일 전체 누적 데이터' (마지막 행 기준)
                current_total_vol = float(df['total_vol'].iloc[-1])
                current_total_val = float(df['total_tr_pbmn'].iloc[-1])
                
                # 2. 현재 차트로 불러온 120개 분봉 데이터 안에서의 총합
                recent_vol_sum = df['volume'].sum()
                recent_val_sum = df['TP_Volume'].sum()
                
                # 3. 장 초반(아침 9시 ~ 분봉 시작점)에 짤려서 누락된 과거 데이터 역산
                #    (혹시 모를 음수 에러를 막기 위해 max(0, x) 사용)
                past_vol_offset = max(0, current_total_vol - recent_vol_sum)
                past_val_offset = max(0, current_total_val - recent_val_sum)
                
                # 4. [짤려나간 과거 수치 + 현재 분봉 누적합]을 더해서 영웅문 HTS 등과 똑같은 당일 VWAP 생성!
                df['VWAP'] = (past_val_offset + df['TP_Volume'].cumsum()) / (past_vol_offset + df['volume'].cumsum() + 1e-9)
            else:
                # 만약 API 연동 실패나 과거 데이터 테스트 중일 때를 대비한 땜빵용 기존 로직 (안전망)
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
        
        # 🚀 [업그레이드 1] 1분봉이 닫히기 전이라도, 실시간 '현재가(curr_price)' 변동에 맞춰 
        # 핵심 지표들을 0.1초만에 재계산하여 AI에게 먹여줍니다. (틱 단위 반응속도 획득!)
        curr_price = float(df.iloc[-1]['close'])
        prev_close = float(df.iloc[-2]['close']) if len(df) > 1 else curr_price
        
        if prev_close > 0: df.at[df.index[-1], 'return'] = ((curr_price - prev_close) / prev_close) * 100.0
        
        ma5 = float(df.iloc[-1].get('MA5', curr_price))
        ma20 = float(df.iloc[-1].get('MA20', curr_price))
        vwap = float(df.iloc[-1].get('VWAP', curr_price))
        
        if ma5 > 0: df.at[df.index[-1], 'Disparity_5'] = (curr_price / ma5) * 100.0
        if ma20 > 0: df.at[df.index[-1], 'Disparity_20'] = (curr_price / ma20) * 100.0
        if vwap > 0: df.at[df.index[-1], 'VWAP_Disparity'] = (curr_price / vwap) * 100.0

        features = [
            'return', 'vol_change', 'RSI', 'MACD', 'BB_PctB', 'BB_Width', 
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
    def check_trade_signal(self, df, code, is_sell_mode=False):
        if len(df) < 26: return "WAIT"
        
        current = df.iloc[-1]
        curr_price = float(current['close']) 
        ai_prob = 0.0 
        buy_signal = False 
        pretty_name = self.get_pretty_name(code)

        # 🚀 [병목 완벽 해결] 10초에 한 번만 DB에서 설정값을 갱신하고 메모리(캐시)에 보관합니다!
        # 스캔 종목이 60개라면 1초에 수십~수백 번 발생하던 DB 과부하(Lock)를 원천 차단합니다.
        import time
        if time.time() - getattr(self, 'last_settings_update', 0) > 10.0:
            try:
                self.settings_cache = {
                    'sell_rsi': float(self.db.get_shared_setting("TRADE", "SELL_RSI", "75.0")),
                    'ai_threshold': float(self.db.get_shared_setting("AI", "THRESHOLD", "70.0")) / 100.0,
                    'vwap_buffer': float(self.db.get_shared_setting("TRADE", "VWAP_BUFFER_PCT", "1.0")) / 100.0,
                    'lstm_threshold': float(self.db.get_shared_setting("AI", "LSTM_THRESHOLD", "30.0")) / 100.0
                }
            except Exception:
                # DB 접속 실패 시 사용할 최후의 안전망
                self.settings_cache = {'sell_rsi': 75.0, 'ai_threshold': 0.70, 'vwap_buffer': 0.01, 'lstm_threshold': 0.30}
            self.last_settings_update = time.time()

        # 캐시에서 설정값을 0.0001초 만에 꺼내옵니다.
        sell_rsi = self.settings_cache['sell_rsi']
        ai_threshold = self.settings_cache['ai_threshold']
        vwap_buffer = self.settings_cache['vwap_buffer']
        lstm_threshold = self.settings_cache['lstm_threshold']

        # =================================================================
        # 🚨 [최우선 판단] 초단타 비상 탈출구 (매수 조건보다 무조건 먼저 검사!)
        # =================================================================
        # 1. 추세 붕괴 신호 (데드크로스 + 이평선 이탈)
        if current['MACD'] < current['Signal_Line'] and curr_price < current.get('MA5', curr_price):
            return "SELL"
            
        # 🚀 [업그레이드 3] 세력 평단가(VWAP) 강력 이탈 시 비상 탈출!
        curr_vwap = float(current.get('VWAP', curr_price))
        if is_sell_mode and curr_price < curr_vwap * 0.995: # VWAP(세력평단가) 대비 -0.5% 이탈 시
            # self.send_log(f"🚨 [긴급 탈출] {pretty_name} 세력 평단가(VWAP) 붕괴! 더 큰 하락 전 즉시 손절합니다.", "error")
            return "SELL"

        # 2. 고점 과열 및 매도 폭탄(긴 윗꼬리) 감지
        body_size = abs(current['open'] - current['close'])
        is_heavy_selling_pressure = current['High_Tail'] > body_size and current['High_Tail'] > 0
        
        # 캐시에서 가져온 sell_rsi 사용
        if current['RSI'] >= sell_rsi and is_heavy_selling_pressure:
            return "SELL"

        if is_sell_mode:
            return "WAIT"

        # -----------------------------------------------------------------
        # 🤖 [1단계] AI 모델 및 기술적 지표 1차 판독 (매수 탐색)
        # -----------------------------------------------------------------
        buy_signal = False
        ai_prob = 0.0

        if self.ai_model is not None:
            try:
                features = self.get_ai_features(df)
                if features is not None:
                    ai_prob = self.ai_model.predict_proba(features)[0][1]
                    
                    # 캐시에서 가져온 ai_threshold 사용
                    if ai_prob >= ai_threshold:
                        # 🔥 [1. VWAP 당일 세력 평단가 필터 적용 (공격적 완화 적용)]
                        curr_vwap = float(current.get('VWAP', curr_price))
                        
                        # 캐시에서 가져온 vwap_buffer를 사용하여 마지노선 계산
                        allowed_vwap = curr_vwap * (1.0 - vwap_buffer)
                        
                        if curr_price < allowed_vwap:
                            self.send_log(f"🛑 [VWAP 필터] {pretty_name} 주가가 세력 평단가 마지노선 이탈. 탈락!", "warning")
                            buy_signal = False
                        else:
                            is_above_ma5 = curr_price >= current.get('MA5', curr_price)
                            is_macd_good = current.get('MACD', 0) >= current.get('Signal_Line', 0)
                            is_rsi_oversold = current.get('RSI', 50) <= 40.0 

                            if is_above_ma5 or is_macd_good or is_rsi_oversold:
                                self.send_log(f"🤖 [AI 1차 승인] {pretty_name} 포착! (확률: {ai_prob*100:.1f}%) ➔ VWAP 지지 확인 완료!", "success")
                                buy_signal = True
                            else:
                                # 💡 왜 1차에서 탈락했는지 사유를 밝힙니다.
                                self.send_log(f"⚠️ [1차 보조지표 미달] {pretty_name} 확률({ai_prob*100:.1f}%)은 높으나 차트 지표(MA5/MACD) 불량으로 매수 포기.", "warning")
            except Exception as e:
                self.send_log(f"🚨 [1단계 연산 에러] {pretty_name} AI 판독 중 오류 발생: {e}", "error")

        # -----------------------------------------------------------------
        # 🛡️ [2단계] LSTM 시계열 패턴 방어막
        # -----------------------------------------------------------------
        if buy_signal:
            if self.lstm_model is not None and self.scaler is not None:
                if len(df) >= 10:
                    try:
                        seq_features = self.get_ai_sequence_features(df, seq_length=10)
                        if seq_features is not None and len(seq_features) == 10:
                            seq_features = np.nan_to_num(seq_features, nan=0.0) 
                            seq_features_scaled = self.scaler.transform(seq_features)
                            seq_features_scaled = np.clip(seq_features_scaled, 0.0, 1.0)
                            seq_tensor = torch.tensor(seq_features_scaled, dtype=torch.float32).unsqueeze(0).to(self.device)
                            
                            with torch.no_grad():
                                lstm_prob = self.lstm_model(seq_tensor).item()
                            
                            # 캐시에서 가져온 lstm_threshold 사용
                            if lstm_prob < lstm_threshold:
                                self.send_log(f"🛑 [LSTM 매수취소] {pretty_name} 패턴 불량 ({lstm_prob*100:.1f}%). 진입 포기!", "error")
                                buy_signal = False 
                            else:
                                self.send_log(f"✅ [2차 승인] {pretty_name} 시계열 패턴 우수 ({lstm_prob*100:.1f}%)", "success")
                        else:
                            self.send_log(f"⚠️ [LSTM 취소] {pretty_name} 시퀀스 데이터 변환 실패.", "warning")
                            buy_signal = False
                    except Exception as e:
                        self.send_log(f"🚨 [LSTM 연산 에러] {pretty_name} 분석 중 문제 발생: {e}", "error")
                        buy_signal = False 
                else:
                    self.send_log(f"⚠️ [LSTM 취소] {pretty_name} 수집된 틱 데이터가 10개 미만이라 분석 불가.", "warning")
                    buy_signal = False

        # -----------------------------------------------------------------
        # ⚖️ [3단계] 최종 관문: 실시간 호가 수급 + 체결강도 검사
        # -----------------------------------------------------------------
        if buy_signal:
            try:
                # 1. 호가창 매도/매수 잔량 비율 검사 통과 시
                if self.check_orderbook_imbalance(code):
                    # 🚀 2. 체결강도(진짜 돈이 들어오는지) 검사 통과 시 최종 진입!
                    if self.check_volume_power_and_money(code):
                        self.send_log(f"🔥 [3차 승인] {pretty_name} 수급 및 체결강도 완벽! (최종 매수 예산 확인 중...)", "success")
                        try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "🔥 매수 예산 확인 중...")
                        except Exception: pass
                        return "BUY" 
                    else:
                        buy_signal = False 
                else:
                    self.send_log(f"🛡️ [수급 불량 취소] {pretty_name} 매수 잔량 과다(개미 꼬시기). 진입 취소!", "warning")
                    buy_signal = False
            except Exception as e:
                self.send_log(f"🚨 [3단계 수급 검사 에러] {pretty_name} 호가/체결강도 확인 중 오류 발생: {e}", "error")
                buy_signal = False

        # -----------------------------------------------------------------
        # 모든 조건이 아니면 대기
        # -----------------------------------------------------------------
        try: self.db.update_realtime(code, curr_price, ai_prob * 100, "NO", "분석 및 탐색 중...")
        except Exception: pass
        
        return "WAIT"