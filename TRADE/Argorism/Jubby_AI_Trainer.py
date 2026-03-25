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
# 🌐 시스템 전역 설정 (국내/해외 시장 모드 판별용) 및 DB 매니저 호출
# =====================================================================
from COMMON.Flag import SystemConfig 
from COMMON.DB_Manager import JubbyDB_Manager # 🔥 우리가 만든 투 트랙 DB 매니저

# Optuna의 불필요한 로그를 숨겨서 화면을 깔끔하게 만듭니다.
optuna.logging.set_verbosity(optuna.logging.WARNING)

def train_jubby_brain(log_callback=None):
    # 🔥 1. DB 객체 생성 (데이터 로드, 상태 보고, 성적표 저장용)
    db = JubbyDB_Manager()
    
    # -----------------------------------------------------------------
    # 📝 [로그 함수] 로그를 터미널과 '공유 DB'에 동시에 기록합니다.
    # -----------------------------------------------------------------
    def send_log(msg, level="INFO"):
        if log_callback: 
            log_callback(msg, level)
        else: 
            print(f"[{level.upper()}] {msg}")
            
        # C# UI 하단 '로그 창'에 띄워주기 위해 공유 DB에 저장!
        db.insert_log(level.upper(), msg)

    # 🚀 C# 화면의 진행바(ProgressBar)를 0%로 초기화하며 시작을 알립니다.
    db.update_system_status('TRAINER', '학습 준비 중...', 0)

    # 현재 모드에 따라 인사말을 다르게 출력합니다.
    market_name = "🇰🇷 국내 주식" if SystemConfig.MARKET_MODE == "DOMESTIC" else "🌐 미국(해외) 주식"
    send_log(f"🧠 [주삐 AI 연구소] {market_name} 맞춤형 Optuna 자동 튜닝 및 앙상블 학습을 시작합니다...", "INFO")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(current_dir))
    
    # =========================================================================
    # 📂 [핵심 수정 1] CSV 파일을 버리고, 무한 누적된 SQL DB에서 데이터를 꺼내옵니다!
    # =========================================================================
    send_log("📡 SQL 데이터베이스에서 누적된 빅데이터를 불러오는 중입니다...", "INFO")
    db.update_system_status('TRAINER', 'DB 데이터 로드 중', 10)
    
    # DB 매니저에게 "현재 모드에 맞는 학습 데이터 싹 다 가져와!" 라고 명령합니다.
    df = db.get_training_data(SystemConfig.MARKET_MODE)

    # 🛡️ 방어 로직: 데이터가 아예 없거나 너무 적으면 학습을 포기합니다.
    if df is None or len(df) < 100:
        send_log("🚨 SQL DB에 학습할 데이터가 부족합니다! 수집기(Data Collector)를 먼저 돌려주세요.", "ERROR")
        db.update_system_status('TRAINER', '데이터 부족 에러', 0)
        return

    # 지저분한 값(무한대, 결측치)을 깨끗하게 청소합니다.
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(inplace=True)
    
    total_data_count = len(df) # 나중에 성적표에 기록할 총 데이터 개수
    send_log(f"📊 총 {total_data_count:,}개의 15지표 1분봉 데이터를 DB에서 성공적으로 불러왔습니다.", "SUCCESS")

    # 15개 핵심 지표 (Strategy.py와 100% 동일한 순서)
    features = [
        'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 'BB_Width', 
        'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
        'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m'
    ]
    
    X = df[features]
    y = df['Target_Buy']

    # 데이터를 공부용(80%)과 시험용(20%)으로 나눕니다. 시간 순서대로 잘라야 하므로 shuffle=False를 줍니다.
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    # =========================================================================
    # 🤖 [Phase 1] Optuna: XGBoost 최적의 황금 파라미터 찾기
    # =========================================================================
    send_log("⚙️ [1/3] XGBoost (GPU) 최적의 셋팅값을 스스로 탐색합니다... (약 1~3분 소요)", "WARNING")
    db.update_system_status('TRAINER', 'XGBoost 튜닝 중...', 20)
    
    def xgb_objective(trial):
        param = {
            'tree_method': 'hist',
            'device': 'cuda', # NVIDIA 그래픽카드(GPU)를 사용해 속도를 폭발적으로 높입니다.
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
    
    send_log(f"✅ XGBoost 튜닝 완료! (최고 정답률: {xgb_study.best_value * 100:.2f}%)", "SUCCESS")

    # =========================================================================
    # 🤖 [Phase 2] Optuna: LightGBM 최적의 황금 파라미터 찾기
    # =========================================================================
    send_log("⚙️ [2/3] LightGBM 최적의 셋팅값을 스스로 탐색합니다... (약 1~3분 소요)", "WARNING")
    db.update_system_status('TRAINER', 'LightGBM 튜닝 중...', 50)

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
    
    send_log(f"✅ LightGBM 튜닝 완료! (최고 정답률: {lgb_study.best_value * 100:.2f}%)", "SUCCESS")

    # =========================================================================
    # 👑 [Phase 3] 최강 앙상블 (투표 시스템) 결성 및 최종 학습
    # =========================================================================
    send_log(f"🤝 [3/3] 튜닝된 {market_name} 특화 XGBoost와 LightGBM을 하나로 합체(앙상블)합니다!", "WARNING")
    db.update_system_status('TRAINER', '앙상블 합체 및 최종 학습 중...', 80)

    xgb_best_model = xgb.XGBClassifier(**best_xgb_params)
    lgb_best_model = lgb.LGBMClassifier(**best_lgb_params)

    # 두 AI가 서로 의견을 나누고 투표(Voting)하여 최종 결정을 내리는 모델을 만듭니다.
    ensemble_model = VotingClassifier(
        estimators=[('xgb', xgb_best_model), ('lgb', lgb_best_model)],
        voting='soft'
    )

    ensemble_model.fit(X_train, y_train)

    final_preds = ensemble_model.predict(X_test)
    final_accuracy = accuracy_score(y_test, final_preds) * 100 # 백분율로 변환
    send_log(f"🏆 [합체 완료] 최종 앙상블 주삐 AI 정답률: {final_accuracy:.2f}%", "SUCCESS")

    # =========================================================================
    # 💾 [저장 및 마무리] 완성된 뇌(Model) 저장 및 C#에 보고
    # =========================================================================
    if SystemConfig.MARKET_MODE == "DOMESTIC":
        model_name = "jubby_brain.pkl"
    else:
        model_name = "jubby_brain_overseas.pkl"
        
    save_path = os.path.join(root_dir, model_name)
    joblib.dump(ensemble_model, save_path) # 실물 파일(.pkl)로 저장하여 내일도 쓸 수 있게 합니다.
    
    send_log(f"💾 [저장 완료] {market_name} 맞춤형 완벽한 뇌가 이식되었습니다!", "SUCCESS")
    send_log(f"📍 뇌 저장 위치: {save_path}", "INFO")

    # 🔥 내부 DB에 "오늘 몇 개의 데이터로 공부해서 몇 점 맞았음" 이라는 성적표를 남깁니다.
    db.insert_ai_train_log(model_name=model_name, accuracy=final_accuracy, data_count=total_data_count)
    send_log("📈 [기록 완료] 내부 DB(jubby_python.db)에 AI 학습 성적표가 등록되었습니다.", "INFO")
    
    # 🚀 C# 화면의 진행바를 100%로 꽉 채우고 완료 상태를 알립니다.
    db.update_system_status('TRAINER', '학습 완료!', 100)

if __name__ == "__main__":
    train_jubby_brain()