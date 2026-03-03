import pandas as pd
import numpy as np
import os
import sys
import joblib 
from xgboost import XGBClassifier 
from sklearn.model_selection import train_test_split 
from sklearn.metrics import classification_report, accuracy_score 

# ---------------------------------------------------------------------
# 1. [경로 및 파일 설정] 데이터 위치를 정확히 지정합니다.
# ---------------------------------------------------------------------
# 현재 파일 위치를 기준으로 프로젝트 최상위 폴더를 찾습니다.
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 수집기(V3)에서 생성한 대용량 마스터 데이터 파일 이름을 입력하세요.
# 파일명이 다르면 여기서 수정해주시면 됩니다.
file_name = "AI_Ultra_Master_Train_Data_V2.csv"
data_path = os.path.join(root_dir, file_name)

def train_jubby_brain():
    print("🧠 [주삐 AI 트레이너 V2] '신중함 강화 학습' 모드를 시작합니다.")
    
    # 데이터 파일 존재 여부 확인
    if not os.path.exists(data_path):
        print(f"❌ 데이터 파일이 없습니다! 수집기를 먼저 실행해 주세요. (위치: {data_path})")
        return
    
    # [1] 데이터 불러오기
    df = pd.read_csv(data_path)
    initial_len = len(df)

    # ---------------------------------------------------------------------
    # 2. [데이터 세척] AI가 싫어하는 '무한대'와 '빈 칸'을 제거합니다.
    # ---------------------------------------------------------------------
    # 계산 과정에서 발생한 무한대(inf) 값을 비어있는 값(NaN)으로 변환
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    
    # 비어있는 값이 하나라도 있는 행은 공부에 방해가 되므로 삭제
    df.dropna(inplace=True)
    
    cleaned_len = len(df)
    if initial_len != cleaned_len:
        print(f"🧹 데이터 세척 완료: 오류 데이터 {initial_len - cleaned_len}줄 삭제됨.")

    # ---------------------------------------------------------------------
    # 3. [특징 선택] AI에게 어떤 정보를 가르칠지 결정합니다. (중요!)
    # ---------------------------------------------------------------------
    # V3 수집기에서 추가한 '괴리율', '에너지', '낙폭' 지표들을 포함시킵니다.
    # 만약 수집기에서 해당 지표를 추가하지 않았다면 아래 리스트를 수정해야 합니다.
    features = ['return', 'vol_change', 'RSI', 'MACD', 'BB_Lower']
    
    # [주의] 만약 데이터에 아래 보강 지표들이 들어있다면 리스트에 추가하세요.
    reinforced_features = ['Disparity', 'Vol_Energy', 'Drop_Slope']
    for rf in reinforced_features:
        if rf in df.columns:
            features.append(rf)
            print(f"✨ 보강 지표 감지됨: {rf}")

    X = df[features]      # 문제 (차트 상황)
    y = df['Target_Buy']  # 정답 (10분 내 반등 성공 여부)
    
    print(f"📊 최종 학습에 사용되는 지표: {features}")
    print(f"📊 전체 기출문제: {cleaned_len}줄 (성공 사례: {y.sum()}개)")
    
    if y.sum() == 0:
        print("❌ 에러: 데이터에 성공 사례(Target_Buy=1)가 없습니다. 수집을 더 해야 합니다.")
        return

    # ---------------------------------------------------------------------
    # 4. [데이터 분리] 공부용과 모의고사용으로 나눕니다.
    # ---------------------------------------------------------------------
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # 성공 사례(1)가 부족하므로 1에 대해 더 집중해서 공부하라는 가중치를 계산합니다.
    pos_weight = (len(y_train) - sum(y_train)) / sum(y_train)

    # ---------------------------------------------------------------------
    # 5. [AI 모델 생성] 신중하게 설계된 XGBoost 모델을 만듭니다.
    # ---------------------------------------------------------------------
    model = XGBClassifier(
        n_estimators=200,      # 공부 반복 횟수 (100 -> 200으로 늘려 더 꼼꼼하게)
        learning_rate=0.05,    # 학습 속도 (더 신중하고 세밀하게 분석)
        max_depth=7,           # 생각의 깊이 (더 복잡한 차트 패턴을 이해)
        scale_pos_weight=pos_weight, # 성공 사례 비중 조절
        random_state=42,
        eval_metric='logloss'
    )
    
    print("🚀 AI가 차트 패턴을 심층 분석하며 열공 중입니다...")
    model.fit(X_train, y_train)

    # ---------------------------------------------------------------------
    # 6. [신중함 강화 필터] '긴가민가'한 건 버리고 '확실한 것'만 골라냅니다.
    # ---------------------------------------------------------------------
    # 단순히 0 또는 1로 예측하는 게 아니라, "AI가 확신하는 확률"을 가져옵니다.
    y_proba = model.predict_proba(X_test)[:, 1]
    
    # 커트라인(Threshold)을 0.8(80%)로 상향 조정합니다.
    # AI가 "80% 이상 오를 것 같다"고 확신할 때만 매수 신호(1)를 줍니다.
    # 이 수치가 높을수록 헛발질(Precision)은 줄고 신중함은 올라갑니다.
    y_pred_strict = (y_proba > 0.8).astype(int) 

    # ---------------------------------------------------------------------
    # 7. [성적표 출력] 보강된 성적표를 확인합니다.
    # ---------------------------------------------------------------------
    print("\n🔍 [주삐 AI 보강된 성적표 - 신중함 80% 기준]")
    print(f"최종 정확도(Accuracy): {accuracy_score(y_test, y_pred_strict):.2f}")
    print("-" * 60)
    print(classification_report(y_test, y_pred_strict))
    print("-" * 60)

    # 어떤 지표가 주삐의 결정에 가장 큰 영향을 주었는지 확인합니다.
    importances = pd.Series(model.feature_importances_, index=features).sort_values(ascending=False)
    print("\n💡 주삐가 가장 중요하게 생각한 지표 순위:")
    print(importances)

    # ---------------------------------------------------------------------
    # 8. [모델 저장] 완성된 주삐의 뇌를 파일로 저장합니다.
    # ---------------------------------------------------------------------
    model_save_path = os.path.join(root_dir, "jubby_brain.pkl")
    joblib.dump(model, model_save_path)
    print(f"\n💎 완성! 주삐의 신중한 뇌가 저장되었습니다: {model_save_path}")

if __name__ == "__main__":
    train_jubby_brain()