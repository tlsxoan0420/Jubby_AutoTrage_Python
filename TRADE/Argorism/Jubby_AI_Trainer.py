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
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
file_name = "AI_Ultra_Master_Train_Data_V3.csv"
data_path = os.path.join(root_dir, file_name)

# 💡 [핵심 수정] log_callback을 인자로 받아서 UI 로그창에 출력합니다.
def train_jubby_brain(log_callback=None):
    def send_log(msg, log_type="info"):
        """print 대신 UI로 쏘는 내부 로그 함수"""
        if log_callback:
            log_callback(msg, log_type)
        else:
            print(msg) # UI가 안 붙었을 땐 그냥 콘솔에 출력 (안전장치)

    send_log("🧠 [주삐 AI 트레이너 V3] 13개 다차원 심층 지표 모드로 학습을 시작합니다.", "info")
    
    if not os.path.exists(data_path):
        send_log(f"❌ 데이터 파일이 없습니다! 수집기를 먼저 실행해 주세요.", "error")
        return
    
    df = pd.read_csv(data_path)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(inplace=True)

    # 13개 지표
    features = [
        'return', 'vol_change', 'RSI', 'MACD', 'BB_Lower', 
        'BB_Width', 'Disparity_5', 'Disparity_20', 
        'Vol_Energy', 'OBV_Trend', 
        'ATR', 'High_Tail', 'Low_Tail'
    ]

    X = df[features]      
    y = df['Target_Buy']  
    
    send_log(f"📊 최종 학습에 사용되는 지표: {len(features)}개", "info")
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    pos_weight = (len(y_train) - sum(y_train)) / sum(y_train)

    model = XGBClassifier(
        n_estimators=300,      
        learning_rate=0.03,    
        max_depth=6,           
        subsample=0.8,         
        colsample_bytree=0.8,  
        scale_pos_weight=pos_weight,
        random_state=42,
        eval_metric='logloss'
    )
    
    send_log("🚀 주삐 AI가 13차원 차트 패턴을 심층 분석하며 열공 중입니다...", "warning")
    model.fit(X_train, y_train)

    y_proba = model.predict_proba(X_test)[:, 1]
    y_pred_strict = (y_proba >= 0.6).astype(int) 

    acc = accuracy_score(y_test, y_pred_strict)
    send_log(f"🔍 [실전 매매 성적표] 최종 적중률: {acc*100:.1f}%", "success")

    importances = pd.Series(model.feature_importances_, index=features).sort_values(ascending=False)
    send_log(f"💡 가장 중요한 1등 지표: {importances.index[0]}", "info")

    model_save_path = os.path.join(root_dir, "jubby_brain.pkl")
    joblib.dump(model, model_save_path)
    send_log(f"💎 완성! 퀀트 두뇌(pkl)가 장착되었습니다. (저장완료)", "buy") # 파란색