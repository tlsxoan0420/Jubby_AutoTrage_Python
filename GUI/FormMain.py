# =====================================================================
# [1] 필요한 '마법 도구'들을 창고에서 꺼내옵니다.
# =====================================================================
from PyQt5 import QtWidgets, uic, QtCore, QtGui  # 화면을 그리고 단축키를 만드는 도구
from PyQt5.QtCore import Qt, QThread, pyqtSignal # 💡 [중요] 렉 방지용 '일꾼(Thread)'과 연락용 '무전기(Signal)'
import sys
import pandas as pd        # 표(Table) 데이터를 엑셀처럼 다루는 도구
import numpy as np         # AI 계산을 위한 수학 도구
import random
import joblib              # 우리가 만든 'AI 뇌(pkl)'를 깨우는 도구
import os                  # 파일 경로를 찾는 도구
import time                # "잠깐 쉬어!" 라고 명령하는 도구
from datetime import datetime # "지금 몇 시야?" 시계를 보는 도구

# [경로 설정] 우리가 직접 만든 부품들을 가져옵니다.
from COMMON.Flag import TradeData            # 💡 C#과 통신할 때 쓰는 '진짜 데이터 바구니'
from COM.TcpJsonClient import TcpJsonClient  # 완성된 데이터를 C#으로 쏴주는 '통신병'
from COMMON.KIS_Manager import KIS_Manager   # 증권사 서버와 대화하는 '영업 매니저'


# ✨ [종목 번역 사전] 증권사 API는 '005930' 같은 코드만 줍니다.
# 우리가 화면이나 로그를 볼 때 "어? 이게 무슨 종목이지?" 하지 않도록 이름을 붙여주는 사전입니다.
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
# ⚙️ [핵심 부품] 렉 방지용 백그라운드 일꾼 (AutoTradeWorker)
# 👩‍🏫 과외 쌤의 설명: 왜 일꾼이 필요한가요?
# 파이썬 화면(UI)은 아주 예민해서, 데이터 수집처럼 시간이 걸리는 일을 시키면
# "나 일하느라 바빠!" 하면서 마우스 클릭도 안 먹히고 화면이 하얗게 굳어버립니다(렉).
# 그래서 화면 뒤에서 '매매만 전담'할 그림자 일꾼(QThread)을 따로 고용하는 것입니다.
# =====================================================================
class AutoTradeWorker(QThread):
    # 📡 [무전기 채널 설정] 일꾼은 화면을 직접 건드리면 안 됩니다. (에러 발생의 주원인!)
    # 그래서 일꾼이 데이터를 다 구하면 대장(FormMain)에게 "대장! 무전 쏠 테니 화면 좀 그려줘!" 라고 신호(Signal)를 보냅니다.
    
    # 👩‍🏫 주목! 여기가 에러의 원인이었던 곳입니다.
    # pyqtSignal(str, str)의 의미는 "나는 문자열(str) 2개를 대장에게 보낼 거야!" 라는 약속입니다.
    # (첫 번째 str: 로그 내용 / 두 번째 str: 로그 색상이나 종류(info, success 등))
    sig_log = pyqtSignal(str, str)        # 로그창에 글씨 써달라는 무전
    sig_account_df = pyqtSignal(object)   # 계좌 표 그려달라는 무전 (표 덩어리를 object로 보냄)
    sig_strategy_df = pyqtSignal(object)  # 전략 표 그려달라는 무전
    sig_sync_cs = pyqtSignal()            # C#으로 데이터 쏴달라는 무전 (인자 없음)

    def __init__(self, main_window):
        super().__init__()
        self.mw = main_window   # 메인 화면(대장)의 기능들을 빌려 쓰기 위해 끈으로 연결해 둡니다.
        self.is_running = False # 이 일꾼이 지금 일하고 있는지 확인하는 스위치입니다.

    def run(self):
        """🚀 [일꾼의 메인 일터] '가동' 버튼을 누르면 이 함수가 무한 반복됩니다."""
        self.is_running = True
        while self.is_running:
            self.process_trading() # 아래에 정의한 '진짜 매수/매도 로직'을 1바퀴 돌립니다.
            
            # 💡 [중요 스킬] 1분을 쉽니다. 하지만 60초를 통째로 자버리면 중간에 '정지'를 눌러도 안 꺼집니다.
            # 그래서 1초씩 60번을 쪼개서 쉬면서 "대장이 그만하래?" 하고 매초 눈치를 봅니다.
            for _ in range(60):
                if not self.is_running: break 
                time.sleep(1)

    def process_trading(self):
        """🧠 주삐의 '진짜 뇌'가 작동하는 핵심 로직입니다."""
        now = datetime.now() # 지금 몇 시인지 시계를 봅니다.
        
        # 🚨 [시간 규칙 1] 오후 3시 20분 "무조건 강제 청산!"
        # 장 마감 직전에 모든 주식을 다 팔아서 '오버나잇(다음날로 넘기기)' 위험을 제거합니다.
        if now.hour == 15 and now.minute >= 20:
            if len(self.mw.my_holdings) > 0: 
                # 👩‍🏫 무전(Signal) 사용법: .emit(내용, 종류) -> 문자열 2개를 잘 보내고 있죠?
                self.sig_log.emit("⏰ [장 마감 임박] 오후 3시 20분입니다! 전 종목 강제 청산 시작!", "error")
                for code, info in list(self.mw.my_holdings.items()):
                    self.mw.api_manager.sell(code, info['qty'])
                    del self.mw.my_holdings[code] 
                self.sig_log.emit("✅ 강제 청산 완료. 내일 기분 좋게 다시 만나요!", "success")
                
                # 표가 깨지지 않게 '이름표'가 살아있는 빈 깡통을 C#에 보냅니다.
                empty_df = pd.DataFrame(columns=['종목코드','종목명','보유수량','평균매입가','평가손익','주문가능금액'])
                self.sig_account_df.emit(empty_df)
                self.sig_sync_cs.emit()
            return # 강제 청산 시간엔 쇼핑(매수)을 하면 안 되니까 여기서 함수를 끝내버립니다!

        # 💰 [철칙 설정] 안정형 단타 모드의 규칙들
        MAX_STOCKS = 10     # 지갑에 최대 10개 종목만 담겠다!
        TAKE_PROFIT = 3.0   # +3.0% 수익 나면 익절(기분 좋게 팔기)!
        STOP_LOSS = -1.5    # -1.5% 떨어지면 손절(눈물을 머금고 팔기)!
        SCAN_POOL = list(STOCK_DICT.keys()) # 20개 관심 종목 코드만 쏙 가져오기

        # ---------------------------------------------------------
        # 🚨 STEP 0: 기존 주식 이어달리기 & 매도 감시 (무조건 1순위 실행!)
        # 💡 프로그램을 껐다 켜도, 새로 사기 전에 내가 들고 있는 것부터 살핍니다.
        # ---------------------------------------------------------
        account_rows = [] # 파이썬 화면의 '표'에 그릴 데이터를 임시로 담는 바구니
        
        if len(self.mw.my_holdings) > 0: 
            sold_codes = [] # 이번에 팔기로 결정한 녀석들의 명단 (나중에 지갑에서 지우기 위함)
            
            for code, info in self.mw.my_holdings.items():
                buy_price = info['price'] # 내가 산 가격
                buy_qty = info['qty']     # 내가 산 개수
                
                # 1. 증권사 서버에 "얘 지금 얼마야?" 하고 1분봉 차트를 물어봅니다.
                df = self.mw.api_manager.fetch_minute_data(code)
                if df is None: continue 
                curr_price = df.iloc[-1]['close'] # 가장 마지막 봉의 종가 = 현재가
                
                # 2. 내 진짜 수익률 계산 (수학: (현재가-매수가)/매수가 * 100)
                profit_rate = ((curr_price - buy_price) / buy_price) * 100
                
                # 3. AI 변심 체크: "주삐야, 이거 아직도 오를 확률 40% 이상이야?"
                current_prob, _ = self.mw.get_ai_probability(code)
                stock_name = STOCK_DICT.get(code, f"알수없음_{code}")

                # 💡 [매도 판단 방아쇠] 팔아야 할 타이밍인지 확인하는 스위치
                is_sell = False
                status_msg = ""

                if profit_rate >= TAKE_PROFIT:     # +3% 달성 (수익!)
                    is_sell = True
                    status_msg = f"📈 기계적 익절 (+{profit_rate:.2f}%)"
                elif profit_rate <= STOP_LOSS:     # -1.5% 도달 (손해 ㅠㅠ)
                    is_sell = True
                    status_msg = f"📉 기계적 손절 ({profit_rate:.2f}%)"
                elif current_prob < 0.4:           # AI가 "이거 망했어! 추락할 확률이 더 높아" 라고 함
                    is_sell = True
                    status_msg = f"🤖 AI 위험 감지 손절 (상승확률 {current_prob*100:.1f}% 추락)"

                # 팔기로 마음먹었다면? 시장가로 즉시 던집니다!
                if is_sell:
                    success = self.mw.api_manager.sell(code, buy_qty) 
                    if success: 
                        sold_codes.append(code) # 팔았으니까 '지워야 할 명단'에 추가
                        self.sig_log.emit(f"====================================", "warning")
                        self.sig_log.emit(f"{status_msg} -> [{stock_name}] 매도 실행!", "warning")
                        self.sig_log.emit(f"====================================", "warning")
                else:
                    # 아직 안 팔았으면 화면 표에 띄울 데이터를 바구니에 담아둡니다.
                    account_rows.append({
                        '종목코드': code, '종목명': stock_name, '보유수량': buy_qty, 
                        '평균매입가': f"{buy_price:,.0f}", '평가손익': f"{profit_rate:.2f}%", '주문가능금액': 0
                    })
                        
            # 다 판 놈들은 내 지갑(my_holdings)에서 완전히 파냅니다.
            for code in sold_codes:
                del self.mw.my_holdings[code]

        # ---------------------------------------------------------
        # 🚨 [시간 규칙 2] 오후 3시 이후 매수 금지!
        # ---------------------------------------------------------
        if now.hour >= 15:
            self.sig_log.emit("⏰ 오후 3시가 넘었습니다. 쇼핑(매수)은 멈추고 감시만 합니다.", "info")
            self._update_account_ui(account_rows) # 내 계좌 표만 갱신해주고 매수는 생략!
            return 

        # ---------------------------------------------------------
        # 🔍 STEP 1: 지갑 빈자리 파악 & 💰 완벽한 N빵 자금 배분!
        # ---------------------------------------------------------
        current_count = len(self.mw.my_holdings) 
        needed_count = MAX_STOCKS - current_count # 10자리 중 빈자리가 몇 개인가?
        
        # ✨ [N빵 로직] 증권사에 내 진짜 예수금(쓸 수 있는 돈)을 물어봅니다.
        my_cash = self.mw.api_manager.get_balance() or 0
        cash_str = f"{my_cash:,}" 
        
        # 계좌 표에 내 예수금과 들고 있는 주식들을 찍어줍니다.
        self._update_account_ui(account_rows, cash_str)

        if needed_count <= 0: # 10개 꽉 찼으면 살 필요가 없죠?
            self.sig_log.emit(f"✅ 포트폴리오 꽉 참 ({MAX_STOCKS}/10). 수익률 감시 중...", "info")
            return 
            
        # ✨ [핵심] 남은 내 돈을 빈자리 개수로 똑같이 나눕니다!
        # 돈이 300만원 있고 3자리 남았으면? 종목당 100만원씩 쇼핑하자!
        BUDGET_PER_STOCK = my_cash // needed_count

        self.sig_log.emit(f"🔎 빈자리 {needed_count}개. 타겟 스캔... (종목당 {BUDGET_PER_STOCK:,}원 배분)", "info")

        # 돈이 너무 적으면 스캔을 안 합니다 (예: 1만원 이하면 1주도 못 살 수 있으니까요)
        if BUDGET_PER_STOCK < 10000:
            self.sig_log.emit("⚠️ 현금이 너무 부족합니다. 추가 매수를 중단합니다.", "error")
            return

        # 🎯 20개 종목을 AI에게 보여주며 "얘 어때?" 라고 물어봅니다.
        candidates = [] 
        for code in SCAN_POOL:
            if code in self.mw.my_holdings: continue # 이미 산 놈은 패스!
            
            prob, curr_price = self.mw.get_ai_probability(code)
            # 확률이 60% 이상(0.6)이면 장바구니 후보에 담습니다.
            if prob >= 0.6: 
                candidates.append({'code': code, 'prob': prob, 'price': curr_price})
            time.sleep(0.2) # 증권사 서버가 화내지 않게 0.2초씩 쉬면서 물어보기!
        
        # 1등부터 꼴등까지 '상승 확률(prob)'을 기준으로 줄 세웁니다. (reverse=True : 내림차순)
        candidates = sorted(candidates, key=lambda x: x['prob'], reverse=True)

        # AI의 추천 목록을 '전략 표(Strategy Table)'에 띄울 준비를 합니다.
        strategy_rows = []
        for target in candidates[:10]: # 상위 10개만 보여줍니다.
            stock_name = STOCK_DICT.get(target['code'], "알수없음")
            strategy_rows.append({
                '종목코드': target['code'], '종목명': stock_name, 'MA_5': 0, 'MA_20': 0, 'RSI': 0, 
                'MACD': f"{target['prob']*100:.1f}%", '전략신호': "BUY 🟢" if target['prob'] >= 0.6 else "WAIT 🟡" 
            })
            
        # 화면 대장에게 무전 쏘기 (전략 표 그려줘!)
        if strategy_rows:
            self.sig_strategy_df.emit(pd.DataFrame(strategy_rows))
        else:
            # 텅 비었더라도 제목(컬럼명)이 안 날아가게 이름표가 붙은 깡통 보내기
            self.sig_strategy_df.emit(pd.DataFrame(columns=['종목코드','종목명','MA_5','MA_20','RSI','MACD','전략신호']))

        # ---------------------------------------------------------
        # 🛒 STEP 2: 상위 랭커부터 야무지게 매수!
        # ---------------------------------------------------------
        if not candidates:
            self.sig_log.emit("🤔 상승 확률 60% 이상인 꿀벌 종목이 없네요. 관망합니다.", "info")
            return

        # 빈자리 개수(needed_count)만큼만, 1등부터 순서대로 시장가 매수!
        for i in range(min(needed_count, len(candidates))):
            target = candidates[i]
            code = target['code']
            curr_price = target['price']
            stock_name = STOCK_DICT.get(code, code) 
            
            # 아까 N빵 한 예산으로 몇 주 살 수 있는지 계산 (소수점 버림)
            buy_qty = int(BUDGET_PER_STOCK / curr_price)
            
            if buy_qty > 0:
                # 한국투자증권에 "시장가로 이만큼 사주세요!" 요청
                success = self.mw.api_manager.buy_market_price(code, buy_qty)
                if success:
                    # 매수에 성공했으면 내 지갑(my_holdings)에 바로 적어둡니다.
                    self.mw.my_holdings[code] = {'price': curr_price, 'qty': buy_qty}
                    
                    # 🛠️ [에러 해결 부분] 👩‍🏫 여기에 두 번째 인자인 "success" (또는 "info") 색상 코드를 넣어야 에러가 안 납니다!
                    self.sig_log.emit(f"🛒 [AI 매수] {stock_name} (상승확률: {target['prob']*100:.1f}%)", "info")
                    self.sig_log.emit(f"💸 {buy_qty}주 ({curr_price * buy_qty:,}원어치) 매수 완료!", "success")

        # ✨ 모든 쇼핑과 업데이트가 끝났으니, C# 대시보드 화면에도 이 정보를 통째로 전송하라고 무전 칩니다!
        self.sig_sync_cs.emit()


    # 🛠️ (내부 보조 함수) 계좌 표 업데이트용 무전 담당
    # 👩‍🏫 여러 줄의 계좌 데이터 중, '주문가능금액(내 예수금)'은 맨 윗줄 한 번만 보여주는 예쁜 UI를 위한 함수입니다.
    def _update_account_ui(self, account_rows, cash_str="0"):
        if len(account_rows) > 0:
            for row in account_rows: row['주문가능금액'] = "" # 전부 다 뜨면 지저분하니 일단 다 빈칸으로 만들고
            account_rows[0]['주문가능금액'] = cash_str      # 맨 윗줄(0번째 줄)에만 내 예수금을 딱 적어줍니다.
            self.sig_account_df.emit(pd.DataFrame(account_rows))
        else:
            empty_df = pd.DataFrame(columns=['종목코드','종목명','보유수량','평균매입가','평가손익','주문가능금액'])
            self.sig_account_df.emit(empty_df)
        self.sig_sync_cs.emit()


# =====================================================================
# 🖥️ 메인 UI 클래스 (FormMain) - 지휘통제실이자 화면을 그리는 대장입니다!
# =====================================================================
class FormMain(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.initUI() # 껍데기(UI) 그리기 공사 시작

        # [AI 두뇌 이식] 머신러닝/딥러닝으로 공부한 데이터(.pkl)를 머리에 꽂아줍니다.
        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(root, "jubby_brain.pkl")
            self.model = joblib.load(model_path)
            self.add_log("🧠 AI 두뇌(jubby_brain.pkl) 이식 완료!", "success")
        except Exception as e:
            self.add_log(f"⚠️ AI 뇌 로드 실패: {e}", "error")

        # [매니저 고용] 증권사(한국투자증권) API 서버에 로그인하고 통신할 매니저를 세팅합니다.
        self.api_manager = KIS_Manager(ui_main=self)
        self.api_manager.start_api() 

        # 내 지갑(보유종목) 보관함 딕셔너리 { "005930": {"price": 70000, "qty": 10} ... }
        self.my_holdings = {} 

        # ⚙️ [핵심] 아까 위에서 우리가 열심히 만든 '렉 방지용 일꾼(AutoTradeWorker)'을 고용합니다.
        self.trade_worker = AutoTradeWorker(main_window=self)
        
        # 📡 일꾼의 무전기(Signal) 채널을 대장(FormMain)의 행동(Slot)에 연결합니다!
        # "무전기가 울리면 -> 내가 이 행동을 할게!" 라고 약속하는 부분입니다.
        self.trade_worker.sig_log.connect(self.add_log)                                # 무전: "로그 써줘" -> 대장: 로그 작성
        self.trade_worker.sig_account_df.connect(self.update_account_table_slot)       # 무전: "계좌 그려" -> 대장: 표 그리기
        self.trade_worker.sig_strategy_df.connect(self.update_strategy_table_slot)     # 무전: "전략 그려" -> 대장: 표 그리기
        self.trade_worker.sig_sync_cs.connect(self.btnDataSendClickEvent)              # 무전: "C# 쏴줘"   -> 대장: C# 전송

        # 마우스로 창을 잡고 드래그해서 움직일 수 있도록 돕는 변수들
        self._isDragging = False
        self._startPos = QtCore.QPoint()

        # 💡 [핵심: 이어달리기] 프로그램 켜자마자 내 진짜 계좌를 털어옵니다!
        # 여기서 털어온 정보가 my_holdings에 들어가서 나중에 'GO' 누를 때 1순위로 검사됩니다.
        self.load_real_holdings()


    def load_real_holdings(self):
        """증권사 서버에서 내 주식들을 훔쳐오고, 화면에 수익률을 예쁘게 띄웁니다."""
        try:
            self.my_holdings = self.api_manager.get_real_holdings()
            self.add_log(f"💼 [잔고 동기화] {len(self.my_holdings)}개 종목 로드 완료. (이어달리기 준비 끝!)", "success")
        except Exception as e:
            self.add_log(f"⚠️ 잔고 로드 에러: {e}", "error")
            return

        # 내 예수금(현금)도 물어봅니다.
        my_cash = self.api_manager.get_balance()
        cash_str = f"{my_cash:,}" if my_cash is not None else "0"

        account_rows = []
        is_first = True
        
        for code, info in self.my_holdings.items():
            buy_price = info['price']
            buy_qty = info['qty']
            stock_name = STOCK_DICT.get(code, f"알수없음_{code}")
            
            # 💡 켜자마자 수익률을 0%로 두면 섭섭하니까 현재가를 한 번 싹 긁어와서 계산합니다.
            df = self.api_manager.fetch_minute_data(code)
            pnl_str = "0.00%"
            if df is not None:
                curr_price = df.iloc[-1]['close']
                profit_rate = ((curr_price - buy_price) / buy_price) * 100
                pnl_str = f"{profit_rate:.2f}%"

            account_rows.append({
                '종목코드': code, '종목명': stock_name, '보유수량': buy_qty, 
                '평균매입가': f"{buy_price:,.0f}", '평가손익': pnl_str,
                '주문가능금액': cash_str if is_first else "" # 맨 윗줄에만 현금 표시
            })
            is_first = False
            
        if account_rows:
            TradeData.account.df = pd.DataFrame(account_rows)
            # 👩‍🏫 창이 켜지는 중이라 바로 그리면 뻑이 날 수 있어서 0.5초(500ms) 여유를 주고 그립니다.
            QtCore.QTimer.singleShot(500, lambda: self.update_table(self.tbAccount, TradeData.account.df))


    def initUI(self):
        """화면에 버튼과 표를 배치하고 어두운 배경색을 입히는 인테리어 구역입니다."""
        uic.loadUi("GUI/Main.ui", self)
        # C# UI 프로그램과 통신할 9001번 포트의 소켓 통신병을 세팅합니다.
        self.client = TcpJsonClient(host="127.0.0.1", port=9001)

        self.setWindowFlags(QtCore.Qt.FramelessWindowHint) # 윈도우의 기본 테두리(X, 최대화 버튼 있는 바) 제거
        self.setGeometry(0, 0, 1920, 1080) # 화면 크기를 1920x1080으로 꽉 차게!
        self.centralwidget.setStyleSheet("background-color: rgb(5,5,15);") # 다크 모드 배경색

        # ✨ [핵심 연동] 표 제목을 그릴 때, 우리 데이터 바구니(Flag.py)의 한글 제목을 그대로 가져옵니다!
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

        # 오른쪽 로그창 세팅
        self.txtLog = QtWidgets.QPlainTextEdit(self.centralwidget)
        self.txtLog.setGeometry(1430, 95, 485, 930)
        self.txtLog.setReadOnly(True) # 타이핑해서 못 바꾸게 읽기 전용으로!
        self.txtLog.setStyleSheet("background-color: rgb(20, 30, 45); color: white; font-family: Consolas; font-size: 13px;")
        
        # 🚨 [수동 저장] 로그창 클릭을 가로채서 Ctrl+클릭 시 메모장에 저장!
        self.txtLog.mousePressEvent = self.custom_log_mouse_press

        # 상단 네비게이션 버튼들 생성
        self.btnDataCreatTest = self._create_nav_button("데이터 생성 테스트", 5)
        self.btnDataSendTest = self._create_nav_button("C# 데이터 전송", 310)
        self.btnSimulDataTest = self._create_nav_button("계좌 잔고 조회", 615)
        self.btnAutoDataTest = self._create_nav_button("자동 매매 가동 (GO)", 920)
        self.btnDataClearTest = self._create_nav_button("화면 데이터 초기화", 1225)
        
        self.btnClose = QtWidgets.QPushButton(" X ", self.centralwidget)
        self.btnClose.setGeometry(1875, 5, 40, 40)
        self.btnClose.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")

        self.btnConnected = QtWidgets.QPushButton("통신 연결 X", self.centralwidget)
        self.btnConnected.setGeometry(1430, 50, 485, 40)
        self.btnConnected.setStyleSheet("background-color: rgb(5,5,15); color: Silver; border: 1px solid Silver;")

        # 버튼 클릭 시 실행될 함수(이벤트) 연결
        self.btnDataCreatTest.clicked.connect(self.btnDataCreatClickEvent)
        self.btnDataSendTest.clicked.connect(self.btnDataSendClickEvent)
        self.btnSimulDataTest.clicked.connect(self.btnSimulTestClickEvent)
        self.btnAutoDataTest.clicked.connect(self.btnAutoTradingSwitch)
        self.btnDataClearTest.clicked.connect(self.btnDataClearClickEvent)
        self.btnClose.clicked.connect(self.btnCloseClickEvent)
        self.btnConnected.clicked.connect(self.btnConnectedClickEvent)

        # 🚨 비상 탈출 단축키 (Ctrl+Shift+W) -> 누르면 강제 시장가 매도!
        self.shortcut_sell = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Shift+W"), self)
        self.shortcut_sell.activated.connect(self.emergency_sell_event)


    def custom_log_mouse_press(self, event):
        """로그창을 Ctrl + 왼쪽 클릭하면 현재까지의 로그가 메모장 파일로 저장됩니다."""
        if event.button() == Qt.LeftButton and event.modifiers() == Qt.ControlModifier:
            text = self.txtLog.toPlainText() 
            if not text.strip(): return 
            os.makedirs("Logs", exist_ok=True) # Logs라는 폴더가 없으면 만들어라!
            now_str = datetime.now().strftime("%Y%m%d_%H%M%S") # 20260305_101530 처럼 파일명 생성
            filename = f"Logs/Manual_Log_{now_str}.txt" 
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            self.add_log(f"💾 [저장 성공] 현재 로그가 {filename} 로 찰칵! 캡처되었습니다.", "success")
        else:
            # Ctrl키 안 누르고 그냥 클릭했으면 원래 파이썬이 하던 클릭 동작을 그대로 해라.
            QtWidgets.QPlainTextEdit.mousePressEvent(self.txtLog, event)


    def emergency_sell_event(self):
        """표에서 종목을 누르고 단축키를 누르면 당장 내다 팝니다!"""
        selected_ranges = self.tbAccount.selectedRanges() 
        if not selected_ranges:
            self.add_log("⚠️ 매도할 종목을 'Account 표'에서 클릭해주세요.", "warning")
            return
            
        row = selected_ranges[0].topRow() # 내가 클릭한 줄의 번호
        item = self.tbAccount.item(row, 0) # 그 줄의 0번째 칸 (보통 종목코드 자리)
        if item is None: return
        code = item.text() # 종목 코드 텍스트 가져오기
        
        if code in self.my_holdings:
            qty = self.my_holdings[code]['qty']
            success = self.api_manager.sell(code, qty) 
            if success:
                del self.my_holdings[code]     # 지갑에서 삭제
                self.tbAccount.removeRow(row)  # 화면 표에서도 그 줄을 지워버림
                stock_name = STOCK_DICT.get(code, code)
                self.add_log(f"🚨 [비상 탈출] {stock_name} {qty}주 수동 매도 완료!", "error")
                self.btnDataSendClickEvent()   # C#에도 팔았다고 알려줍니다.
        else:
            self.add_log(f"⚠️ 이미 팔았거나 지갑에 없는 종목입니다: {code}", "error")


    def btnAutoTradingSwitch(self):
        """'GO' 버튼을 누르면 일꾼을 깨워서 일을 시키고, 'STOP'을 누르면 재웁니다."""
        if not self.trade_worker.is_running: # 일꾼이 자고 있으면?
            self.trade_worker.start() # 🚀 일어나서 일해! (Thread의 run 함수 실행)
            self.btnAutoDataTest.setText("자동 매매 중단 (STOP)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(70, 10, 10); color: Lime; font-weight: bold;")
            self.add_log("🚀 [주삐 엔진] 1분 단위 스레드 가동! (기존 주식 감시부터 시작합니다)", "success")
        else: # 이미 일하고 있으면?
            self.trade_worker.is_running = False # 그만하고 집에 가! (while 반복문 탈출)
            self.trade_worker.quit() 
            self.btnAutoDataTest.setText("자동 매매 가동 (GO)")
            self.btnAutoDataTest.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
            self.add_log("🛑 [주삐 엔진] 감시를 멈춥니다.", "warning")


    def get_ai_probability(self, code):
        """차트 데이터를 AI에게 던져주고 '오를 확률'을 받아오는 함수입니다."""
        df = self.api_manager.fetch_minute_data(code) 
        if df is None or len(df) < 30: return 0.0, 0 

        # 👩‍🏫 보조지표를 수학적으로 계산하는 과정입니다. 
        # (수익률, 거래량 변화, RSI, MACD, 볼린저밴드 하단 등)
        df['return'] = df['close'].pct_change()
        df['vol_change'] = df['volume'].pct_change()
        delta = df['close'].diff()
        up, down = delta.copy(), delta.copy()
        up[up < 0] = 0; down[down > 0] = 0
        df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.abs().ewm(com=13).mean())))
        df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        df['MA20'] = df['close'].rolling(20).mean()
        df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)
        
        # 최신(가장 아래쪽) 줄만 가져오되 비어있는 값(NaN)은 0으로 채웁니다.
        curr = df.iloc[-1].fillna(0).replace([np.inf, -np.inf], 0)
        curr_price = curr['close'] 
        
        # AI 모델이 공부했던 항목 순서대로 맞춰서 데이터를 넣어줍니다.
        features = ['return', 'vol_change', 'RSI', 'MACD', 'BB_Lower']
        X = curr[features].values.reshape(1, -1)
        prob = self.model.predict_proba(X)[0][1] # "이 차트 75% 확률로 오릅니다!" 라는 숫자를 뱉어냅니다.
        
        return prob, curr_price 


    # =================================================================
    # 📡 무전 수신처(Slot) : 일꾼이 무전을 칠 때 실행되는 함수들입니다!
    # =================================================================
    
    @QtCore.pyqtSlot(object) 
    def update_account_table_slot(self, df):
        # 무전기로 받은 df(표 데이터)를 Flag.py 저장소에 넣고 화면에 그립니다.
        TradeData.account.df = df
        self.update_table(self.tbAccount, df)

    @QtCore.pyqtSlot(object) 
    def update_strategy_table_slot(self, df):
        TradeData.strategy.df = df
        self.update_table(self.tbStrategy, df)

    @QtCore.pyqtSlot(str, str) 
    def add_log(self, text, log_type="info"):
        # 👩‍🏫 아까 AutoTradeWorker에서 보냈던 두 번째 인자("success", "error" 등)가
        # 여기서 log_type으로 들어옵니다. 그에 맞춰 글씨 색상을 HTML로 예쁘게 바꿔줍니다.
        color = {"info": "white", "success": "lime", "warning": "yellow", 
                 "error": "red", "send": "cyan", "recv": "orange"}.get(log_type, "white")
        now = datetime.now().strftime("[%H:%M:%S]")
        html_message = f'<span style="color:{color}">{now} {text}</span>'
        
        # 스레드 안전성(UI 안 뻗게 하기)을 위해 QTimer로 던져서 그립니다.
        QtCore.QTimer.singleShot(0, lambda: self._safe_append_log(html_message))

    def _safe_append_log(self, html_msg):
        self.txtLog.appendHtml(html_msg)
        # 로그가 길어지면 스크롤 바를 자동으로 맨 아래로 쫙 내려주는 센스!
        self.txtLog.verticalScrollBar().setValue(self.txtLog.verticalScrollBar().maximum())

    # =================================================================
    # 🎨 화면 꾸미기 및 기본 보조 기능 (여기는 손댈 필요 없습니다!)
    # =================================================================
    def _setup_table(self, table, columns):
        table.setColumnCount(len(columns))
        table.setHorizontalHeaderLabels(columns)
        self.style_table(table)

    def style_table(self, table):
        table.setFont(QtGui.QFont("Noto Sans KR", 12))
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch) # 칸 너비 꽉 차게 조절
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)  # 클릭하면 줄 전체가 선택되게
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection) # 다중 선택 금지
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)   # 더블클릭해서 값 수정하는거 금지
        table.setStyleSheet("""
            QTableWidget { background-color: rgb(50,80,110); color: Black; selection-background-color: rgb(80, 120, 160); } 
            QHeaderView::section { background-color: rgb(40,60,90); color: Black; font-weight: bold; }
        """)

    def _create_nav_button(self, text, x_pos):
        # 상단 메뉴 버튼들을 공장에서 찍어내듯 만드는 함수입니다.
        btn = QtWidgets.QPushButton(text, self.centralwidget)
        btn.setGeometry(x_pos, 5, 300, 40)
        btn.setStyleSheet("background-color: rgb(5,5,15); color: Silver;")
        btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor)) # 마우스 올리면 손가락 모양으로 변경
        btn.installEventFilter(self) 
        return btn

    def eventFilter(self, source, event):
        # 버튼 위에 마우스가 올라가면 텍스트가 연두색(Lime)으로 빛나게 하는 효과!
        if event.type() == QtCore.QEvent.Enter: source.setStyleSheet("background-color: rgb(5,5,10); color: Lime;")
        elif event.type() == QtCore.QEvent.Leave: source.setStyleSheet("background-color: rgb(5,5,10); color: Silver;")
        return super().eventFilter(source, event)

    # 마우스로 상단 빈 공간을 드래그해서 창을 옮길 수 있도록 해주는 이벤트들입니다.
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._isDragging = True
            self._startPos = event.globalPos() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, event):
        if self._isDragging: self.move(event.globalPos() - self._startPos)
    def mouseReleaseEvent(self, event): self._isDragging = False

    def btnSimulTestClickEvent(self): self.api_manager.check_my_balance() 
    def btnCloseClickEvent(self): QtWidgets.QApplication.quit()           

    # 🎲 [개조 완료!] 데이터 생성 테스트 버튼을 누르면 부드럽게 이어지는 트렌드 데이터를 만듭니다.
    def btnDataCreatClickEvent(self):
        """'데이터 생성 테스트' 버튼을 누르면 '누적형' 랜덤 가짜 데이터를 쫙 뿌려줍니다."""
        # 1. 4개 표의 가짜 데이터를 '기존 데이터 끝에 덧붙여서' 생성합니다! (부드러운 그래프의 비결)
        TradeData.market.generate_mock_data()
        TradeData.account.generate_mock_data()
        TradeData.order.generate_mock_data()
        TradeData.strategy.generate_mock_data()
        
        # 2. 업데이트된 표를 화면에 다시 그립니다.
        self.update_table(self.tbMarket, TradeData.market.df)
        self.update_table(self.tbAccount, TradeData.account.df)
        self.update_table(self.tbOrder, TradeData.order.df)
        self.update_table(self.tbStrategy, TradeData.strategy.df)
        
        self.add_log("🎲 부드럽게 이어지는 '트렌드 가짜 데이터' 생성 및 전송 완료!", "success")
        
        # 3. 방금 만든 화려한 데이터를 C#으로 즉시 쏴봅니다! (이제 그래프가 부드럽게 나옵니다)
        self.btnDataSendClickEvent()

    @QtCore.pyqtSlot() 
    def btnDataSendClickEvent(self):
        """C# 화면에 표 데이터를 싹 다 전송합니다."""
        if TcpJsonClient.Isconnected:
            self.client.send_message("market", TradeData.market_dict())
            self.client.send_message("account", TradeData.account_dict())
            self.client.send_message("strategy", TradeData.strategy_dict())

    def update_table(self, table, df):
        """판다스 엑셀 표를 화면의 QTableWidget으로 옮겨 적는 노가다 함수입니다."""
        table.clearContents()
        table.setRowCount(len(df))
        if len(df.columns) > 0:
            table.setColumnCount(len(df.columns))
            table.setHorizontalHeaderLabels(df.columns)
        for i in range(len(df)):
            for j in range(len(df.columns)):
                item = QtWidgets.QTableWidgetItem(str(df.iloc[i, j]))
                item.setTextAlignment(QtCore.Qt.AlignCenter) # 가운데 정렬!
                table.setItem(i, j, item)

    def btnDataClearClickEvent(self):
        # 표 데이터들 전부 싹 지우기 (초기화)
        self.tbAccount.setRowCount(0)
        self.tbStrategy.setRowCount(0)
        self.tbOrder.setRowCount(0)
        self.tbMarket.setRowCount(0)

    def btnConnectedClickEvent(self):
        # C# 프로그램이랑 통신을 연결하거나 끊는 스위치 역할입니다.
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