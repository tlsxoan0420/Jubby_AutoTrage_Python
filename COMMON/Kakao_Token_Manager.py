import requests
import json

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
    with open("kakao_token.json", "w") as fp:
        json.dump(tokens, fp)
    print("\n🎉 [대성공] 카톡 메시지 권한이 완벽하게 탑재된 토큰이 발급되었습니다!!")
else:
    print("\n🚨 [실패] 에러 발생:", tokens)