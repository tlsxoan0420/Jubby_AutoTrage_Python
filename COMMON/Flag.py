import pandas as pd

class TradeData:
    # 자동 매매 데이터 - 1. 계좌 / 표지션 데이터
    class Market:
        def __init__(self):
            # 각 컬럼에 대응하는 변수 초기화
            self.last_price = 0         # 현재가
            self.open_price = 0         # 시가
            self.high_price = 0         # 고가
            self.low_price = 0          # 저가
            self.bid_price = 0          # 매수호가
            self.ask_price = 0          # 매도호가
            self.bid_size = 0           # 매수잔량
            self.ask_size = 0           # 매도잔량
            self.volume = 0             # 거래량

            # 전체 업데이트 카운트
            self.update_count = 0

            # 데이터 표
            dtColumns =  ['현재가','시가','고가','저가','매수호가','매도호가','매수잔량','매도잔량','거래량']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '현재가': self.last_price,
                '시가': self.open_price,
                '고가': self.high_price,
                '저가': self.low_price,
                '매수호가': self.bid_price,
                '매도호가': self.ask_price,
                '매수잔량': self.bid_size,
                '매도잔량': self.ask_size,
                '거래량': self.volume
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

    # 자동 매매 데이터 - 2. 시장 / 호가 데이터
    class Account:
        def __init__(self):
            # 각 컬럼에 대응하는 변수 초기화
            self.symbol = ""           # 종목
            self.quantity = 0          # 보유수량
            self.avg_price = 0         # 평균매입가
            self.pnl = 0               # 평가손익
            self.available_cash = 0    # 주문가능금액

            # 전체 업데이트 카운트
            self.update_count = 0

            dtColumns = ['종목','보유수량','평균매입가','평가손익','주문가능금액']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '종목': self.symbol,
                '보유수량': self.quantity,
                '평균매입가': self.avg_price,
                '평가손익': self.pnl,
                '주문가능금액': self.available_cash,
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)      

    # 자동 매매 데이터 - 3. 주문 상태 데이터
    class Order:
        def __init__(self):
            # 각 컬럼에 대응하는 변수 초기화
            self.order_id = 0           # 주문번호
            self.order_type = ""        # 주문종류
            self.order_price = 0        # 주문가격
            self.order_quantity = 0     # 주문수량
            self.filled_quantity = 0    # 체결수량
            self.order_time = ""        # 주문시간
            self.status = ""            # 상태

            # 전체 업데이트 카운트
            self.update_count = 0

            dtColumns = ['주문번호','주문종류','주문가격','주문수량','체결수량','주문시간','상태']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '주문번호': self.order_id,
                '주문종류': self.order_type,
                '주문가격': self.order_price,
                '주문수량': self.order_quantity,
                '체결수량': self.filled_quantity,
                '주문시간': self.order_time,
                '상태': self.status,
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)        

    # 자동 매매 데이터 - 4. 자동 매매 알고리즘 데이터
    class Strategy:
        def __init__(self):
            # 각 컬럼에 대응하는 변수 초기화
            self.symbol = ""      # 종목
            self.ma_5 = 0         # 단기 이동평균
            self.ma_20 = 0        # 장기 이동평균
            self.rsi = 0          # RSI 지표
            self.macd = 0         # MACD 지표
            self.signal = ""      # 전략 신호 ('BUY', 'SELL', '')
            
            # 전체 업데이트 카운트
            self.update_count = 0
            
            dtColumns = ['종목','MA_5','MA_20','RSI','MACD','전략신호']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '종목': self.symbol,
                'MA_5': self.ma_5,
                'MA_20': self.ma_20,
                'RSI': self.rsi,
                'MACD': self.macd,
                '전략신호': self.signal,
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)     

    # TradeData 클래스 초기화
    def __init__(self):
        self.market = TradeData.Market()
        self.account = TradeData.Account()
        self.order = TradeData.Order()
        self.strategy = TradeData.Strategy()

# 전역 인스턴스
TradeData = TradeData()