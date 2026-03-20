import pandas as pd
import random 
from datetime import datetime

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

            dtColumns =  ['종목코드','종목명','현재가','시가','고가','저가','매수호가','매도호가','매수잔량','매도잔량','거래량']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def update_df(self):
            new_row = {
                '종목코드' : self.symbol, '종목명' : self.symbol_name, '현재가': self.last_price,
                '시가': self.open_price, '고가': self.high_price, '저가': self.low_price,
                '매수호가': self.bid_price, '매도호가': self.ask_price, '매수잔량': self.bid_size,
                '매도잔량': self.ask_size, '거래량': self.volume
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

        def generate_mock_data(self):
            self.df = pd.DataFrame(columns=self.df.columns) 
            mock_stocks = [
                ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("035420", "NAVER"),
                ("035720", "카카오"), ("005380", "현대차"), ("000270", "기아"),
                ("068270", "셀트리온"), ("005490", "POSCO홀딩스"), ("051910", "LG화학"), ("000100", "유한양행")
            ]
            
            rows = []
            for i in range(10):
                code, name = mock_stocks[i]
                change = random.randint(-300, 310)
                self.last_mock_price += change 
                
                price = self.last_mock_price
                open_p = price - random.randint(-50, 50)
                high_p = max(price, open_p) + random.randint(0, 100)
                low_p = min(price, open_p) - random.randint(0, 100)
                
                rows.append({
                    '종목코드': code, '종목명': name, '현재가': price,
                    '시가': open_p, '고가': high_p, '저가': low_p,
                    '매수호가': price - 100, '매도호가': price + 100,
                    '매수잔량': random.randint(1000, 5000), '매도잔량': random.randint(1000, 5000),
                    '거래량': random.randint(10000, 50000)
                })
            self.df = pd.concat([self.df, pd.DataFrame(rows)], ignore_index=True)

    # =========================================================================
    # 💼 2. Account (내 지갑/계좌 상황)
    # =========================================================================
    class Account:
        def __init__(self):
            self.update_count = 0
            dtColumns = ['종목코드','종목명','보유수량','평균매입가','평가손익','주문가능금액']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def generate_mock_data(self):
            self.df = pd.DataFrame(columns=self.df.columns)
            new_row = {
                '종목코드': '005930', '종목명': '삼성전자', '보유수량': 100,
                '평균매입가': '70,000', '평가손익': '2.50%', '주문가능금액': '5,000,000'
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

    # =========================================================================
    # 🧠 3. Strategy (AI 및 보조지표 분석 현황)
    # =========================================================================
    class Strategy:
        def __init__(self):
            self.update_count = 0
            # 💡 [핵심 수정] 이미지에 맞춰 '상승확률' 컬럼 추가 완료!
            dtColumns = ['종목코드','종목명','상승확률','MA_5','MA_20','RSI','MACD','전략신호']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)

        def generate_mock_data(self):
            self.df = pd.DataFrame(columns=self.df.columns)
            prob = random.uniform(0.1, 0.9)
            new_row = {
                '종목코드': '005930', '종목명': '삼성전자', 
                '상승확률': f"{prob*100:.1f}%", # 추가된 컬럼 더미 데이터
                'MA_5': 71000, 'MA_20': 70000, 
                'RSI': f"{random.randint(20, 80)}", 
                'MACD': f"{random.uniform(-1.0, 1.0):.2f}", 
                '전략신호': "BUY 🟢" if prob >= 0.6 else "WAIT 🟡"
            }
            self.df = pd.concat([self.df, pd.DataFrame([new_row])], ignore_index=True)

    # =========================================================================
    # 📜 4. Order (주문 및 체결 내역)
    # =========================================================================
    class Order:
        def __init__(self):
            # 💡 [핵심 수정] 이미지에 맞춰 한글 8개 컬럼명 지정 완료!
            dtColumns = ['종목코드', '종목명', '주문종류', '주문가격', '주문수량', '체결수량', '주문시간', '상태']
            self.df = pd.DataFrame(columns=dtColumns, dtype=object)
            
        def generate_mock_data(self):
            self.df = pd.DataFrame(columns=self.df.columns)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows = [
                {'종목코드': '005930', '종목명': '삼성전자', '주문종류': '매수(BUY)', '주문가격': '75,000', '주문수량': '10', '체결수량': '10', '주문시간': now, '상태': '체결완료'},
                {'종목코드': '000660', '종목명': 'SK하이닉스', '주문종류': '매도(SELL)', '주문가격': '150,000', '주문수량': '5', '체결수량': '5', '주문시간': now, '상태': '체결완료'}
            ]
            self.df = pd.concat([self.df, pd.DataFrame(rows)], ignore_index=True)


    # =========================================================================
    # 📡 [데이터 번역기] C# 서버 전송용 JSON 변환기
    # =========================================================================
    def market_dict(self):
        result_list = []
        for _, row in self.market.df.iterrows():
            result_list.append({
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
                "symbol": str(row.get('종목코드', '')),
                "symbol_name": str(row.get('종목명', '')),
                "quantity": str(row.get('보유수량', '0')),
                "avg_price": str(row.get('평균매입가', '0')),
                "pnl": str(row.get('평가손익', '0%')),
                "available_cash": str(row.get('주문가능금액', '0')),
                "update_count": self.account.update_count
            })
        return result_list

    def strategy_dict(self):
        result_list = []
        for _, row in self.strategy.df.iterrows():
            result_list.append({
                "symbol": str(row.get('종목코드', '')),
                "symbol_name": str(row.get('종목명', '')),
                "ai_prob": str(row.get('상승확률', '0%')), # C# 변환기에도 상승확률 추가
                "ma_5": str(row.get('MA_5', '')),
                "ma_20": str(row.get('MA_20', '')),
                "rsi": str(row.get('RSI', '')),
                "macd": str(row.get('MACD', '')),
                "signal": str(row.get('전략신호', '')),
                "update_count": self.strategy.update_count
            })
        return result_list

    def order_dict(self):
        # 💡 [핵심 수정] 빈 배열만 보내던 것을 한글 컬럼을 읽어 보내도록 고쳤습니다.
        result_list = []
        for _, row in self.order.df.iterrows():
            result_list.append({
                "time": str(row.get('주문시간', '')),
                "symbol": str(row.get('종목코드', '')),
                "symbol_name": str(row.get('종목명', '')),
                "type": str(row.get('주문종류', '')),
                "price": str(row.get('주문가격', '0')),
                "quantity": str(row.get('주문수량', '0')),
                "status": str(row.get('상태', ''))
            })
        return result_list

    def __init__(self):
        self.market = TradeData.Market()
        self.account = TradeData.Account()
        self.order = TradeData.Order()
        self.strategy = TradeData.Strategy()

TradeData = TradeData()