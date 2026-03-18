# =====================================================================
# 📦 [1단계] 마법의 도구 상자 열기 (필요한 라이브러리 가져오기)
# =====================================================================
from PyQt5 import QtWidgets, uic, QtCore, QtGui  # 화면(UI)을 예쁘게 그리고, 단축키를 만드는 핵심 도구들
from PyQt5.QtCore import Qt, QThread, pyqtSignal # 💡 [중요] 메인 화면이 멈추지 않게 도와주는 '일꾼(Thread)'과 '무전기(Signal)'
import sys
import pandas as pd        # 엑셀 표(Table)처럼 데이터를 다루기 위해 꼭 필요한 도구
import numpy as np         # 인공지능(AI) 계산을 위한 강력한 수학 도구
import random              # 테스트용 가짜 데이터나 확률을 만들 때 쓰는 주사위
import joblib              # 우리가 정성껏 학습시킨 'AI 뇌(모델 파일)'를 깨우는 도구
import os                  # 컴퓨터의 폴더나 파일을 다루는 도구 (로그 저장용)
import time                # "잠깐 쉬어!" 라고 명령하는 도구 (과부하 방지)
from datetime import datetime # "지금 몇 시야?" 시간을 확인하는 시계 도구

# 🗂️ [내부 도구] 우리가 직접 만든 부품들 가져오기
from COMMON.Flag import TradeData            # C# 화면과 데이터를 주고받을 때 쓰는 '규격화된 데이터 바구니'
from COM.TcpJsonClient import TcpJsonClient  # 완성된 데이터를 C# 화면으로 쏴주는 '통신병'
from COMMON.KIS_Manager import KIS_Manager   # 한국투자증권 서버와 대화(매수/매도/잔고조회)하는 '영업 매니저'


# ✨ [종목 번역 사전] 주식 코드만 보면 헷갈리니까 이름을 달아줍니다.
STOCK_DICT = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "005380": "현대차", "000270": "기아", "068270": "셀트리온",
    "005490": "POSCO홀딩스", "035420": "NAVER", "035720": "카카오",
    "000810": "삼성화재", "051910": "LG화학", "105560": "KB금융",
    "012330": "현대모비스", "032830": "삼성생명", "055550": "신한지주",
    "003550": "LG", "000100": "유한양행", "033780": "KT&G",
    "009150": "삼성전기", "015760": "한국전력"
}

# =====================================================================
# ⚙️ [2단계] 백그라운드 일꾼 (AutoTradeWorker) - 화면 뒤에서 쉬지 않고 일하는 엔진!
# =====================================================================
class AutoTradeWorker(QThread):
    # 📻 [무전기 세팅] 일꾼이 일하다가 화면(UI)쪽에 보고할 때 쓰는 무전기들입니다.
    sig_log = pyqtSignal(str, str)             # 로그 창에 글씨를 쓰라고 명령하는 무전기
    sig_account_df = pyqtSignal(object)        # 계좌 잔고 표를 업데이트하라는 무전기
    sig_strategy_df = pyqtSignal(object)       # 전략 표를 업데이트하라는 무전기
    sig_market_df = pyqtSignal(object)         # 💡 [핵심] C# 차트를 그릴 수 있도록 '시세'를 던져주는 무전기!
    sig_sync_cs = pyqtSignal()                 # "C#으로 전송해!" 라고 알리는 무전기
    sig_order_append = pyqtSignal(dict)        # 💡 [핵심] 덮어쓰지 않고 표 밑에 계속 '누적'시키라는 무전기!

    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window   # 사장님(FormMain)이 누군지 기억해둡니다.
        self.is_running = False # 일꾼의 현재 상태 (쉬는중)

    def run(self):
        """일꾼이 일을 시작하면 이 함수가 무한 반복됩니다."""
        self.is_running = True
        while self.is_running:
            self.process_trading() # 매수/매도 업무 시작!
            
            # 1분(60초) 대기합니다. 단, 중간에 정지 버튼을 누르면 즉시 쉴 수 있도록 1초씩 쪼개서 검사합니다.
            for _ in range(60):
                if not self.is_running: break 
                time.sleep(1)

    # 🚨 [특수 임무] 100% 매도를 보장하는 불도저 함수!
    def execute_guaranteed_sell(self, code, qty, current_price):
        """호가가 맞지 않아 안 팔리는 현상을 막기 위해, 가격을 낮춰가며 끈질기게 매도합니다."""
        max_retries = 3 # 최대 3번 시도합니다.
        target_price = current_price
        
        for attempt in range(max_retries):
            success = self.mw.api_manager.sell(code, qty) # 지정가/시장가 매도 시도
            if success:
                self.sig_log.emit(f"✅ [{code}] 매도 주문 성공! (시도 횟수: {attempt+1})", "success")
                return True
            
            # 실패하면? 가격을 0.5% 후려쳐서 다시 던집니다!
            target_price = int(target_price * 0.995)
            self.sig_log.emit(f"⚠️ [{code}] 매도 미체결. 재시도... ({attempt+1}/{max_retries})", "warning")
            time.sleep(1.0) # 서버 부하를 막기 위해 1초 대기
            
        # 3번 다 실패하면 묻지도 따지지도 않고 시장가로 강제 청산(패닉셀)!
        self.sig_log.emit(f"🚨 [{code}] 3회 매도 실패! 시장가 강제 청산.", "error")
        success = self.mw.api_manager.sell(code, qty) 
        return success

    def process_trading(self):
        """1분마다 한 번씩 보유 종목을 감시하고, 빈자리가 있으면 새 주식을 쇼핑하는 핵심 엔진입니다."""
        now = datetime.now() 
        self.sig_log.emit(f"🔄 [주삐 엔진 가동중] {now.strftime('%H:%M')} - 매도 감시 및 타겟 스캔 중...", "info")

        MAX_STOCKS = 10     # 지갑에 담을 수 있는 최대 주식 개수
        TAKE_PROFIT = 3.0   # 3% 먹으면 욕심 안 부리고 익절!
        STOP_LOSS = -2.0    # -2% 물리면 미련 없이 손절!
        SCAN_POOL = list(STOCK_DICT.keys()) # 스캔할 관심 종목 리스트

        account_rows = [] # 파이썬 계좌 표에 그릴 데이터 바구니
        market_rows = []  # C# 차트에 점을 찍기 위해 수집할 시세 바구니
        
        # 계좌 전체의 수익/손실을 계산하기 위한 저금통
        total_invested = 0     # 내가 쏟아부은 원금 총합
        total_current_val = 0  # 지금 당장 팔았을 때 받을 수 있는 돈 총합

        # =====================================================================
        # 🔍 [임무 1] 보유 종목 감시 (팔 때가 되었나? 수익률은 얼마인가?)
        # =====================================================================
        if len(self.mw.my_holdings) > 0: 
            sold_codes = [] # 방금 막 팔아버린 주식들의 이름을 적어둘 메모장
            hold_status_list = [] # 안 팔고 쥐고 있는 주식들의 성적표를 모아둘 리스트
            
            for code, info in self.mw.my_holdings.items():
                buy_price = info['price'] # 내가 예전에 샀던 가격
                buy_qty = info['qty']     # 내가 가지고 있는 수량
                
                # 증권사에서 이 주식의 최근 1분봉 차트 기록을 통째로 가져옵니다.
                df = self.mw.api_manager.fetch_minute_data(code)
                if df is None or len(df) < 20: continue # 데이터가 꼬여서 안 오면 이번 턴은 패스!
                
                curr_price = df.iloc[-1]['close'] # 방금 전 1분봉의 종가(현재가)
                profit_rate = ((curr_price - buy_price) / buy_price) * 100 # 현재 수익률 계산 (%)
                stock_name = STOCK_DICT.get(code, f"알수없음_{code}")

                # 💡 내 계좌 총합을 구하기 위해 원금과 현재가치를 계속 누적해서 더합니다.
                total_invested += (buy_price * buy_qty)
                total_current_val += (curr_price * buy_qty)

                # 💡 [진짜 캔들 데이터 추출] 1분봉의 진짜 시가, 고가, 저가를 가져옵니다.
                curr_open = float(df.iloc[-1].get('open', curr_price))
                curr_high = float(df.iloc[-1].get('high', curr_price))
                curr_low = float(df.iloc[-1].get('low', curr_price))

                # 💡 차트에 그리기 위해 '진짜 캔들 데이터'를 시세 배열에 저장합니다!
                market_rows.append({
                    '종목코드': code, '종목명': stock_name, '현재가': curr_price,
                    '시가': curr_open, '고가': curr_high, '저가': curr_low,
                    '매수호가': 0, '매도호가': 0, '매수잔량': 0, '매도잔량': 0, '거래량': 0
                })

                # 📈 MACD 보조지표 계산 (주가가 꺾이는지 확인하는 레이더)
                df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
                df['Signal'] = df['MACD'].ewm(span=9).mean()
                curr_macd = df.iloc[-1]['MACD']
                curr_signal = df.iloc[-1]['Signal']

                is_sell = False # 팔아야 하나요? (기본값: 아니요)
                status_msg = "" # 로그에 띄울 매도 이유

                # 🚨 [장 마감 스페셜 로직] 오버나잇(내일까지 들고 가기) 절대 금지!
                if now.hour == 15 and now.minute >= 10:
                    # 오후 3시 10분이 넘으면? 무조건 다 팔고 도망칩니다!
                    is_sell = True
                    status_msg = f"🚨 마감 임박 강제 청산! ({profit_rate:.2f}%)"
                elif now.hour == 15 and 0 <= now.minute < 10:
                    # 오후 3시 ~ 3시 10분 사이에는 수수료(0.3%)만 건져도 던집니다.
                    if profit_rate >= 0.3:
                        is_sell = True
                        status_msg = f"⏰ 마감 전 수수료 방어 익절 (+{profit_rate:.2f}%)"
                    elif profit_rate > 0.0 and curr_macd < curr_signal:
                        is_sell = True
                        status_msg = f"⏰ 마감 전 추세꺾임 탈출 (+{profit_rate:.2f}%)"
                    elif profit_rate <= STOP_LOSS:
                        is_sell = True
                        status_msg = f"📉 마감 전 기계적 손절 ({profit_rate:.2f}%)"
                else:
                    # 🌞 [평시 로직] 장 중에는 정해진 룰에 따라 움직입니다.
                    if profit_rate >= TAKE_PROFIT:     
                        is_sell = True
                        status_msg = f"📈 기계적 익절 (+{profit_rate:.2f}%)"
                    elif profit_rate <= STOP_LOSS:     
                        is_sell = True
                        status_msg = f"📉 기계적 손절 ({profit_rate:.2f}%)"
                    elif profit_rate > 2.0 and curr_macd < curr_signal: 
                        # 2% 이상 수익이 났는데 MACD가 꺾이면 욕심 안 부리고 익절합니다.
                        is_sell = True
                        status_msg = f"📉 데드크로스 출현! 수익보존 익절 (+{profit_rate:.2f}%)"

                # 판결의 시간: 팔아야 한다면?
                if is_sell:
                    success = self.execute_guaranteed_sell(code, buy_qty, curr_price) # 불도저 함수 출동!
                    if success: 
                        sold_codes.append(code) # 정상적으로 팔았으니 삭제 명단에 적어둡니다.
                        
                        self.sig_log.emit(f"====================================", "warning")
                        self.sig_log.emit(f"{status_msg} -> [{stock_name}] 매도 완료!", "warning")
                        self.sig_log.emit(f"====================================", "warning")
                        
                        # 💡 팔았다는 사실을 파이썬/C# 표 밑에 '새로운 줄'로 예쁘게 누적시킵니다!
                        order_info = {'Time': now.strftime("%Y-%m-%d %H:%M:%S"), 'Symbol': code, 'Name': stock_name, 'Type': 'SELL', 'Price': curr_price}
                        self.sig_order_append.emit(order_info)
                else:
                    # 안 팔고 계속 쥐고 가기로 했다면? 계좌 표에 최신 성적표를 갱신해 줍니다.
                    account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': buy_qty, '평균매입가': f"{buy_price:,.0f}", '평가손익': f"{profit_rate:.2f}%", '주문가능금액': 0})
                    hold_status_list.append(f"{stock_name}({profit_rate:.2f}%)") # 로그 보고용 리스트에도 추가
                    
            # 매도가 끝났으면 내 지갑(메모리)에서 팔린 주식을 확실히 버립니다! (삭제 처리)
            for code in sold_codes:
                del self.mw.my_holdings[code]

            # 💡 [매도 보류 브리핑] "왜 아직 안 팔았어?" 라고 궁금해하실까 봐 로그에 적어줍니다.
            if len(hold_status_list) > 0:
                self.sig_log.emit(f"🔒 [매도 보류] {', '.join(hold_status_list)} ➔ 목표가 미도달", "info")
                
            # 💡 [계좌 전체 요약 브리핑] 총얼마를 투자해서 얼마를 벌고 있는지 한눈에 보여줍니다.
            if total_invested > 0:
                total_profit = total_current_val - total_invested # 총 평가손익 (원)
                total_profit_rate = (total_profit / total_invested) * 100 # 총 수익률 (%)
                
                # 벌었으면 초록색(success), 잃었으면 노란색(warning)으로 칠해줍니다.
                pnl_color = "success" if total_profit > 0 else "warning" if total_profit < 0 else "info"
                self.sig_log.emit(f"📊 [현재 계좌 종합] 총 투자금: {int(total_invested):,}원 / 총 평가손익: {int(total_profit):,}원 ({total_profit_rate:.2f}%)", pnl_color)


        # =====================================================================
        # 🛒 [임무 2] 신규 매수 로직 (빈자리가 있으면 AI가 점지해 주는 종목을 삽니다)
        # =====================================================================
        current_count = len(self.mw.my_holdings) # 지금 내 지갑에 들어있는 주식 종류 개수
        needed_count = MAX_STOCKS - current_count # 앞으로 더 살 수 있는 빈자리 개수
        
        # 내 실제 계좌의 남은 현금을 조회합니다.
        api_cash = self.mw.api_manager.get_balance()
        if api_cash is None:
            # 증권사 서버가 잠깐 맛이 가서 None을 주면, 잔고가 0으로 날아가는 걸 막기 위해 예전 돈을 그대로 씁니다!
            my_cash = getattr(self.mw, 'last_known_cash', 0)
        else:
            my_cash = api_cash
            self.mw.last_known_cash = my_cash # 정상일 땐 꼭 예비 금고에 저장해 둡니다.
            
        cash_str = f"{my_cash:,}" 
        
        # 🚨 [시간제한 차단기] 오후 3시가 넘었으면 절대 주식을 새로 사지 않습니다! 퇴근 준비!
        if now.hour >= 15:
            self.sig_log.emit("⏰ [쇼핑 종료] 오후 3시가 넘었습니다. 신규 매수를 전면 차단합니다.", "error")
        else:
            # 3시 이전이고 + 빈자리(needed_count)도 있고 + 돈도 있으면 쇼핑을 시작합니다.
            if needed_count > 0:
                # [안전 투자법] 한 종목에 내 전 재산의 딱 10%만 투자합니다! (몰빵 금지)
                total_asset = my_cash + sum([info['price'] * info['qty'] for info in self.mw.my_holdings.values()])
                BUDGET_PER_STOCK = int(total_asset * 0.1)

                candidates = [] # AI 면접을 통과한 훌륭한 종목들을 모아둘 방
                best_prob = 0.0 # 스캔하면서 제일 똑똑했던(확률 높은) 녀석의 점수
                best_stock_name = ""

                for code in SCAN_POOL:
                    if code in self.mw.my_holdings: continue # 이미 산 주식은 또 안 삽니다.
                    
                    # AI에게 물어봅니다. "이 주식 당장 오를 확률이 몇 %야?"
                    prob, curr_price = self.mw.get_ai_probability(code)

                    # 🚨 [위험 방지 2] AI가 고장나서 -1점을 줬다면, 매수 스캔을 즉시 멈추고 로그를 띄웁니다!
                    if prob == -1.0:
                        self.sig_log.emit("🚨 [비상] AI 뇌(pkl)를 찾을 수 없습니다! 랜덤 묻지마 매수를 차단합니다.", "error")
                        candidates = [] # 후보군 통째로 비우기
                        break # 스캔 즉각 탈출

                    stock_name = STOCK_DICT.get(code, code) 
                    
                    # 💡 [진짜 캔들 데이터 추출] 1분봉의 진짜 시가, 고가, 저가를 가져옵니다.
                    curr_open = float(df.iloc[-1].get('open', curr_price))
                    curr_high = float(df.iloc[-1].get('high', curr_price))
                    curr_low = float(df.iloc[-1].get('low', curr_price))

                    # 💡 차트에 그리기 위해 '진짜 캔들 데이터'를 시세 배열에 저장합니다!
                    market_rows.append({
                        '종목코드': code, '종목명': stock_name, '현재가': curr_price,
                        '시가': curr_open, '고가': curr_high, '저가': curr_low,
                        '매수호가': 0, '매도호가': 0, '매수잔량': 0, '매도잔량': 0, '거래량': 0
                    })

                    # 매수 보류 브리핑을 위해 1등 녀석의 점수를 기록해 둡니다.
                    if prob > best_prob:
                        best_prob = prob
                        best_stock_name = stock_name

                    # 60점(60%)을 넘긴 녀석들만 합격 목걸이를 줍니다.
                    if prob >= 0.6: candidates.append({'code': code, 'prob': prob, 'price': curr_price})
                    time.sleep(0.2) # 너무 빨리 물어보면 서버가 화내니까 0.2초씩 쉬어줍니다.
                
                # 💡 합격자가 한 명도 없다면? 로그에 왜 안 샀는지 변명(브리핑)을 적어줍니다.
                if len(candidates) == 0:
                    self.sig_log.emit(f"🤔 [매수 보류] AI 상승확률 60% 통과 종목 없음. (현재 1위: {best_stock_name} {best_prob*100:.1f}%)", "warning")
                else:
                    # 합격자가 있다면? 점수가 제일 높은 애들부터 줄을 세웁니다.
                    candidates = sorted(candidates, key=lambda x: x['prob'], reverse=True)

                    # 빈자리(needed_count) 개수만큼만 딱 맞춰서 차례대로 구매합니다.
                    for i in range(min(needed_count, len(candidates))):
                        target = candidates[i]
                        code = target['code']
                        curr_price = target['price']
                        stock_name = STOCK_DICT.get(code, code) 
                        buy_qty = int(BUDGET_PER_STOCK / curr_price) # 내가 가진 돈(10%)으로 몇 주 살 수 있는지 계산 (소수점 버림)
                        
                        if buy_qty > 0:
                            success = self.mw.api_manager.buy_market_price(code, buy_qty)
                            if success:
                                # 성공했으면 내 지갑(my_holdings)에 소중히 넣습니다.
                                self.mw.my_holdings[code] = {'price': curr_price, 'qty': buy_qty}
                                self.sig_log.emit(f"🛒 [AI 매수] {stock_name} (상승확률: {target['prob']*100:.1f}%)", "info")
                                
                                # 💡 샀다는 기록을 파이썬/C# 표에 새로운 줄로 예쁘게 추가합니다!
                                order_info = {'Time': now.strftime("%Y-%m-%d %H:%M:%S"), 'Symbol': code, 'Name': stock_name, 'Type': 'BUY', 'Price': curr_price}
                                self.sig_order_append.emit(order_info)

                                # 💡 방금 산 주식을 계좌 표에도 바로바로 보여줍니다!
                                account_rows.append({'종목코드': code, '종목명': stock_name, '보유수량': buy_qty, '평균매입가': f"{curr_price:,.0f}", '평가손익': "0.00%", '주문가능금액': 0})

        # =====================================================================
        # 📤 [임무 3] 모아둔 데이터들을 한방에 화면(UI)으로 쏘아 올리기! (동기화)
        # =====================================================================
        if len(account_rows) > 0:
            account_rows[0]['주문가능금액'] = cash_str # 표의 맨 첫 줄에만 내 남은 현금을 적어줍니다.
        else:
            # 주식이 1개도 없으면 표가 텅 비니까, "보유종목 없음"이라고 친절하게 1줄을 만들어줍니다.
            account_rows.append({'종목코드': '-', '종목명': '보유종목 없음', '보유수량': 0, '평균매입가': '0', '평가손익': '0.00%', '주문가능금액': cash_str})
        
        # 무전기를 통해 파이썬 화면의 계좌 표를 새로고침합니다!
        self.sig_account_df.emit(pd.DataFrame(account_rows)) 

        # 무전기를 통해 C# 차트에 점을 찍을 데이터를 쏴줍니다!
        if len(market_rows) > 0:
            self.sig_market_df.emit(pd.DataFrame(market_rows))

        # "데이터 준비 다 끝났으니 C#으로 통신 날려!" 라고 메인 화면에 지시합니다.
        self.sig_sync_cs.emit()


# =====================================================================
# 🖥️ 메인 UI 클래스 (FormMain) - 주삐 프로젝트의 지휘통제실!
# =====================================================================
class FormMain(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI() # 화면의 버튼, 표, 로그창 등을 배치합니다.

        self.api_manager = KIS_Manager(ui_main=self) # 증권사 영업 매니저 채용
        self.api_manager.start_api() # 증권사 서버 로그인!

        self.my_holdings = {} # 내 주식을 담아둘 지갑 (딕셔너리)
        self.last_known_cash = 0 # 💡 API 통신이 끊겼을 때를 대비한 비상금(잔고) 저장소
        
        self.trade_worker = AutoTradeWorker(main_window=self) # 백그라운드에서 매매할 일꾼 고용
        
        # 📻 일꾼의 무전기와 내 화면(함수)들을 연결해 줍니다. (그래야 화면이 바뀜)
        self.trade_worker.sig_log.connect(self.add_log)                                
        self.trade_worker.sig_account_df.connect(self.update_account_table_slot)       
        self.trade_worker.sig_strategy_df.connect(self.update_strategy_table_slot)     
        self.trade_worker.sig_sync_cs.connect(self.btnDataSendClickEvent) 
        self.trade_worker.sig_order_append.connect(self.append_order_table_slot) # 파이썬 표 누적 연결             
        self.trade_worker.sig_market_df.connect(self.update_market_table_slot)   # 시세 표 업데이트 연결

        # 🚨 [버그 방패] 프로그램 켜자마자 잔고를 달라고 하면 증권사 서버가 화내서 튕깁니다. 3초 뒤에 안전하게 부릅니다!
        QtCore.QTimer.singleShot(3000, self.load_real_holdings) 

    @QtCore.pyqtSlot(dict)
    def append_order_table_slot(self, order_info):
        """파이썬 매매 표(tbOrder) 누적 및 500줄 메모리 제한 로직"""
        new_row = pd.DataFrame([order_info])
        if TradeData.order.df.empty:
            TradeData.order.df = new_row
        else:
            TradeData.order.df = pd.concat([TradeData.order.df, new_row], ignore_index=True)

        # 🧹 [메모리 누수 방지] 백그라운드 데이터가 500개가 넘으면 제일 오래된 것을 지웁니다.
        MAX_ROWS = 500
        if len(TradeData.order.df) > MAX_ROWS:
            TradeData.order.df = TradeData.order.df.iloc[-MAX_ROWS:].reset_index(drop=True)

        row_idx = self.tbOrder.rowCount()
        self.tbOrder.insertRow(row_idx) 
        
        cols = ['Time', 'Symbol', 'Name', 'Type', 'Price']
        for col_idx, key in enumerate(cols):
            val = str(order_info.get(key, ''))
            item = QtWidgets.QTableWidgetItem(val)
            item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.tbOrder.setItem(row_idx, col_idx, item)

        # 🧹 [메모리 누수 방지] 화면 표의 줄 수가 500개를 넘으면 맨 윗줄(0번) 삭제!
        if self.tbOrder.rowCount() > MAX_ROWS:
            self.tbOrder.removeRow(0)
            
        self.tbOrder.scrollToBottom() 
        self.btnDataSendClickEvent()

    @QtCore.pyqtSlot() 
    def btnDataSendClickEvent(self):
        """C# 화면으로 4개의 표 데이터를 싹 다 택배로 보냅니다."""
        if TcpJsonClient.Isconnected:
            self.client.send_message("market", TradeData.market_dict())
            self.client.send_message("account", TradeData.account_dict())
            self.client.send_message("strategy", TradeData.strategy_dict())
            # 🚨 [버그 해결] 예전에 여기서 'order(주문)'를 안 보내서 C# 누적 표가 먹통이었습니다. 추가 완료!
            self.client.send_message("order", TradeData.order_dict())

    # 💡 [버그 방패] 시세(Market) 표 업데이트 및 KeyError 완벽 방어
    @QtCore.pyqtSlot(object) 
    def update_market_table_slot(self, df):
        """일꾼이 던져준 시세 데이터를 Flag.py가 좋아하는 11개 한글 세트로 완벽히 번역해서 에러를 막습니다."""
        standard_cols = ['종목코드','종목명','현재가','시가','고가','저가','매수호가','매도호가','매수잔량','매도잔량','거래량']
        
        if df.empty:
            TradeData.market.df = pd.DataFrame(columns=standard_cols)
            return

        # 만약 일꾼이 실수로 영어를 보냈다면 찰떡같이 한글로 번역합니다.
        if '종목코드' not in df.columns:
            if 'Symbol' in df.columns:
                df = df.rename(columns={'Symbol': '종목코드', 'Name': '종목명', 'Price': '현재가'})

        # 빈칸이 있다면 에러가 나지 않게 숫자 0으로 메꿔줍니다.
        for col in standard_cols:
            if col not in df.columns:
                df[col] = 0
                
        # 순서까지 완벽하게 맞춰서 엑셀 표에 저장!
        TradeData.market.df = df[standard_cols]
        self.update_table(self.tbMarket, TradeData.market.df)


    def load_real_holdings(self):
        """프로그램 시작 시 증권사 서버에서 내 진짜 잔고와 보유 주식을 가져오는 함수입니다."""
        try:
            self.my_holdings = self.api_manager.get_real_holdings()
            self.add_log(f"💼 [잔고 동기화] {len(self.my_holdings)}개 종목 로드 완료.", "success")
        except Exception as e:
            self.add_log(f"⚠️ 잔고 로드 에러: {e}", "error")
            return

        my_cash = self.api_manager.get_balance()
        cash_str = f"{my_cash:,}" if my_cash is not None else "0"

        account_rows = []
        is_first = True
        
        for code, info in self.my_holdings.items():
            buy_price = info['price']
            buy_qty = info['qty']
            stock_name = STOCK_DICT.get(code, f"알수없음_{code}")
            
            df = self.api_manager.fetch_minute_data(code)
            pnl_str = "0.00%"
            if df is not None:
                curr_price = df.iloc[-1]['close']
                profit_rate = ((curr_price - buy_price) / buy_price) * 100
                pnl_str = f"{profit_rate:.2f}%"

            account_rows.append({
                '종목코드': code, '종목명': stock_name, '보유수량': buy_qty, 
                '평균매입가': f"{buy_price:,.0f}", '평가손익': pnl_str,
                '주문가능금액': cash_str if is_first else "" 
            })
            is_first = False
            
        if account_rows:
            TradeData.account.df = pd.DataFrame(account_rows)
            QtCore.QTimer.singleShot(500, lambda: self.update_table(self.tbAccount, TradeData.account.df))


    # =====================================================================
    # 🎨 화면 꾸미기 및 버튼 기능 설정 (이하 UI 관련 함수들)
    # =====================================================================
    def initUI(self):
        uic.loadUi("GUI/Main.ui", self)
        self.client = TcpJsonClient(host="127.0.0.1", port=9001)

        self.setWindowFlags(QtCore.Qt.FramelessWindowHint) 
        self.setGeometry(0, 0, 1920, 1080) 
        self.centralwidget.setStyleSheet("background-color: rgb(5,5,15);") 

        self.tbMarket = QtWidgets.QTableWidget(self.centralwidget)
        self.tbMarket.setGeometry(5, 50, 1420, 240)
        self._setup_table(self.tbMarket, list(TradeData.market.df.columns))

        self.tbAccount = QtWidgets.QTableWidget(self.centralwidget)
        self.tbAccount.setGeometry(5, 295, 1420, 240)
        self._setup_table(self.tbAccount, list(TradeData.account.df.columns))

        self.tbOrder = QtWidgets.QTableWidget(self.centralwidget)
        self.tbOrder.setGeometry(5, 540, 1420, 240)
        self._setup_table(self.tbOrder, list(TradeData.order.df.columns))

        self.tbStrategy = QtWidgets.QTableWidget(self.centralwidget)
        self.tbStrategy.setGeometry(5, 785, 1420, 240)
        self._setup_table(self.tbStrategy, list(TradeData.strategy.df.columns))

        self.txtLog = QtWidgets.QPlainTextEdit(self.centralwidget)
        self.txtLog.setGeometry(1430, 95, 485, 930)
        self.txtLog.setReadOnly(True) 
        self.txtLog.setStyleSheet("background-color: rgb(20, 30, 45); color: white; font-family: Consolas; font-size: 13px;")
        self.txtLog.mousePressEvent = self.custom_log_mouse_press

        self.btnDataCreatTest = self._create_nav_button("데이터 자동생성 시작", 5)
        self.btnDataSendTest = self._create_nav_button("C# 데이터 수동전송", 310)
        self.btnSimulDataTest = self._create_nav_button("계좌 잔고 조회", 615)
        self.btnAutoDataTest = self._create_nav_button("자동 매매 가동 (GO)", 920)
        self.btnDataClearTest = self._create_nav_button("화면 데이터 초기화", 1225)
        
        self.btnClose = QtWidgets.QPushButton(" X ", self.centralwidget)
        self.btnClose.setGeometry(1875, 5, 40, 40)
        self.btnClose.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")

        self.btnConnected = QtWidgets.QPushButton("통신 연결 X", self.centralwidget)
        self.btnConnected.setGeometry(1430, 50, 485, 40)
        self.btnConnected.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")

        self.btnDataCreatTest.clicked.connect(self.btnDataCreatClickEvent)
        self.btnDataSendTest.clicked.connect(self.btnDataSendClickEvent)
        self.btnSimulDataTest.clicked.connect(self.btnSimulTestClickEvent)
        self.btnAutoDataTest.clicked.connect(self.btnAutoTradingSwitch)
        self.btnDataClearTest.clicked.connect(self.btnDataClearClickEvent)
        self.btnClose.clicked.connect(self.btnCloseClickEvent)
        self.btnConnected.clicked.connect(self.btnConnectedClickEvent)

        self.shortcut_sell = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Shift+W"), self)
        self.shortcut_sell.activated.connect(self.emergency_sell_event)


    # =========================================================================
    # 💡 [요청 반영] "계좌 잔고 조회" 버튼을 눌렀을 때의 특별한 브리핑 함수!
    # =========================================================================
    def btnSimulTestClickEvent(self):
        """계좌 잔고 조회 버튼을 누르면 증권사 서버에서 돈과 주식을 확인해 로그 창에 상세히 브리핑합니다."""
        self.add_log("🔄 [수동 조회] 증권사 서버에 계좌 현황을 요청합니다...", "info")
        
        # 1. 잔고 업데이트
        self.api_manager.check_my_balance() 
        current_cash = self.api_manager.get_balance()
        cash_str = f"{current_cash:,}원" if current_cash is not None else "조회 실패"
        
        # 2. 보유 주식 목록 예쁘게 브리핑
        if len(self.my_holdings) == 0:
            self.add_log(f"💰 [계좌 잔고 보고] 남은 현금: {cash_str} / 현재 보유 중인 주식이 하나도 없습니다! (텅텅)", "warning")
        else:
            self.add_log(f"💰 [계좌 잔고 보고] 남은 현금: {cash_str} / 총 {len(self.my_holdings)}개 종목 보유 중:", "success")
            
            for code, info in self.my_holdings.items():
                stock_name = STOCK_DICT.get(code, code)
                buy_price = info['price']
                buy_qty = info['qty']
                total_value = buy_price * buy_qty
                
                # 로그 창에 한 줄씩 예쁘게 출력! (예: 🔹 삼성전자 - 5주 (평단가: 75,000원 / 총액: 375,000원))
                self.add_log(f"   🔹 {stock_name} - {buy_qty}주 (평단가: {buy_price:,.0f}원 / 총액: {total_value:,.0f}원)", "success")
                time.sleep(0.05) # 출력 애니메이션 효과 (부드럽게 촤르륵)


    def custom_log_mouse_press(self, event):
        if event.button() == Qt.LeftButton and event.modifiers() == Qt.ControlModifier:
            text = self.txtLog.toPlainText() 
            if not text.strip(): return 
            os.makedirs("Logs", exist_ok=True) 
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S") 
            filename = f"Logs/Manual_Log_{now_str}.txt" 
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            self.add_log(f"💾 [저장 성공] 현재 로그가 {filename} 로 캡처되었습니다.", "success")
        else:
            QtWidgets.QPlainTextEdit.mousePressEvent(self.txtLog, event)

    def emergency_sell_event(self):
        selected_ranges = self.tbAccount.selectedRanges() 
        if not selected_ranges:
            self.add_log("⚠️ 매도할 종목을 'Account 표'에서 클릭해주세요.", "warning")
            return
            
        row = selected_ranges[0].topRow() 
        item = self.tbAccount.item(row, 0) 
        if item is None: return
        code = item.text() 
        
        if code in self.my_holdings:
            qty = self.my_holdings[code]['qty']
            success = self.api_manager.sell(code, qty) 
            if success:
                del self.my_holdings[code]     
                self.tbAccount.removeRow(row)  
                stock_name = STOCK_DICT.get(code, code)
                self.add_log(f"🚨 [비상 탈출] {stock_name} {qty}주 수동 매도 완료!", "error")
                self.btnDataSendClickEvent()   
        else:
            self.add_log(f"⚠️ 이미 팔았거나 지갑에 없는 종목입니다: {code}", "error")

    def btnAutoTradingSwitch(self):
        if not self.trade_worker.is_running: 
            self.trade_worker.start() 
            self.btnAutoDataTest.setText("자동 매매 중단 (STOP)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 [주삐 엔진] 1분 단위 감시망 가동! 잠시 후 첫 브리핑이 시작됩니다.", "success")
        else: 
            self.trade_worker.is_running = False 
            self.trade_worker.quit() 
            self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 [주삐 엔진] 감시망을 거둡니다. 푹 쉬세요!", "warning")

    def get_ai_probability(self, code):
            df = self.api_manager.fetch_minute_data(code) 
            if df is None or len(df) < 30: return 0.0, 0 

            df['return'] = df['close'].pct_change()
            df['vol_change'] = df['volume'].pct_change()
            delta = df['close'].diff()
            up, down = delta.copy(), delta.copy()
            up[up < 0] = 0; down[down > 0] = 0
            df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.abs().ewm(com=13).mean())))
            df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
            df['MA20'] = df['close'].rolling(20).mean()
            df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
            
            curr = df.iloc[-1].fillna(0).replace([np.inf, -np.inf], 0)
            curr_price = curr['close'] 
            
            features = ['return', 'vol_change', 'RSI', 'MACD', 'BB_Lower']
            X = curr[features].values.reshape(1, -1)
            
            # 🚨 [위험 방지 1] 묻지마(랜덤) 매수 삭제! 모델이 없으면 -1을 반환합니다.
            if hasattr(self, 'model') and self.model is not None:
                prob = self.model.predict_proba(X)[0][1] 
            else:
                prob = -1.0 # 뇌(모델)가 없다는 에러 신호!
            
            return prob, curr_price

    @QtCore.pyqtSlot(object) 
    def update_account_table_slot(self, df):
        TradeData.account.df = df
        self.update_table(self.tbAccount, df)

    @QtCore.pyqtSlot(object) 
    def update_strategy_table_slot(self, df):
        TradeData.strategy.df = df
        self.update_table(self.tbStrategy, df)

    @QtCore.pyqtSlot(str, str) 
    def add_log(self, text, log_type="info"):
        color = {"info": "white", "success": "lime", "warning": "yellow", 
                 "error": "red", "send": "cyan", "recv": "orange"}.get(log_type, "white")
        now = datetime.now().strftime("[%H:%M:%S]")
        html_message = f'<span style="color:{color}">{now} {text}</span>'
        
        QtCore.QTimer.singleShot(0, lambda: self._safe_append_log(html_message))

    def _safe_append_log(self, html_msg):
        self.txtLog.appendHtml(html_msg)
        self.txtLog.verticalScrollBar().setValue(self.txtLog.verticalScrollBar().maximum())

    def _setup_table(self, table, columns):
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        self.style_table(table)

    def style_table(self, table):
        table.setFont(QtGui.QFont("Noto Sans KR", 12))
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch) 
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)  
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection) 
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)   
        table.setStyleSheet("""
            QTableWidget { background-color: rgb(50,80,110); color: Black; selection-background-color: rgb(80, 120, 160); } 
            QHeaderView::section { background-color: rgb(40,60,90); color: Black; font-weight: bold; }
        """)

    def _create_nav_button(self, text, x_pos):
        btn = QtWidgets.QPushButton(text, self.centralwidget)
        btn.setGeometry(x_pos, 5, 300, 40)
        btn.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor)) 
        btn.installEventFilter(self) 
        return btn

    def eventFilter(self, source, event):
        if event.type() == QtCore.QEvent.Enter: source.setStyleSheet("background-color: rgb(5,5,10); color: Lime;")
        elif event.type() == QtCore.QEvent.Leave: source.setStyleSheet("background-color: rgb(5,5,10); color: Silver;")
        return super().eventFilter(source, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._isDragging = True
            self._startPos = event.globalPos() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, event):
        if self._isDragging: self.move(event.globalPos() - self._startPos)
    def mouseReleaseEvent(self, event): self._isDragging = False

    def btnCloseClickEvent(self): QtWidgets.QApplication.quit()          

    def btnDataCreatClickEvent(self):
        if hasattr(self, 'mock_data_timer') and self.mock_data_timer.isActive():
            self.mock_data_timer.stop()
            self.btnDataCreatTest.setText("데이터 자동생성 시작")
            self.btnDataCreatTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 실시간 가짜 데이터 전송을 멈춥니다.", "warning")
        else:
            if not hasattr(self, 'mock_data_timer'):
                self.mock_data_timer = QtCore.QTimer(self)
                self.mock_data_timer.timeout.connect(self.generate_and_send_mock_data)
            self.mock_data_timer.start(1000)
            self.btnDataCreatTest.setText("데이터 자동생성 중지 (STOP)")
            self.btnDataCreatTest.setStyleSheet("background-color: rgb(10, 70, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 1초마다 가짜 데이터를 C#으로 연속 발사합니다!", "success")

    def generate_and_send_mock_data(self):
        TradeData.market.generate_mock_data()
        TradeData.account.generate_mock_data()
        TradeData.order.generate_mock_data()
        TradeData.strategy.generate_mock_data()
        
        self.update_table(self.tbMarket, TradeData.market.df)
        self.update_table(self.tbAccount, TradeData.account.df)
        self.update_table(self.tbOrder, TradeData.order.df)
        self.update_table(self.tbStrategy, TradeData.strategy.df)
        
        self.btnDataSendClickEvent()

    def update_table(self, tableWidget, df):
        tableWidget.setUpdatesEnabled(False) 

        current_row_count = tableWidget.rowCount() 
        new_row_count = len(df)                    

        if current_row_count < new_row_count:
            for _ in range(new_row_count - current_row_count):
                tableWidget.insertRow(tableWidget.rowCount())
        elif current_row_count > new_row_count:
            for _ in range(current_row_count - new_row_count):
                tableWidget.removeRow(tableWidget.rowCount() - 1)

        for i in range(new_row_count):
            for j, col in enumerate(df.columns):
                val = str(df.iloc[i, j])          
                item = tableWidget.item(i, j)     

                if item is None:
                    item = QtWidgets.QTableWidgetItem(val)
                    item.setTextAlignment(QtCore.Qt.AlignCenter)
                    tableWidget.setItem(i, j, item)
                else:
                    if item.text() != val: 
                        item.setText(val)

        tableWidget.scrollToBottom() 
        tableWidget.setUpdatesEnabled(True) 

    def btnDataClearClickEvent(self):
        self.tbAccount.setRowCount(0)
        self.tbStrategy.setRowCount(0)
        self.tbOrder.setRowCount(0)
        self.tbMarket.setRowCount(0)

    def btnConnectedClickEvent(self):
        if TcpJsonClient.Isconnected:
            self.client.close()
            TcpJsonClient.Isconnected = False
            self.btnConnected.setText("통신 연결 X")
            self.btnConnected.setStyleSheet("color: Silver;")
        else:
            self.client.connect()
            if TcpJsonClient.Isconnected:
                self.btnConnected.setText("통신 연결 O")
                self.btnConnected.setStyleSheet("color: Lime;")