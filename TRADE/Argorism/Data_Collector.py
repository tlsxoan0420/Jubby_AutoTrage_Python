import sys
import os
import pandas as pd
import numpy as np
import requests
import time

# ---------------------------------------------------------------------
# 1. [파일 경로 설정] 파이썬에게 'COMMON' 폴더 위치를 알려줍니다.
# ---------------------------------------------------------------------
# 현재 파일 위치: TRADE/Argorism/Data_Collector_Ultra.py
# 1단계 위: TRADE/Argorism
# 2단계 위: TRADE
# 3단계 위: Jubby_AutoTrage_Python (프로젝트의 최상위 뿌리 폴더)
# 이 경로를 등록해야 프로젝트 어디서든 공용 모듈(KIS_Manager)을 불러올 수 있습니다.
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if root_dir not in sys.path:
    sys.path.append(root_dir)

# 이제 최상위 폴더에 있는 COMMON 폴더 안의 KIS_Manager 파일을 가져옵니다.
import COMMON.KIS_Manager as KIS

class UltraDataCollector:
    """
    대한민국 대표 100개 종목의 과거 차트를 몽땅 긁어와서
    AI가 공부할 '기출문제집'을 만드는 특수 로봇 클래스입니다.
    """
    def __init__(self, app_key, app_secret, account_no, is_mock=True):
        print("🔥 [주삐 울트라 컬렉터 V2] 시스템 가동! 100대 종목 사냥을 시작합니다.")
        # 한국투자증권 API와 연결하기 위해 '열쇠(Token)'를 발급받는 과정입니다.
        self.api = KIS.KIS_API(app_key, app_secret, account_no, is_mock)
        self.api.get_access_token()
        
        # 접속할 서버 주소 (모의투자용 vts 서버 혹은 실전 서버)를 결정합니다.
        self.base_url = "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443"

    # ---------------------------------------------------------
    # 2. [데이터 수집] 종목 하나의 하루치(09:00~15:30) 1분봉 싹쓸이
    # ---------------------------------------------------------
    def fetch_full_day_data(self, stock_code):
        """
        한 번에 30개씩만 주는 API의 한계를 넘기 위해 
        시간을 뒤로 돌려가며 여러 번 호출하여 하루 전체 데이터를 통째로 모읍니다.
        """
        all_chunks = []
        target_time = "153000" # 오후 3시 30분(장 마감 시간)부터 시작해서 거꾸로 올라갑니다.

        # 보통 하루 장 운영 시간(390분)을 다 채우기 위해 15번 정도 반복 호출합니다. (30분 * 15회 = 450분치)
        for i in range(15):
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
            headers = {
                "Content-Type": "application/json",
                "authorization": f"Bearer {self.api.access_token}",
                "appKey": self.api.app_key,
                "appSecret": self.api.app_secret,
                "tr_id": "FHKST03010200", # 1분봉 차트를 조회할 때 쓰는 약속된 코드
                "custtype": "P"
            }
            params = {
                "FID_ETC_CLS_CODE": "", 
                "FID_COND_MRKT_DIV_CODE": "J", # J는 주식(Stock)을 의미
                "FID_INPUT_ISCD": stock_code,  # 수집할 종목의 코드
                "FID_INPUT_HOUR_1": target_time, # 이 시간 이전의 데이터를 가져와라
                "FID_PW_DATA_INCU_YN": "Y"  # ✨[매우 중요] "Y"로 해야 과거 데이터를 연속해서 가져옵니다.
            }
            
            res = requests.get(url, headers=headers, params=params)
            
            if res.status_code == 200 and res.json()['rt_cd'] == '0':
                data = res.json()['output2']
                if not data: break # 더 이상 가져올 과거 데이터가 없으면 멈춥니다.
                
                # 받아온 30개 데이터 뭉치를 임시 보관함에 넣습니다.
                df_chunk = pd.DataFrame(data)
                all_chunks.append(df_chunk)
                
                # 다음 번에는 방금 가져온 데이터 중 가장 과거 시간(마지막 행)을 기준으로 다시 요청합니다.
                target_time = data[-1]['stck_cntg_hour'] 
                
                # ⚠️ [안전장치] API를 너무 빨리 부르면 서버에서 차단할 수 있으니 0.5초씩 매너 있게 쉽니다.
                time.sleep(0.5) 
            else:
                print(f"❌ [{stock_code}] 수집 중 서버 에러 발생. 다음으로 넘어갑니다.")
                break
            
        if not all_chunks: return None
        
        # 여기저기 흩어진 30분짜리 조각들을 하나로 합치고 시간순(09:00 -> 15:30)으로 예쁘게 정렬합니다.
        df = pd.concat(all_chunks).drop_duplicates().sort_values('stck_cntg_hour')
        df['code'] = stock_code # 나중에 헷갈리지 않게 종목 코드 이름을 새겨넣습니다.
        
        # 컬럼 이름을 우리가 알아보기 쉬운 한글/영어 이름으로 바꿉니다.
        df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'volume', 'acc_volume', 'extra', 'code'][:len(df.columns)]
        
        # 문자로 된 가격과 거래량을 진짜 계산이 가능한 '숫자' 형태로 변환합니다.
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].apply(pd.to_numeric)
        return df.reset_index(drop=True)

    # ---------------------------------------------------------
    # 3. [전처리 및 라벨링] AI가 공부할 수 있게 밥상 차리기
    # ---------------------------------------------------------
    def make_ai_dataset(self, df):
        """
        생 데이터에 RSI, MACD 같은 'AI의 특수 안경'을 씌워주고, 미래를 컨닝해서 정답지를 만듭니다.
        """
        # [수익률] AI는 절대 가격보다 "이전보다 몇 % 올랐어?"라는 변화에 더 민감합니다.
        df['return'] = df['close'].pct_change() # 가격의 변화율
        df['vol_change'] = df['volume'].pct_change() # 거래량의 변화율

        # [보조지표 1: RSI] 현재 주가가 공포(바닥)인지 탐욕(천장)인지 측정합니다.
        delta = df['close'].diff()
        up, down = delta.copy(), delta.copy()
        up[up < 0] = 0; down[down > 0] = 0
        df['RSI'] = 100 - (100 / (1 + (up.ewm(com=13).mean() / down.abs().ewm(com=13).mean())))
        
        # [보조지표 2: MACD] 비행기가 활주로에서 뜨듯이 추세가 바뀌는 지점을 포착합니다.
        df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
        
        # [보조지표 3: 볼린저 밴드 하단] 주가가 고무줄 하단을 찢었을 때(진짜 폭락)를 잡아냅니다.
        df['MA20'] = df['close'].rolling(20).mean()
        df['BB_Lower'] = df['MA20'] - (df['close'].rolling(20).std() * 2)

        # ---------------------------------------------------------------------
        # 🎯 [정답지 라벨링] AI 학습의 꽃! '미래 10분'을 몰래 보고 정답을 적습니다.
        # ---------------------------------------------------------------------
        # 현재 시점에서 앞으로 10분 동안 일어날 최고가와 최저가를 미리 가져옵니다.
        df['future_max_10'] = df['close'].rolling(window=10).max().shift(-10)
        df['future_min_10'] = df['close'].rolling(window=10).min().shift(-10)

        # ✅ 정답 1: 대박 기회 (Target_Buy)
        # "지금 사면 앞으로 10분 안에 1% 이상 확 튀어오르는가?" -> 맞으면 1 (수익 확정!)
        df['Target_Buy'] = np.where(df['future_max_10'] >= df['close'] * 1.01, 1, 0)

        # ✅ 정답 2: 위험/마지노선 (Target_Sell)
        # 1. 샀는데 10분 안에 -1%까지 처박히거나 (손절 지점)
        # 2. 샀는데 10분 내에 0.2%조차 수익이 안 나는 빌빌대는 구간 (힘없음/탈출해야함)
        # 이 경우 AI에게 "여기서는 빨리 도망쳐야 해!"라고 '1'을 적어서 가르칩니다.
        df['Target_Sell'] = np.where((df['future_min_10'] <= df['close'] * 0.99) | 
                                     (df['future_max_10'] < df['close'] * 1.002), 1, 0)

        # 계산을 위해 앞뒤로 생긴 빈 줄(NaN)을 지우고 깨끗한 데이터만 남깁니다.
        return df.dropna().reset_index(drop=True)

# ---------------------------------------------------------------------
# 🚀 [메인 실행부] 100개 종목을 하나씩 돌면서 통합 족보를 합칩니다.
# ---------------------------------------------------------------------
if __name__ == "__main__":
    # 회원님의 개인 API 정보 (보안에 주의하세요!)
    APP_KEY = "PSargEXRJo0zf5vOG1HAAKr7bKX9VKDzBhjy"
    APP_SECRET = "3IS6VELZscyON3lhpinnbWf9I6+oCfFR+k5+XyreSvnwgi1IFaOFlN4M35ZL8IvTidXiSWws+qCe8Y015l/w2VN8kVC/BHmncRwLBVZUxICBE6RcVt3JsPp/xlHyjo1meR0XWqU8yqlIUkOcib3HfSamhnpiCKFalhlVeyYcgU3uP/1UWP8="
    ACCOUNT = "50172151"

    # 🎯 주삐가 마스터할 대한민국 대표 100대 종목 (삼전, 하이닉스, 카카오 등등)
    stock_list = ["005930", "000660", "373220", "005380", "000270", "068270", "005490", "035420", "035720", "000810",
                  "051910", "105560", "012330", "032830", "055550", "003550", "000100", "033780", "009150", "015760",
                  "018260", "011780", "010130", "010950", "323410", "000720", "086790", "034220", "003670", "034730",
                  "090430", "096770", "003470", "011070", "006400", "267250", "024110", "005830", "004020", "011170",
                  "071050", "000080", "000670", "008770", "007070", "002380", "036570", "009830", "005935", "004170",
                  "010120", "000120", "028260", "000150", "011210", "001450", "003490", "030000", "001040", "078930",
                  "021240", "023530", "086280", "138040", "005440", "047040", "047050", "009540", "000990", "006800",
                  "005387", "001520", "016360", "042700", "000210", "002790", "010620", "000100", "001230", "003000",
                  "086520", "091990", "247540", "066970", "293490", "035900", "058470", "253450", "067160", "028300",
                  "036830", "039200", "041510", "046890", "051910", "066570", "084850", "086900", "131970", "278280"]
    
    collector = UltraDataCollector(APP_KEY, APP_SECRET, ACCOUNT)
    final_combined_data = []

    print(f"📊 총 {len(stock_list)}개 종목 사냥 시작! 예상 시간은 약 15~20분입니다.")
    
    for idx, code in enumerate(stock_list):
        try:
            # 1. 종목 하나의 하루치를 통째로 긁어옵니다.
            raw = collector.fetch_full_day_data(code)
            if raw is not None:
                # 2. 보조지표를 달고 미래를 컨닝해서 정답을 매깁니다.
                processed = collector.make_ai_dataset(raw)
                final_combined_data.append(processed)
                
                # 5개 종목마다 사냥 진행 상황을 출력합니다.
                if (idx + 1) % 5 == 0:
                    current_count = sum(len(d) for d in final_combined_data)
                    print(f"✅ {idx + 1}번째 종목 완료! (현재 수집된 기출문제: {current_count}줄)")
        except Exception as e:
            # 혹시 중간에 하나가 에러 나도 멈추지 않고 다음 종목으로 넘어갑니다.
            print(f"⚠️ [{code}] 사냥 실패(건너뜀): {e}")
            continue

    # 100개 종목의 모든 문제집을 하나로 합쳐서 거대한 족보를 만듭니다.
    if final_combined_data:
        master_df = pd.concat(final_combined_data).reset_index(drop=True)
        # 프로젝트 최상위 폴더에 'AI_Ultra_Master_Train_Data_V2.csv'라는 이름으로 저장합니다.
        save_path = os.path.join(root_dir, "AI_Ultra_Master_Train_Data_V2.csv")
        master_df.to_csv(save_path, index=False, encoding="utf-8-sig")
        
        print(f"\n💎 [대성공!] 총 {len(master_df)}줄의 거대한 족보가 완성되었습니다!")
        print(f"📍 파일 위치: {save_path}")
        print("이제 이 '완벽한 기출문제집'으로 주삐의 뇌를 훈련시킬 준비가 끝났습니다!")