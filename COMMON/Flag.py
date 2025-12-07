import pandas as pd

class TradeData:
    # 자동 매매 데이터 - 1. 계좌 / 표지션 데이터
    class Market:
        def __init__(self):
            # 각 컬럼에 대응하는 변수 초기화 
            self.symbol = ""            # 1. 종목코드
            self.symbol_name = ""       # 2. 종목명

            self.last_price = 0         # 3. 현재가
            self.open_price = 0         # 4. 시가
            self.high_price = 0         # 5. 고가
            self.low_price = 0          # 6. 저가
            self.bid_price = 0          # 7. 매수호가
            self.ask_price = 0          # 8. 매도호가
            self.bid_size = 0           # 9. 매수잔량
            self.ask_size = 0           # 10. 매도잔량
            self.volume = 0             # 11. 거래량

            # 전체 업데이트 카운트
            self.update_count = 0

            # 데이터 표
            dtColumns =  ['종목코드','종목명','현재가','시가','고가','저가','매수호가','매도호가','매수잔량','매도잔량','거래량']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '종목코드' : self.symbol,
                '종목명' : self.symbol_name,
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
            self.symbol = ""            # 1. 종목코드
            self.symbol_name = ""       # 2. 종목명
            self.quantity = 0           # 3. 보유수량
            self.avg_price = 0          # 4. 평균매입가
            self.pnl = 0                # 5. 평가손익
            self.available_cash = 0     # 6. 주문가능금액

            # 전체 업데이트 카운트
            self.update_count = 0

            dtColumns = ['종목코드','종목명','보유수량','평균매입가','평가손익','주문가능금액']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '종목코드': self.symbol,
                '종목명': self.symbol_name,
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
            self.symbol = ""            # 1. 종목코드
            self.symbol_name = ""       # 2. 종목명
            self.order_type = ""        # 3. 주문종류
            self.order_price = 0        # 4. 주문가격
            self.order_quantity = 0     # 5. 주문수량
            self.filled_quantity = 0    # 6. 체결수량
            self.order_time = ""        # 7. 주문시간
            self.order_status = ""      # 8. 주문상태

            # 전체 업데이트 카운트
            self.update_count = 0

            dtColumns = ['종목코드','종목명','주문종류','주문가격','주문수량','체결수량','주문시간','상태']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '종목코드': self.symbol,
                '종목명':   self.symbol_name,
                '주문종류': self.order_type,
                '주문가격': self.order_price,
                '주문수량': self.order_quantity,
                '체결수량': self.filled_quantity,
                '주문시간': self.order_time,
                '주문상태': self.order_status,
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)        

    # 자동 매매 데이터 - 4. 자동 매매 알고리즘 데이터
    class Strategy:
        def __init__(self):
            # 각 컬럼에 대응하는 변수 초기화
            self.symbol = ""            # 1. 종목코드
            self.symbol_name = ""       # 2. 종목명
            self.ma_5 = 0               # 3. 단기 이동평균
            self.ma_20 = 0              # 4. 장기 이동평균
            self.rsi = 0                # 5. RSI 지표
            self.macd = 0               # 6. MACD 지표
            self.signal = ""            # 7. 전략 신호 ('BUY', 'SELL', 'None')
            
            # 전체 업데이트 카운트
            self.update_count = 0
            
            dtColumns = ['종목코드','종목명','MA_5','MA_20','RSI','MACD','전략신호']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '종목코드': self.symbol,
                '종목명': self.symbol_name,
                'MA_5': self.ma_5,
                'MA_20': self.ma_20,
                'RSI': self.rsi,
                'MACD': self.macd,
                '전략신호': self.signal,
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)   

    def market_dict(self):
        return {
                "symbol": self.market.symbol,
                "symbol_name": self.market.symbol_name,
                "last_price": self.market.last_price,
                "last_price": self.market.last_price,
                "open_price": self.market.open_price,
                "high_price": self.market.high_price,
                "low_price": self.market.low_price,
                "bid_price": self.market.bid_price,
                "ask_price": self.market.ask_price,
                "bid_size": self.market.bid_size,
                "ask_size": self.market.ask_size,
                "volume": self.market.volume,
                "update_count": self.market.update_count
        }

    def account_dict(self):
        return {
                "symbol": self.account.symbol,
                "symbol_name": self.account.symbol_name,
                "quantity": self.account.quantity,
                "avg_price": self.account.avg_price,
                "pnl": self.account.pnl,
                "available_cash": self.account.available_cash,
                "update_count": self.account.update_count
        }

    def order_dict(self):
        return {
                "symbol": self.account.symbol,
                "symbol_name": self.account.symbol_name,
                "order_type": self.order.order_type,
                "order_price": self.order.order_price,
                "order_quantity": self.order.order_quantity,
                "filled_quantity": self.order.filled_quantity,
                "order_time": self.order.order_time,
                "order_status": self.order.order_status,
                "update_count": self.order.update_count
        }

    def strategy_dict(self):
        return {
                "symbol": self.account.symbol,
                "symbol_name": self.account.symbol_name,
                "ma_5": self.strategy.ma_5,
                "ma_20": self.strategy.ma_20,
                "rsi": self.strategy.rsi,
                "macd": self.strategy.macd,
                "signal": self.strategy.signal,
                "update_count": self.strategy.update_count
        }

    # TradeData 클래스 초기화
    def __init__(self):
        self.market = TradeData.Market()
        self.account = TradeData.Account()
        self.order = TradeData.Order()
        self.strategy = TradeData.Strategy()

# 전역 인스턴스
TradeData = TradeData()