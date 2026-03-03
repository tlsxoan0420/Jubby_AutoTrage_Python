import requests # 인터넷(HTTP)을 통해 서버와 통신하기 위한 라이브러리
import json     # 데이터를 주고받을 때 사용하는 JSON 형식을 다루는 라이브러리

class KIS_API:
    # 클래스가 처음 생성될 때 실행되는 초기화 함수입니다.
    def __init__(self, app_key, app_secret, account_no, is_mock=True):
        self.app_key = app_key          # 한국투자증권에서 발급받은 APP KEY
        self.app_secret = app_secret    # 한국투자증권에서 발급받은 APP SECRET
        self.account_no = account_no    # 본인의 주식 계좌번호 (앞 8자리 문자열)
        self.is_mock = is_mock          # 모의투자 모드인지 실전 모드인지 결정 (True = 모의)
        
        # 모의투자와 실전투자는 접속해야 하는 서버 주소(URL)가 다릅니다.
        if self.is_mock:
            self.base_url = "https://openapivts.koreainvestment.com:29443" # 모의투자용 서버
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"     # 실전투자용 서버
            
        # 발급받은 토큰과 키를 저장해둘 변수들 (처음엔 빈 칸)
        self.access_token = ""
        self.approval_key = ""

    # =====================================================================
    # 1. 접근 토큰(Access Token) 발급 함수
    # 단발성 명령(잔고 조회, 주식 매수/매도 주문 등)을 내릴 때 필요한 "통행증"입니다.
    # =====================================================================
    def get_access_token(self):
        url = f"{self.base_url}/oauth2/tokenP" # 토큰을 발급해주는 URL 주소
        headers = {"content-type": "application/json"}
        
        # 서버에 보낼 데이터 (나의 Key와 Secret을 보내서 신원을 증명함)
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        # requests.post를 이용해 서버에 데이터를 '제출(Post)' 합니다.
        res = requests.post(url, headers=headers, data=json.dumps(body))
        
        if res.status_code == 200: # 200은 서버가 "OK(정상)" 라고 대답했다는 뜻
            self.access_token = res.json().get("access_token")
            print("[✅ 성공] KIS Access Token 발급 완료 (주문/조회용 통행증)")
            return self.access_token
        else:
            print(f"[❌ 실패] Token 발급 에러: {res.status_code} - {res.text}")
            return None

    # =====================================================================
    # 2. 웹소켓 접속키(Approval Key) 발급 함수
    # 실시간으로 쏟아지는 주가 데이터(웹소켓)를 받기 위해 필요한 전용 "통행증"입니다.
    # =====================================================================
    def get_approval_key(self):
        url = f"{self.base_url}/oauth2/Approval"
        headers = {"content-type": "application/json; utf-8"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret
        }
        
        res = requests.post(url, headers=headers, data=json.dumps(body))
        if res.status_code == 200:
            self.approval_key = res.json().get("approval_key")
            print("[✅ 성공] KIS WebSocket Approval Key 발급 완료 (실시간 데이터용)")
            return self.approval_key
        else:
            print(f"[❌ 실패] Approval Key 발급 에러: {res.status_code} - {res.text}")
            return None

    # =====================================================================
    # 3. 계좌 잔고(예수금) 조회 함수 ✨ (새로 추가된 핵심 기능)
    # 내 계좌에 지금 당장 주식을 살 수 있는 돈(주문 가능 현금)이 얼마인지 확인합니다.
    # =====================================================================
    def get_account_balance(self):
        # 1. 통행증(Token)이 있는지 먼저 확인합니다. 없으면 조회가 불가능합니다.
        if not self.access_token:
            print("[에러] 통행증(Access Token)이 없습니다. get_access_token()을 먼저 실행하세요.")
            return None

        # 2. 매수 가능 금액을 조회하는 KIS 서버의 특정 주소
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        
        # 3. 서버에 보낼 헤더(Header) 정보 (편지 봉투에 적는 보내는 사람 정보 같은 것)
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}", # 발급받은 통행증을 여기에 넣음
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            # tr_id는 "어떤 작업을 할 것인가"를 나타내는 암호 코드입니다. (모의/실전 코드가 다름)
            "tr_id": "VTTC8908R" if self.is_mock else "TTTC8908R", 
            "custtype": "P" # P: 개인투자자
        }
        
        # 4. 서버에 보낼 상세 요청 조건 (편지 내용물)
        params = {
            "CANO": self.account_no[:8], # 종합계좌번호 앞 8자리 (예: 50001234)
            "ACNT_PRDT_CD": "01",        # 계좌상품코드 뒤 2자리 (주식 계좌는 보통 "01" 입니다)
            "PDNO": "",                  # 종목코드 (특정 종목을 지정하지 않고 전체 돈을 보려면 공란)
            "ORD_UNPR": "",              # 주문단가 (공란으로 둠)
            "ORD_DVSN": "01",            # 주문구분 (01: 시장가. 시장가로 샀을 때 얼마까지 살 수 있는지 계산)
            "CMA_EVLU_AMT_ICLD_YN": "N", # CMA 평가금액 포함 여부 (포함 안 함 "N")
            "OVRS_ICLD_YN": "N"          # 해외주식 포함 여부 (포함 안 함 "N")
        }
        
        # 5. 서버에 정보 조회를 요청합니다. (조회할 때는 get 방식을 사용)
        res = requests.get(url, headers=headers, params=params)
        
        # 6. 서버로부터 받은 답변(res) 확인
        if res.status_code == 200:
            data = res.json() # 서버가 준 데이터를 파이썬이 읽기 쉽게 변환
            
            if data['rt_cd'] == '0': # '0' 이면 조회가 성공적으로 완료되었다는 뜻
                # 서버가 보내준 엄청나게 많은 데이터 중 'ord_psbl_cash(주문 가능 현금)' 항목만 쏙 뽑아옵니다.
                cash = int(data['output']['ord_psbl_cash']) 
                print(f"[✅ 잔고 조회 성공] 현재 주문 가능한 모의투자 예수금: {cash:,}원")
                return cash
            else:
                # '0'이 아니면 뭔가 문제가 있다는 뜻이므로 서버가 보내준 에러 메시지를 출력합니다.
                print(f"[❌ 조회 실패] {data['msg1']}")
        else:
            print(f"[❌ 통신 에러] {res.status_code} - {res.text}")
        return None

    # =====================================================================
    # 4. 주식 시장가 매수/매도 주문 함수 ✨ (초단타의 핵심 무기)
    # 신호가 오면 즉시 시장가로 긁어서 빠르게 체결시킵니다.
    # =====================================================================
    def order_stock(self, stock_code, qty, is_buy=True):
        """
        주식 시장가 주문
        - stock_code: 종목코드 (예: 삼성전자 "005930")
        - qty: 주문 수량 (몇 주 살 건지)
        - is_buy: True면 매수(사는 것), False면 매도(파는 것)
        """
        if not self.access_token:
            print("[에러] 통행증(Access Token)이 없습니다.")
            return False

        # 주문을 넣는 서버 주소
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        # TR_ID 결정 (모의투자인지 실전인지, 매수인지 매도인지에 따라 코드가 다름)
        if self.is_mock:
            tr_id = "VTTC0802U" if is_buy else "VTTC0801U" # 모의 매수 / 모의 매도
        else:
            tr_id = "TTTC0802U" if is_buy else "TTTC0801U" # 실전 매수 / 실전 매도
            
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P"
        }
        
        # 주문 상세 내용 (시장가 주문)
        body = {
            "CANO": self.account_no[:8], # 계좌번호 앞 8자리
            "ACNT_PRDT_CD": "01",        # 계좌번호 뒤 2자리
            "PDNO": stock_code,          # 종목코드 (예: 005930)
            "ORD_DVSN": "01",            # 01: 시장가 (현재 시장에서 가장 빨리 사지는 가격)
            "ORD_QTY": str(qty),         # 주문 수량 (문자열로 보내야 함)
            "ORD_UNPR": "0"              # 시장가 주문이므로 가격은 0으로 세팅
        }
        
        # 서버로 주문서 전송 (Post 방식)
        res = requests.post(url, headers=headers, data=json.dumps(body))
        
        if res.status_code == 200:
            data = res.json()
            if data['rt_cd'] == '0':
                order_type = "매수(BUY)" if is_buy else "매도(SELL)"
                print(f"[💰 {order_type} 접수 완료] 종목: {stock_code} | 수량: {qty}주 (시장가)")
                print(f"[상세 메시지] {data['msg1']}")
                return True
            else:
                print(f"[❌ 주문 실패] {data['msg1']}")
        else:
            print(f"[❌ 통신 에러] {res.status_code} - {res.text}")
        return False


# ==========================================
# 여기부터는 파일 자체를 실행했을 때만 돌아가는 테스트 공간입니다.
# ==========================================
if __name__ == "__main__":
    # ⚠️ 본인의 정보 유지
    MY_APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    MY_APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    MY_ACCOUNT = "50172151"
    
    # 1. 주삐 KIS API 객체 생성
    print("🚀 주삐 주문 테스트를 시작합니다...")
    kis = KIS_API(MY_APP_KEY, MY_APP_SECRET, account_no=MY_ACCOUNT, is_mock=True)
    
    # 2. 토큰 발급 (필수)
    kis.get_access_token()
    
    # 3. 잔고 조회
    kis.get_account_balance()
    
    # 4. 🛒 매수 테스트: 삼성전자(005930) 1주를 시장가로 매수 (is_buy=True)
    # (장이 닫힌 상태면 '장종료' 또는 '주문거부' 등의 메시지가 뜰 수 있지만 통신 자체는 성공합니다!)
    print("\n--- [주문 테스트 진행] ---")
    kis.order_stock(stock_code="005930", qty=1, is_buy=True)