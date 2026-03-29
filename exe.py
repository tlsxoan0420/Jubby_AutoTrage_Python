import os
import shutil
import PyInstaller.__main__

# =========================================================================
# [ 주삐(Jubby) 프로젝트 EXE 빌드 스크립트 ]
# 이 스크립트를 실행하면 Main.py와 연결된 모든 파이썬 파일 및 UI 파일이 
# 하나의 폴더(또는 단일 exe)로 패키징됩니다.
# =========================================================================

def build_executable():
    print("🚀 주삐 파이썬 모듈 EXE 빌드를 시작합니다...")

    # PyInstaller에 전달할 옵션들을 리스트 형태로 세세하게 정의합니다.
    pyinstaller_options = [
        'Main.py',                  # 1. 빌드할 메인 파이썬 파일명 (시작점)
        
        # '--noconfirm' : 출력 폴더(dist, build)가 이미 존재할 경우 묻지 않고 덮어씁니다.
        '--noconfirm',              
        
        # '--onedir' : 하나의 실행 파일(-F, --onefile)로 만들지 않고, 폴더 형태로 만듭니다.
        # [이유] Pandas, PyQt5, 딥러닝(TensorFlow 등) 라이브러리는 용량이 매우 커서 
        # --onefile로 만들 경우 실행할 때마다 임시 폴더에 압축을 푸느라 프로그램 켜지는 데 
        # 수십 초가 걸릴 수 있습니다. 따라서 주식 자동매매처럼 무거운 프로그램은 폴더 형태가 좋습니다.
        '--onedir',                 
        
        # '--windowed' (또는 '-w') : 파이썬 콘솔(검은 창)을 띄우지 않고 백그라운드나 GUI 창만 띄웁니다.
        # 만약 에러 로그를 콘솔 창에서 확인하고 싶다면 이 줄을 주석 처리하세요.
        # '--windowed',             
        
        # '--add-data' : 파이썬 소스코드가 아닌 외부 파일(UI, 이미지, 텍스트 등)을 EXE에 포함시킵니다.
        # 형식: '원본경로;프로그램실행시경로' (윈도우는 세미콜론(;) 사용)
        # 주삐 코드는 "GUI/Main.ui"를 불러오므로 이를 포함해야 합니다.
        '--add-data=GUI/Main.ui;GUI/', 
        
        # '--clean' : 빌드 전에 이전에 생성된 캐시를 깔끔하게 지우고 새로 빌드합니다.
        '--clean',
        
        # '--name' : 최종 생성될 실행 파일 및 폴더의 이름을 지정합니다.
        '--name=Jubby_AutoTrade_Engine',
        
        # 로깅 레벨 설정 (에러나 경고 등을 얼마나 자세히 표시할지)
        '--log-level=INFO'
    ]

    try:
        # 위에서 정의한 옵션들을 모아서 PyInstaller를 실행합니다.
        PyInstaller.__main__.run(pyinstaller_options)
        print("\n✅ EXE 빌드가 성공적으로 완료되었습니다!")
        print("📁 생성된 파일은 현재 폴더의 'dist/Jubby_AutoTrade_Engine' 폴더 안에 있습니다.")
        
    except Exception as e:
        # 빌드 중 에러가 발생하면 어떤 에러인지 출력해 줍니다.
        print(f"\n❌ 빌드 중 에러가 발생했습니다: {e}")

if __name__ == '__main__':
    # 기존에 남아있던 빌드 찌꺼기(build, dist 폴더)를 미리 삭제하여 충돌을 방지합니다.
    if os.path.exists('build'):
        shutil.rmtree('build')
    if os.path.exists('dist'):
        shutil.rmtree('dist')
        
    # 빌드 함수 실행
    build_executable()