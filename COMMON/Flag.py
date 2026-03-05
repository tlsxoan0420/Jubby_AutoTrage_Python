import pandas as pd
import random # 🎲 주사위를 굴려 랜덤 숫자를 만드는 도구입니다.

class TradeData:
    # =========================================================================
    # 📊 1. Market (시장 시세 데이터 - 그래프를 그리는 핵심 소스)
    # =========================================================================
    class Market:
        def __init__(self):
            # [변수 보관함]
            self.symbol = ""            # 종목코드 (예: 005930)
            self.symbol_name = ""       # 종목명 (예: 삼성전자)
            self.last_price = 0         # 현재가
            self.open_price = 0         # 시가
            self.high_price = 0         # 고가
            self.low_price = 0          # 저가
            self.bid_price = 0          # 매수호가
            self.ask_price = 0          # 매도호가
            self.bid_size = 0           # 매수잔량
            self.ask_size = 0           # 매도잔량
            self.volume = 0             # 거래량
            self.update_count = 0       # 데이터가 몇 번 바뀌었는지 세는 카운터

            # ✨ [핵심 추가] 이전 가격을 기억하는 '기억장치'입니다.
            # 이 값이 있어야 "다음 가격은 이전 가격에서 조금만 변해라"라고 시킬 수 있습니다.
            # 이게 없으면 그래프가 널뛰기를 해서 1번처럼 그려집니다.
            self.last_mock_price = 70000 

            # [표 설계도] C# UI의 기둥 이름과 똑같이 한글로 만듭니다.
            dtColumns =  ['종목코드','종목명','현재가','시가','고가','저가','매수호가','매도호가','매수잔량','매도잔량','거래량']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            """현재 보관함에 있는 값들을 표(df)의 맨 아랫줄에 한 줄 추가합니다."""
            new_row = {
                '종목코드' : self.symbol, '종목명' : self.symbol_name, '현재가': self.last_price,
                '시가': self.open_price, '고가': self.high_price, '저가': self.low_price,
                '매수호가': self.bid_price, '매도호가': self.ask_price, '매수잔량': self.bid_size,
                '매도잔량': self.ask_size, '거래량': self.volume
            }
            # 기존 표 아래에 새 줄을 붙입니다.
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

        # 🎲 [데이터 생성 테스트용 마법 지팡이]
        def generate_mock_data(self):
            """버튼 누를 때마다 10개의 '서로 다른 종목'의 데이터를 누적 생성합니다."""
            # 전송용 데이터프레임을 초기화합니다 (새로 만든 10개만 보냅니다)
            self.df = pd.DataFrame(columns=self.df.columns) 

            # 테스트용 우량주 10선
            mock_stocks = [
                ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("035420", "NAVER"),
                ("035720", "카카오"), ("005380", "현대차"), ("000270", "기아"),
                ("068270", "셀트리온"), ("005490", "POSCO홀딩스"), ("051910", "LG화학"), ("000100", "유한양행")
            ]
            
            for i in range(10):
                code, name = mock_stocks[i]
                
                # 각 종목마다 이전 가격을 다르게 관리하면 좋겠지만, 
                # 테스트를 위해 현재가를 랜덤하게 생성하고 부드럽게 움직이는 로직을 씁니다.
                change = random.randint(-300, 310)
                self.last_mock_price += change # (참고: 실제론 종목별 last_price 보관이 필요함)
                
                price = self.last_mock_price
                self.symbol = code
                self.symbol_name = name
                
                self.last_price = price
                self.open_price = price - random.randint(-50, 50)
                self.high_price = max(self.last_price, self.open_price) + random.randint(0, 100)
                self.low_price = min(self.last_price, self.open_price) - random.randint(0, 100)
                
                self.bid_price = price - 10; self.ask_price = price + 10
                self.bid_size = 1000; self.ask_size = 1000; self.volume += random.randint(100, 1000)
                
                self.update_df() # 10번 반복하며 10개 종목을 df에 담습니다.

    # =========================================================================
    # 💼 2. Account (내 지갑 상황 데이터)
    # =========================================================================
    class Account:
        def __init__(self):
            self.update_count = 0
            dtColumns = ['종목코드','종목명','보유수량','평균매입가','평가손익','주문가능금액']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def generate_mock_data(self):
            """지갑에 삼성전자가 들어있는 것처럼 꾸밉니다."""
            self.df = pd.DataFrame(columns=self.df.columns)
            new_row = {
                '종목코드': '005930', '종목명': '삼성전자', '보유수량': 100,
                '평균매입가': '70,000', '평가손익': '2.50%', '주문가능금액': '5,000,000'
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

    # =========================================================================
    # 🧠 3. Strategy (AI의 선택 데이터)
    # =========================================================================
    class Strategy:
        def __init__(self):
            self.update_count = 0
            dtColumns = ['종목코드','종목명','MA_5','MA_20','RSI','MACD','전략신호']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def generate_mock_data(self):
            """AI가 분석 중인 것처럼 데이터를 만듭니다."""
            self.df = pd.DataFrame(columns=self.df.columns)
            prob = random.uniform(0.1, 0.9)
            new_row = {
                '종목코드': '005930', '종목명': '삼성전자', 'MA_5': 0, 'MA_20': 0, 'RSI': 0,
                'MACD': f"{prob*100:.1f}%", '전략신호': "BUY 🟢" if prob >= 0.6 else "WAIT 🟡"
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

    # 📜 4. Order (주문 내역 - 일단 뼈대만 유지)
    class Order:
        def __init__(self):
            self.df = pd.DataFrame(columns=['종목코드','종목명','주문종류','주문가격','주문수량','체결수량','주문시간','상태'])
        def generate_mock_data(self):
            pass

    # =========================================================================
    # 📡 [데이터 번역기] 파이썬 표(df)를 C#이 이해하는 JSON(배열)으로 바꿉니다.
    # 이 부분이 제대로 되어야 C# 표에 10줄이 쫙 뜹니다!
    # =========================================================================
    def market_dict(self):
        """Market 표 10줄을 묶어서 통째로 팩스를 보냅니다."""
        result_list = []
        for _, row in self.market.df.iterrows():
            result_list.append({
                "symbol": str(row['종목코드']),
                "symbol_name": str(row['종목명']),
                "last_price": str(row['현재가']),
                "open_price": str(row['시가']),
                "high_price": str(row['고가']),
                "low_price": str(row['저가']),
                "bid_price": str(row['매수호가']),
                "ask_price": str(row['매도호가']),
                "bid_size": str(row['매수잔량']),
                "ask_size": str(row['매도잔량']),
                "volume": str(row['거래량']),
                "update_count": self.market.update_count
            })
        return result_list

    def account_dict(self):
        result_list = []
        for _, row in self.account.df.iterrows():
            result_list.append({
                "symbol": str(row['종목코드']),
                "symbol_name": str(row['종목명']),
                "quantity": str(row['보유수량']),
                "avg_price": str(row['평균매입가']),
                "pnl": str(row['평가손익']),
                "available_cash": str(row['주문가능금액']),
                "update_count": self.account.update_count
            })
        return result_list

    def strategy_dict(self):
        result_list = []
        for _, row in self.strategy.df.iterrows():
            result_list.append({
                "symbol": str(row['종목코드']),
                "symbol_name": str(row['종목명']),
                "ma_5": str(row['MA_5']),
                "ma_20": str(row['MA_20']),
                "rsi": str(row['RSI']),
                "macd": str(row['MACD']),
                "signal": str(row['전략신호']),
                "update_count": self.strategy.update_count
            })
        return result_list

    def order_dict(self):
        return [] # 주문 내역은 일단 빈 배열 전송

    # 클래스 초기화 (각 방을 만듭니다)
    def __init__(self):
        self.market = TradeData.Market()
        self.account = TradeData.Account()
        self.order = TradeData.Order()
        self.strategy = TradeData.Strategy()

# 🌍 어디서든 이 바구니를 쓸 수 있게 전역 인스턴스로 선언합니다.
TradeData = TradeData()