import pandas as pd
import numpy as np

class JubbyStrategy:
    """
    [주삐 자동매매 두뇌 (전략 엔진)]
    주가 데이터(DataFrame)를 받아서 보조지표(MA, RSI, MACD)를 계산하고,
    미리 정해둔 공식에 따라 매수(BUY) / 매도(SELL) / 대기(HOLD) 신호를 판별합니다.
    """
    def __init__(self):
        pass

    # =====================================================================
    # 1. 보조지표 계산 함수 (기존과 동일)
    # =====================================================================
    def calculate_indicators(self, df):
        if len(df) < 26: 
            return df
            
        # [1] 이동평균선
        df['MA5'] = df['close'].rolling(window=5).mean()
        df['MA20'] = df['close'].rolling(window=20).mean()
        
        # [2] RSI (상대강도지수)
        delta = df['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(com=13, adjust=False).mean()
        ema_down = down.ewm(com=13, adjust=False).mean()
        rs = ema_up / ema_down
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # [3] MACD (추세 변환 판독기)
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        return df

    # =====================================================================
    # 2. 매매 신호 판별 함수 ✨ (이곳에 3초 규칙이 적용되었습니다!)
    # =====================================================================
    def check_trade_signal(self, df):
        if len(df) < 26 or 'RSI' not in df.columns:
            return "HOLD"
            
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # ----------------------------------------------------
        # 🛒 [매수 조건 (BUY)] : 너그러워진 V자 반등 룰
        # 조건 1: RSI가 40 이하에서 오르고 있는가? (바닥 찍고 고개 듦)
        # 조건 2: MACD가 최근 3번의 데이터 안에서 위로 뚫고 올라왔는가? (문 열리고 3초 룰!)
        # ----------------------------------------------------
        is_rsi_rebound = current['RSI'] < 40 and current['RSI'] > prev['RSI']
        
        # [3초 룰 검사] 최근 3개 캔들 안에서 골든크로스가 터졌는지 확인하는 로직
        is_macd_recent_golden = False
        for i in range(1, 4): # 현재(-1), 직전(-2), 그전(-3)을 차례대로 봅니다.
            if len(df) >= i + 1:
                c = df.iloc[-i]        # 그 당시의 현재
                p = df.iloc[-(i+1)]    # 그 당시의 과거
                
                # 전투기가 수송기를 뚫고 올라간 순간이 이 3번 안에 있었다면 합격!
                if c['MACD'] > c['Signal_Line'] and p['MACD'] <= p['Signal_Line']:
                    is_macd_recent_golden = True
                    break
        
        # 두 가지 조건이 모두 맞으면 매수!
        if is_rsi_rebound and is_macd_recent_golden:
            return "BUY"
            
        # ----------------------------------------------------
        # 💰 [매도 조건 (SELL)] : 칼같이 팔아야 물리지 않습니다.
        # 조건 1: RSI가 70을 넘어서 과열되었을 때
        # 조건 2: MA5가 MA20 아래로 떨어질 때 (데드크로스)
        # ----------------------------------------------------
        is_rsi_overbought = current['RSI'] >= 70
        is_ma_deadcross = current['MA5'] < current['MA20'] and prev['MA5'] >= prev['MA20']
        
        if is_rsi_overbought or is_ma_deadcross:
            return "SELL"
            
        return "HOLD"

# ==========================================
# 🧪 뇌 작동 테스트 (파일 직접 실행 시)
# ==========================================
if __name__ == "__main__":
    print("🧠 주삐 뇌(전략 알고리즘) 테스트 가동 중...\n")
    
    # 가상의 주가 폭락 -> 반등 데이터 (어제 골든크로스 발생, 오늘은 진행 중)
    prices = [
        1000, 990, 980, 950, 930, 900, 880, 850, 830, 810, 
        800, 790, 780, 770, 760, 750, 740, 730, 720, 710, 
        700, 690, 680, 670, 660, 650, # 폭락
        660, 680, 700                 # 반등 (어제 골든크로스 발생)
    ]
    
    df_mock = pd.DataFrame({"close": prices})
    brain = JubbyStrategy()
    df_analyzed = brain.calculate_indicators(df_mock)
    
    print("📊 [최근 3개 캔들 지표 분석 결과]")
    print(df_analyzed[['close', 'MA5', 'MA20', 'RSI', 'MACD', 'Signal_Line']].tail(3))
    print("-" * 50)
    
    decision = brain.check_trade_signal(df_analyzed)
    print(f"🎯 주삐의 최종 판단: {decision} !!")