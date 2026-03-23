import requests
import json
import os

# 🚨 1단계에서 복사해둔 본인의 [REST API 키]를 여기에 넣으세요!
REST_API_KEY = "4cbe02304c893a129a812045d5f200a3"
REDIRECT_URI = "https://localhost"

def get_initial_token():
    print("====================================================")
    print("1. 아래 인터넷 주소(URL)를 복사해서 인터넷 브라우저 창에 붙여넣고 엔터를 치세요.")
    url = f"https://kauth.kakao.com/oauth/authorize?client_id={REST_API_KEY}&redirect_uri={REDIRECT_URI}&response_type=code"
    print(f"\n👉 {url}\n")
    print("2. 카카오 로그인을 하고 동의하기를 누르면, 화면이 에러난 것처럼 하얗게 변합니다. (정상입니다)")
    print("3. 그때 인터넷 주소창을 보면 'https://localhost/?code=어쩌구저쩌구' 로 바뀌어 있습니다.")
    print("4. 거기서 'code=' 뒤에 있는 엄청 긴 영어+숫자만 복사해서 아래에 붙여넣어주세요!\n")
    print("====================================================")
    
    auth_code = input("발급받은 인가 코드(code)를 붙여넣으세요: ").strip()

    # 인가 코드로 진짜 토큰(액세스/리프레시 토큰) 발급받기
    token_url = "https://kauth.kakao.com/oauth/token"
    data = {
        "grant_type": "authorization_code",
        "client_id": REST_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "code": auth_code
    }

    response = requests.post(token_url, data=data)
    tokens = response.json()

    if "access_token" in tokens:
        # 발급받은 토큰을 파일로 예쁘게 저장 (앞으로 주삐가 이걸 읽어서 씁니다)
        with open("kakao_token.json", "w") as fp:
            json.dump(tokens, fp)
        print("\n✅ [성공] 카카오톡 토큰이 kakao_token.json 파일에 완벽하게 저장되었습니다!")
        print("이제 6시간마다 토큰이 죽어도 주삐가 알아서 살려낼 수 있습니다.")
    else:
        print("\n❌ [실패] 토큰 발급 실패. 인가 코드를 잘못 복사했거나 권한 설정이 안 되어 있습니다.")
        print(tokens)

if __name__ == "__main__":
    get_initial_token()