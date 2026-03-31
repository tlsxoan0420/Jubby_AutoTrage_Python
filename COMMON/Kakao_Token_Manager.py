import requests
import json
import os
import sys

# =========================================================================
# 📂 [경로 자동 탐색] EXE / 파이썬 스크립트 실행 환경 완벽 호환
# =========================================================================
if getattr(sys, 'frozen', False):
    # 1. 파이썬이 EXE로 빌드되어 실행된 경우: EXE 파일이 놓인 폴더를 기준으로 삼음
    PROJECT_ROOT = os.path.dirname(sys.executable)
else:
    # 2. 스크립트로 실행된 경우: 현재 Kakao_Token_Manager.py가 있는 폴더를 기준으로 삼음
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 🔥 저장될 토큰의 절대 경로 생성 (항상 프로그램 최상위 폴더를 가리킴)
kakao_token_path = os.path.join(PROJECT_ROOT, "kakao_token.json")
# =========================================================================

REST_API_KEY = "4cbe02304c893a129a812045d5f200a3"
REDIRECT_URI = "https://localhost" 

print("="*75)
print("🌐 [1] 아래 링크를 복사해서 인터넷 주소창에 붙여넣으세요!")
print("🚨 [주의] 카카오 로그인 후 나오는 화면에서 반드시!!!")
print("🚨 [카카오톡 메시지 전송] 항목을 체크(✅)하셔야 합니다!")
print("-" * 75)
print(f"https://kauth.kakao.com/oauth/authorize?client_id={REST_API_KEY}&redirect_uri={REDIRECT_URI}&response_type=code&scope=talk_message")
print("="*75)

code = input("\n👉 [2] 빈 화면이 뜨면 주소창의 code= 뒷부분을 여기에 붙여넣고 엔터:\n").strip()

url = "https://kauth.kakao.com/oauth/token"
data = {
    "grant_type": "authorization_code",
    "client_id": REST_API_KEY,
    "redirect_uri": REDIRECT_URI,
    "code": code
}
response = requests.post(url, data=data)
tokens = response.json()

if "access_token" in tokens:
    # 🔥 기존 하드코딩된 이름 대신, 위에서 찾은 절대 경로를 사용하여 파일 저장!
    with open(kakao_token_path, "w") as fp:
        json.dump(tokens, fp)
    print("\n🎉 [대성공] 카톡 메시지 권한이 완벽하게 탑재된 토큰이 발급되었습니다!!")
    print(f"📂 [저장 위치] {kakao_token_path}")
else:
    print("\n🚨 [실패] 에러 발생:", tokens)