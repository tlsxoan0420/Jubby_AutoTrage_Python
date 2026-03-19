import pandas as pd
import numpy as np

class JubbyStrategy:
    """
    [주삐 보조 자동매매 두뇌 (전략 엔진)]
    전통적인 기술적 분석(13가지 심화 지표)을 통해 차트를 진단합니다.
    """
    # 💡 [핵심 수정] log_callback을 받아서, 전략 엔진이 무슨 생각을 하는지 UI에 띄웁니다!
    def __init__(self, log_callback=None):
        self.log_callback = log_callback

    def send_log(self, msg, log_type="info"):
        """UI 로그창으로 직접 메시지를 쏘는 함수"""
        if self.log_callback:
            self.log_callback(msg, log_type)
        else:
            print(msg)

    # =====================================================================
    # 📊 1. [퀀트급 보조지표 13개] 계산 함수 
    # =====================================================================
    def calculate_indicators(self, df):
        if len(df) < 26: 
            return df
            
        df['return'] = df['close'].pct_change()      
        df['vol_change'] = df['volume'].pct_change() 
        
        df['MA5'] = df['close'].rolling(window=5).mean()   
        df['MA20'] = df['close'].rolling(window=20).mean() 
        
        delta = df['close'].diff()
        up = delta.clip(lower=0)       
        down = -1 * delta.clip(upper=0) 
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        rs = ema_up / ema_down
        df['RSI'] = 100 - (100 / (1 + rs)) 
        
        exp1 = df['close'].ewm(span=12, adjust=False).mean() 
        exp2 = df['close'].ewm(span=26, adjust=False).mean() 
        df['MACD'] = exp1 - exp2
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

        df.replace([np.inf, -np.inf], 0, inplace=True)
        df.fillna(0, inplace=True)
        
        return df

    # =====================================================================
    # 🎯 2. 심화 매매 신호 판별 함수 (로그 직접 출력)
    # =====================================================================
    def check_trade_signal(self, df, code="알수없음"):
        if len(df) < 26 or 'Vol_Energy' not in df.columns:
            return "HOLD"
            
        current = df.iloc[-1] 
        prev = df.iloc[-2]    
        
        # 🛒 [매수 조건] 
        is_rsi_rebound = current['RSI'] < 40 and current['RSI'] > prev['RSI']
        
        is_macd_recent_golden = False
        for i in range(1, 4):
            if len(df) >= i + 1:
                c = df.iloc[-i]        
                p = df.iloc[-(i+1)]    
                if c['MACD'] > c['Signal_Line'] and p['MACD'] <= p['Signal_Line']:
                    is_macd_recent_golden = True
                    break
        
        is_volume_spiked = current['Vol_Energy'] >= 1.5
        
        # 💡 UI 로그창으로 상세 이유를 쏴줍니다!
        if is_rsi_rebound and is_macd_recent_golden and is_volume_spiked:
            self.send_log(f"💡 [전략엔진] {code} 매수조건 충족: RSI 바닥탈출 + MACD 골든크로스 + 거래량 폭발", "buy")
            return "BUY"
            
        # 💰 [매도 조건]
        is_rsi_overbought = current['RSI'] >= 70
        is_ma_deadcross = current['MA5'] < current['MA20'] and prev['MA5'] >= prev['MA20']
        
        body_size = abs(current['open'] - current['close'])
        is_heavy_selling_pressure = current['High_Tail'] > body_size and current['High_Tail'] > 0
        
        if is_rsi_overbought:
            self.send_log(f"💡 [전략엔진] {code} 매도조건 충족: RSI 70 초과 (단기 과열)", "sell")
            return "SELL"
        elif is_ma_deadcross:
            self.send_log(f"💡 [전략엔진] {code} 매도조건 충족: 5일선/20일선 데드크로스 발생", "sell")
            return "SELL"
        elif is_heavy_selling_pressure:
            self.send_log(f"💡 [전략엔진] {code} 매도조건 충족: 윗꼬리 대량 발생 (강력한 매도 압력)", "sell")
            return "SELL"
            
        return "HOLD"

# 테스트 블록 (단독 실행용)
if __name__ == "__main__":
    brain = JubbyStrategy()
    print("전략 엔진 구조가 완벽히 업데이트되었습니다. UI 모듈에서 불러와 사용하세요.")