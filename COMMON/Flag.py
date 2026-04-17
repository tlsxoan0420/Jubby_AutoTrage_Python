import pandas as pd
import random 
from datetime import datetime
import os
import sys

# =========================================================================
# 🌐 [완벽 통합] 시스템 전역 설정 및 하드코딩 탈피 자동 경로 탐색기
# =========================================================================
class SystemConfig:
    MARKET_MODE = "DOMESTIC"
    
    if getattr(sys, 'frozen', False):
        # 1. 파이썬이 EXE로 빌드되어 실행된 경우 (EXE가 있는 현재 폴더)
        PROJECT_ROOT = os.path.dirname(sys.executable)
    else:
        # 2. 스크립트로 실행된 경우 (🔥 3칸 위로 올라가야 진짜 Jubby Project가 됩니다!)
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TradeData:
    # =========================================================================
    # 📊 1. Market (시장 시세 데이터 - 차트/호가)
    # =========================================================================
    class Market:
        def __init__(self):
            self.symbol = ""            
            self.symbol_name = ""       
            self.last_price = 0         
            self.open_price = 0         
            self.high_price = 0         
            self.low_price = 0          
            self.bid_price = 0          
            self.ask_price = 0          
            self.bid_size = 0           
            self.ask_size = 0           
            self.volume = 0             
            self.update_count = 0       

            self.last_mock_price = 70000 

            # 💡 [컬럼 순서 유지] 시세 표에 표시될 데이터 순서입니다.
            dtColumns =  ['시간','종목코드','종목명','현재가','시가','고가','저가','매수호가','매도호가','매수잔량','매도잔량','거래량']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '시간': datetime.now().strftime("%H:%M:%S"),
                '종목코드' : self.symbol, '종목명' : self.symbol_name, '현재가': self.last_price,
                '시가': self.open_price, '고가': self.high_price, '저가': self.low_price,
                '매수호가': self.bid_price, '매도호가': self.ask_price, '매수잔량': self.bid_size,
                '매도잔량': self.ask_size, '거래량': self.volume
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

    # =========================================================================
    # 💼 2. Account (내 지갑/계좌 상황)
    # =========================================================================
    class Account:
        def __init__(self):
            self.update_count = 0
            # 💡 실시간 수익률 계산을 위해 '현재가' 컬럼을 추가 배치하는 것이 좋습니다.
            dtColumns = ['시간','종목코드','종목명','보유수량','평균매입가','현재가','평가손익','주문가능금액']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

    # =========================================================================
    # 🧠 3. Strategy (AI 및 보조지표 분석 현황)
    # =========================================================================
    class Strategy:
        def __init__(self):
            # ⭐ [수정] '상태메시지'를 추가하여 UI 표에 "강력 매수 신호!" 등이 보이게 합니다.
            dtColumns = ['시간','종목코드','종목명','상승확률','MA_5','MA_20','RSI','MACD','전략신호','상태메시지']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

    # =========================================================================
    # 📜 4. Order (주문 및 체결 내역) - ⚠️ 여기가 에러의 핵심!
    # =========================================================================
    class Order:
        def __init__(self):
            # ⭐ [핵심 수정] '주문번호'를 0번 자리에 배치! 
            # 이게 있어야 Ticker 창이 표에서 주문을 찾아 "체결완료"로 바꿉니다.
            dtColumns = ['주문번호', '시간', '종목코드', '종목명', '주문종류', '주문가격', '주문수량', '체결수량', '상태']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)
            
        def generate_mock_data(self):
            self.df = pd.DataFrame(columns=self.df.columns)
            now = datetime.now().strftime("%H:%M:%S")
            # 🚀 [수정] 테스트 데이터 생성 시에도 칸 수를 9개로 맞춰줍니다.
            rows = [
                {'주문번호': '000001', '시간': now, '종목코드': '005930', '종목명': '삼성전자', '주문종류': '매수(BUY)', '주문가격': '75,000', '주문수량': '10', '체결수량': '10', '상태': '체결완료'},
            ]
            self.df = pd.concat([self.df, pd.DataFrame(rows)], ignore_index=True)


    # =========================================================================
    # 📡 [데이터 번역기] JSON 변환 시 누락된 필드들을 모두 채워줍니다.
    # =========================================================================
    def market_dict(self):
        result_list = []
        for _, row in self.market.df.iterrows():
            result_list.append({
                "time": str(row.get('시간', '')),
                "symbol": str(row.get('종목코드', '')),
                "symbol_name": str(row.get('종목명', '')),
                "last_price": str(row.get('현재가', '0')),
                "open_price": str(row.get('시가', '0')),
                "high_price": str(row.get('고가', '0')),
                "low_price": str(row.get('저가', '0')),
                "bid_price": str(row.get('매수호가', '0')),
                "ask_price": str(row.get('매도호가', '0')),
                "bid_size": str(row.get('매수잔량', '0')),
                "ask_size": str(row.get('매도잔량', '0')),
                "volume": str(row.get('거래량', '0')),
                "update_count": self.market.update_count
            })
        return result_list

    def account_dict(self):
        result_list = []
        for _, row in self.account.df.iterrows():
            result_list.append({
                "time": str(row.get('시간', '')),
                "symbol": str(row.get('종목코드', '')),
                "symbol_name": str(row.get('종목명', '')),
                "quantity": str(row.get('보유수량', '0')),
                "avg_price": str(row.get('평균매입가', '0')),
                "current_price": str(row.get('현재가', '0')),
                "pnl_amt": str(row.get('평가손익금', '0')),
                "pnl_rate": str(row.get('수익률', '0.00%')),
                "status": str(row.get('상태', '')),
                "available_cash": str(row.get('주문가능금액', '0'))
            })
        return result_list

    def strategy_dict(self):
        result_list = []
        for _, row in self.strategy.df.iterrows():
            result_list.append({
                "time": str(row.get('시간', '')),
                "symbol": str(row.get('종목코드', '')),
                "symbol_name": str(row.get('종목명', '')),
                "ai_prob": str(row.get('상승확률', '0%')), 
                "ma_5": str(row.get('MA_5', '')),
                "ma_20": str(row.get('MA_20', '')),
                "rsi": str(row.get('RSI', '')),
                "macd": str(row.get('MACD', '')),
                "signal": str(row.get('전략신호', '')),
                "status_msg": str(row.get('상태메시지', '대기 중...')), # 상태메시지 전달
                "update_count": self.strategy.update_count
            })
        return result_list

    def order_dict(self):
        result_list = []
        for _, row in self.order.df.iterrows():
            result_list.append({
                # ⭐ [수정] Ticker가 검색할 수 있도록 주문번호를 반드시 포함시킵니다.
                "order_no": str(row.get('주문번호', '')), 
                "time": str(row.get('시간', '')),
                "symbol": str(row.get('종목코드', '')),
                "symbol_name": str(row.get('종목명', '')),
                "type": str(row.get('주문종류', '')),
                "price": str(row.get('주문가격', '0')),
                "quantity": str(row.get('주문수량', '0')),
                "filled_quantity": str(row.get('체결수량', '0')), # 체결수량 추가
                "status": str(row.get('상태', ''))
            })
        return result_list

    def __init__(self):
        self.market = TradeData.Market()
        self.account = TradeData.Account()
        self.order = TradeData.Order()
        self.strategy = TradeData.Strategy()

TradeData = TradeData()