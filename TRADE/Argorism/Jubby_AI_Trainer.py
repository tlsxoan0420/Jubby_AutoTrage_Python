import pandas as pd
import numpy as np
import joblib
import os  # 🔥 os 모듈은 여기서 한 번만 불러옵니다!
import optuna
import xgboost as xgb
import lightgbm as lgb
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split
# 🔥 [핵심 수정 1] 정확도(Accuracy) 외에 F1-Score와 ROC-AUC 평가 지표를 추가로 불러옵니다.
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from sklearn.ensemble import VotingClassifier

# =====================================================================
# 🌐 시스템 전역 설정 및 DB 매니저 호출
# =====================================================================
from COMMON.Flag import SystemConfig 
from COMMON.DB_Manager import JubbyDB_Manager 

optuna.logging.disable_default_handler()

def train_jubby_brain(log_callback=None):
    db = JubbyDB_Manager()
    
    def send_log(msg, level="INFO"):
        if log_callback: log_callback(msg, level)
        else: print(f"[{level.upper()}] {msg}")
        try: db.insert_log(level.upper(), msg)
        except: pass

    db.update_system_status('TRAINER', '학습 준비 중...', 0)

    if SystemConfig.MARKET_MODE == "DOMESTIC": market_name = "🇰🇷 국내 주식"
    elif SystemConfig.MARKET_MODE == "OVERSEAS": market_name = "🌐 미국(해외) 주식"
    elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES": market_name = "🚀 해외 선물"
    else: market_name = "❓ 알 수 없는 시장"
        
    send_log(f"🧠 [주삐 AI 연구소] {market_name} 맞춤형 고도화 학습(스케일링 적용)을 시작합니다...", "INFO")

    # 💡 위에서 불러온 글로벌 os 모듈을 정상적으로 사용합니다.
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # 🔥 3칸 위로 올라가서 Jubby Project를 가리키게 합니다.
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
    
    send_log("📡 SQL 데이터베이스에서 누적된 빅데이터를 불러오는 중입니다...", "INFO")
    db.update_system_status('TRAINER', 'DB 데이터 로드 중', 10)
    
    try: df = db.get_training_data(SystemConfig.MARKET_MODE)
    except Exception as e:
        send_log(f"🚨 DB 데이터 로드 중 에러 발생: {e}", "ERROR")
        return

    if df is None or len(df) < 100:
        send_log("🚨 SQL DB에 학습할 데이터가 부족합니다!", "ERROR")
        db.update_system_status('TRAINER', '데이터 부족 에러', 0)
        return

    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(inplace=True)
    
    total_data_count = len(df)
    send_log(f"📊 총 {total_data_count:,}개의 1분봉 데이터를 DB에서 성공적으로 불러왔습니다.", "SUCCESS")

    # 🟢 [핵심 수정] 실전(Strategy.py)과 동일하게 18개의 지표를 모두 교재에 넣습니다!
    features = [
        'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 'BB_Width', 
        'Disparity_5', 'Disparity_20', 'Vol_Energy', 'OBV_Trend', 
        'ATR', 'High_Tail', 'Low_Tail', 'Buying_Pressure', 'Market_Return_1m',
        'Disparity_60', 'Disparity_120', 'Macro_Trend'  # 🔥 새롭게 추가된 3대장
    ]
    
    X = df[features]
    y = df['Target_Buy']
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)

    # =========================================================================
    # 🔥 [핵심 고도화] 극단적 쫄보 현상(데이터 불균형)을 해결하는 스케일링 가중치 계산
    # =========================================================================
    num_pos = sum(y_train == 1) # 스캘핑 성공(10분 내 1.5% 급등) 희귀 데이터 개수
    num_neg = sum(y_train == 0) # 일반 데이터 개수
        
    # 🔥 [핵심 수정 2] 기존의 극단적인 가중치를 줄이고 상한선(최대 10배)을 걸어 AI의 '확률 뻥튀기'를 막습니다!
    raw_weight = num_neg / num_pos if num_pos > 0 else 1.0
    scale_weight = min(raw_weight * 0.5, 10.0) 
    send_log(f"⚖️ [AI 스케일링 보정] 초단타 스캘핑 포착 가중치({scale_weight:.2f}배) 장착 완료!", "SUCCESS")
    
    # =========================================================================
    # 🤖 [Phase 1] Optuna: XGBoost 튜닝
    # =========================================================================
    send_log("⚙️ [1/3] XGBoost 최적의 셋팅값을 스스로 탐색합니다... (약 1~3분 소요)", "WARNING")
    db.update_system_status('TRAINER', 'XGBoost 튜닝 중...', 20)
    
    def xgb_objective(trial):
        param = {
            'tree_method': 'hist',
            'device': 'cuda', 
            'scale_pos_weight': scale_weight, # 🔥 억제된 가중치 부여
            'n_estimators': trial.suggest_int('n_estimators', 100, 500),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1),
            'max_depth': trial.suggest_int('max_depth', 3, 9),
            'subsample': trial.suggest_float('subsample', 0.6, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
            'random_state': 42
        }
        model = xgb.XGBClassifier(**param)
        model.fit(X_train, y_train, verbose=False)
        
        # 🔥 [핵심 수정 3] Accuracy(정답률) 대신 F1-Score(진짜 급등을 맞춘 비율)로 AI를 똑똑하게 평가합니다!
        preds = model.predict(X_test)
        return f1_score(y_test, preds, zero_division=0)

    # ✅ DB에 값이 없으면 "20"을 DB에 자동으로 저장하고 가져옵니다.
    try: xgb_trials = int(db.get_shared_setting("AI_TRAIN", "XGB_TRIALS", "20"))
    except: xgb_trials = 20

    xgb_study = optuna.create_study(direction='maximize')
    xgb_study.optimize(xgb_objective, n_trials=xgb_trials) 
    
    best_xgb_params = xgb_study.best_params 
    best_xgb_params['tree_method'] = 'hist'
    best_xgb_params['device'] = 'cuda'
    best_xgb_params['scale_pos_weight'] = scale_weight # 🔥 최종 모델에도 세팅
    
    send_log(f"✅ XGBoost 튜닝 완료! (최고 F1-Score: {xgb_study.best_value:.4f})", "SUCCESS")

    # =========================================================================
    # 🤖 [Phase 2] Optuna: LightGBM 튜닝
    # =========================================================================
    send_log("⚙️ [2/3] LightGBM 최적의 셋팅값을 스스로 탐색합니다... (약 1~3분 소요)", "WARNING")
    db.update_system_status('TRAINER', 'LightGBM 튜닝 중...', 50)

    def lgb_objective(trial):
        max_depth = trial.suggest_int('max_depth', 3, 9)
        max_possible_leaves = (2 ** max_depth) - 1 
        num_leaves = trial.suggest_int('num_leaves', 7, min(100, max_possible_leaves))

        param = {
            'scale_pos_weight': scale_weight, # 🔥 억제된 가중치 부여
            'n_estimators': trial.suggest_int('n_estimators', 100, 500),
            'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1),
            'max_depth': max_depth,
            'num_leaves': num_leaves,
            'subsample': trial.suggest_float('subsample', 0.6, 1.0),
            'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
            'random_state': 42,
            'n_jobs': -1,
            'verbose': -1
        }
        model = lgb.LGBMClassifier(**param)
        model.fit(X_train, y_train)
        
        # 🔥 [핵심 수정 4] 여기서도 F1-Score로 평가!
        preds = model.predict(X_test)
        return f1_score(y_test, preds, zero_division=0)

    # ✅ DB에 값이 없으면 "20"을 DB에 자동으로 저장하고 가져옵니다.
    try: lgb_trials = int(db.get_shared_setting("AI_TRAIN", "LGB_TRIALS", "20"))
    except: lgb_trials = 20

    lgb_study = optuna.create_study(direction='maximize')
    lgb_study.optimize(lgb_objective, n_trials=lgb_trials)
    
    best_lgb_params = lgb_study.best_params
    best_lgb_params['n_jobs'] = -1
    best_lgb_params['verbose'] = -1
    best_lgb_params['scale_pos_weight'] = scale_weight # 🔥 최종 모델에도 세팅
    
    send_log(f"✅ LightGBM 튜닝 완료! (최고 F1-Score: {lgb_study.best_value:.4f})", "SUCCESS")

    # =========================================================================
    # 👑 [Phase 3] 최강 앙상블 합체 및 저장
    # =========================================================================
    send_log(f"🤝 [3/3] 튜닝된 특화 XGBoost와 LightGBM을 하나로 합체(앙상블)합니다!", "WARNING")
    db.update_system_status('TRAINER', '앙상블 합체 및 최종 학습 중...', 70)

    xgb_best_model = xgb.XGBClassifier(**best_xgb_params)
    lgb_best_model = lgb.LGBMClassifier(**best_lgb_params)

    ensemble_model = VotingClassifier(
        estimators=[('xgb', xgb_best_model), ('lgb', lgb_best_model)],
        voting='soft'
    )
    ensemble_model.fit(X_train, y_train)

    final_preds = ensemble_model.predict(X_test)
    final_accuracy = accuracy_score(y_test, final_preds) * 100 
    final_f1 = f1_score(y_test, final_preds, zero_division=0) # F1 스코어도 계산해서 보여줌
    
    send_log(f"🏆 [합체 완료] 최종 주삐 AI 성능 - 정답률: {final_accuracy:.2f}%, F1-Score: {final_f1:.4f}", "SUCCESS")

    if SystemConfig.MARKET_MODE == "DOMESTIC": model_name = "jubby_brain.pkl"
    elif SystemConfig.MARKET_MODE == "OVERSEAS": model_name = "jubby_brain_overseas.pkl"
    elif SystemConfig.MARKET_MODE == "OVERSEAS_FUTURES": model_name = "jubby_brain_futures.pkl" 
    else: model_name = "jubby_brain_temp.pkl"
        
    # 🟢 무조건 자동 탐색된 공통 최상위 폴더에 AI 뇌를 저장합니다!
    save_path = os.path.join(SystemConfig.PROJECT_ROOT, model_name)
    
    joblib.dump(ensemble_model, save_path)
    
    send_log(f"💾 [저장 완료] 맞춤형 완벽한 뇌({model_name})가 이식되었습니다!", "SUCCESS")

    # =========================================================================
    # 🛡️ [Phase 4] 휩쏘(가짜 반등) 방어용 LSTM 시계열 딥러닝 학습
    # =========================================================================
    send_log("🛡️ [4/4] 가짜 반등을 걸러낼 'LSTM 패턴 관측수' 학습을 시작합니다...", "WARNING")
    db.update_system_status('TRAINER', 'LSTM 딥러닝 학습 중...', 90)

    # 1. 시계열(Window) 데이터 만들기 (과거 10분 단위로 묶기)
    seq_length = 10
    X_seq, y_seq = [], []
    X_values = X.values
    y_values = y.values
    
    for i in range(len(X_values) - seq_length):
        X_seq.append(X_values[i : i + seq_length])
        y_seq.append(y_values[i + seq_length])
        
    X_seq = torch.tensor(np.array(X_seq), dtype=torch.float32)
    y_seq = torch.tensor(np.array(y_seq), dtype=torch.float32).unsqueeze(1)
    
    # 데이터셋 나누기
    train_size = int(len(X_seq) * 0.8)
    train_dataset = TensorDataset(X_seq[:train_size], y_seq[:train_size])
    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=False)

    # 2. LSTM 신경망 모델 정의
    class JubbyLSTM(nn.Module):
        def __init__(self, input_size, hidden_size=32, num_layers=1):
            super(JubbyLSTM, self).__init__()
            self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
            self.fc = nn.Linear(hidden_size, 1)
            self.sigmoid = nn.Sigmoid()
            
        def forward(self, x):
            out, _ = self.lstm(x)
            out = self.fc(out[:, -1, :]) # 마지막 10분째의 결과를 사용
            return self.sigmoid(out)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    lstm_model = JubbyLSTM(input_size=X_seq.shape[2]).to(device)
    
    # 3. 모델 학습 (에포크 10번)
    criterion = nn.BCELoss(weight=torch.tensor([scale_weight], dtype=torch.float32).to(device)) # 가중치 적용
    optimizer = optim.Adam(lstm_model.parameters(), lr=0.001)

    lstm_model.train()
    for epoch in range(10):
        total_loss = 0
        for batch_X, batch_y in train_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            outputs = lstm_model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
            
    send_log("✅ LSTM 관측수 학습 완료!", "SUCCESS")

    # 4. LSTM 모델 저장
    lstm_model_name = model_name.replace(".pkl", "_lstm.pth")
    lstm_save_path = os.path.join(SystemConfig.PROJECT_ROOT, lstm_model_name)
    torch.save(lstm_model.state_dict(), lstm_save_path)
    send_log(f"💾 [저장 완료] 이중 방어막({lstm_model_name})이 성공적으로 장착되었습니다!", "SUCCESS")

    db.insert_ai_train_log(model_name=model_name, accuracy=final_accuracy, data_count=total_data_count)
    db.update_system_status('TRAINER', '학습 완료!', 100)

if __name__ == "__main__":
    train_jubby_brain()