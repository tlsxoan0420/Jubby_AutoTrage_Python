import pandas as pd
import numpy as np
import joblib
import os
import optuna  # 🚀 AI가 스스로 최적의 값을 찾는 라이브러리
import xgboost as xgb
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from sklearn.ensemble import VotingClassifier # 🚀 여러 AI를 투표시키는 앙상블 라이브러리

# =====================================================================
# 🌐 [추가됨] 시스템 전역 설정 (국내/해외 시장 모드 판별용)
# =====================================================================
from COMMON.Flag import SystemConfig 

# Optuna의 불필요한 로그를 숨겨서 화면을 깔끔하게 만듭니다.
optuna.logging.set_verbosity(optuna.logging.WARNING)

def train_jubby_brain(log_callback=None):
    def send_log(msg, level="info"):
        if log_callback: log_callback(msg, level)
        else: print(msg)

    # 현재 모드에 따라 인사말을 다르게 출력합니다.
    market_name = "🇰🇷 국내 주식" if SystemConfig.MARKET_MODE == "DOMESTIC" else "🌐 미국(해외) 주식"
    send_log(f"🧠 [주삐 AI 연구소] {market_name} 맞춤형 Optuna 자동 튜닝 및 앙상블 학습을 시작합니다...", "info")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(current_dir))
    
    # =========================================================================
    # 📂 [핵심 분기 1] 현재 모드에 따라 '읽어올 훈련 데이터(CSV)' 경로 변경
    # =========================================================================
    if SystemConfig.MARKET_MODE == "DOMESTIC":
        data_file = "AI_Ultra_Master_Train_Data_V3.csv"
    else:
        # 해외 모드일 때는 Data_Collector가 만든 해외 전용 데이터를 불러옵니다.
        data_file = "AI_Ultra_Master_Train_Data_Overseas.csv"
        
    data_path = os.path.join(root_dir, data_file)

    if not os.path.exists(data_path):
        send_log(f"🚨 데이터가 없습니다! ({data_file}) Data Collector를 먼저 실행해주세요.", "error")
        return

    # 1. 데이터 로드
    df = pd.read_csv(data_path, low_memory=False) # 💡 DtypeWarning 경고 방지
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(inplace=True)
    send_log(f"📊 총 {len(df):,}개의 15지표 1분봉 데이터를 성공적으로 불러왔습니다.", "success")

    # 2. 15개 핵심 지표 (Strategy.py와 100% 동일한 순서)
    features = [
        'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 'BB_Width', 
        'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
        'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m'
    ]
    
    X = df[features]
    y = df['Target_Buy']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    # =========================================================================
    # 🤖 [Phase 1] Optuna: XGBoost 최적의 황금 파라미터 찾기
    # =========================================================================
    send_log("⚙️ [1/3] XGBoost (GPU) 최적의 셋팅값을 스스로 탐색합니다... (약 1~3분 소요)", "warning")
    
    def xgb_objective(trial):
        param = {
            'tree_method': 'hist',
            'device': 'cuda', # GPU 가속
            'n_estimators': trial.suggest_int('n_estimators', 100, 500),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1),
            'max_depth': trial.suggest_int('max_depth', 3, 9),
            'subsample': trial.suggest_float('subsample', 0.6, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
            'random_state': 42
        }
        model = xgb.XGBClassifier(**param)
        model.fit(X_train, y_train, verbose=False)
        preds = model.predict(X_test)
        return accuracy_score(y_test, preds)

    # 20번의 모의고사를 치르며 최고 점수 찾기
    xgb_study = optuna.create_study(direction='maximize')
    xgb_study.optimize(xgb_objective, n_trials=20) 
    best_xgb_params = xgb_study.best_params
    best_xgb_params['tree_method'] = 'hist'
    best_xgb_params['device'] = 'cuda'
    
    send_log(f"✅ XGBoost 튜닝 완료! (최고 정답률: {xgb_study.best_value * 100:.2f}%)", "success")

    # =========================================================================
    # 🤖 [Phase 2] Optuna: LightGBM 최적의 황금 파라미터 찾기
    # =========================================================================
    send_log("⚙️ [2/3] LightGBM 최적의 셋팅값을 스스로 탐색합니다... (약 1~3분 소요)", "warning")

    def lgb_objective(trial):
        param = {
            'n_estimators': trial.suggest_int('n_estimators', 100, 500),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1),
            'max_depth': trial.suggest_int('max_depth', 3, 9),
            'num_leaves': trial.suggest_int('num_leaves', 20, 100),
            'subsample': trial.suggest_float('subsample', 0.6, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
            'random_state': 42,
            'n_jobs': -1,
            'verbose': -1
        }
        model = lgb.LGBMClassifier(**param)
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        return accuracy_score(y_test, preds)

    lgb_study = optuna.create_study(direction='maximize')
    lgb_study.optimize(lgb_objective, n_trials=20)
    best_lgb_params = lgb_study.best_params
    best_lgb_params['n_jobs'] = -1
    best_lgb_params['verbose'] = -1
    
    send_log(f"✅ LightGBM 튜닝 완료! (최고 정답률: {lgb_study.best_value * 100:.2f}%)", "success")

    # =========================================================================
    # 👑 [Phase 3] 최강 앙상블 (투표 시스템) 결성 및 최종 학습
    # =========================================================================
    send_log(f"🤝 [3/3] 튜닝된 {market_name} 특화 XGBoost와 LightGBM을 하나로 합체(앙상블)합니다!", "warning")

    xgb_best_model = xgb.XGBClassifier(**best_xgb_params)
    lgb_best_model = lgb.LGBMClassifier(**best_lgb_params)

    ensemble_model = VotingClassifier(
        estimators=[('xgb', xgb_best_model), ('lgb', lgb_best_model)],
        voting='soft'
    )

    ensemble_model.fit(X_train, y_train)

    final_preds = ensemble_model.predict(X_test)
    final_accuracy = accuracy_score(y_test, final_preds)
    send_log(f"🏆 [합체 완료] 최종 앙상블 주삐 AI 정답률: {final_accuracy * 100:.2f}%", "success")

    # =========================================================================
    # 💾 [핵심 분기 2] 저장할 '뇌(모델 파일)' 이름 분기 처리
    # =========================================================================
    if SystemConfig.MARKET_MODE == "DOMESTIC":
        model_name = "jubby_brain.pkl"
    else:
        # 해외 모드일 때는 해외 전용 이름으로 뇌를 저장합니다.
        model_name = "jubby_brain_overseas.pkl"
        
    save_path = os.path.join(root_dir, model_name)
    joblib.dump(ensemble_model, save_path)
    
    send_log(f"💾 [저장 완료] {market_name} 맞춤형 완벽한 뇌가 이식되었습니다!", "buy")
    send_log(f"📍 뇌 저장 위치: {save_path}", "info")

if __name__ == "__main__":
    train_jubby_brain()