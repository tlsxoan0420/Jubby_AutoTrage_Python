import os
import sys
import shutil
import PyInstaller.__main__

# =========================================================================
# [ 주삐(Jubby) 프로젝트 EXE 빌드 스크립트 ]
# =========================================================================

def build_executable():
    print("🚀 주삐 파이썬 모듈 EXE 빌드를 시작합니다...")

    # 현재 exe.py가 있는 폴더(GUI 폴더)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 🔥 [핵심 추가] 한 칸 위 폴더(COMMON, TRADE가 있는 프로젝트 루트 폴더) 경로를 찾습니다.
    root_dir = os.path.dirname(current_dir)
    
    main_file_path = os.path.join(current_dir, 'FormMain.py')
    ui_file_path = os.path.join(current_dir, 'Main.ui')
    
    # 낡은 .spec 파일 무조건 삭제!
    spec_file = os.path.join(current_dir, 'Jubby_AutoTrade_Engine.spec')
    parent_spec_file = os.path.join(root_dir, 'Jubby_AutoTrade_Engine.spec')
    
    if os.path.exists(spec_file):
        os.remove(spec_file)
    if os.path.exists(parent_spec_file):
        os.remove(parent_spec_file)

    if not os.path.exists(main_file_path):
        print(f"\n🚨 [에러] '{main_file_path}' 파일을 찾을 수 없습니다!")
        return

    # PyInstaller에 전달할 옵션
    pyinstaller_options = [
        main_file_path,                 
        
        '--noconfirm',              
        '--onedir',                 
        '--noconsole',              
        
        f'--add-data={ui_file_path};GUI', 
        f'--paths={root_dir}', 
        
        '--hidden-import=PyQt5.QtWidgets',
        '--hidden-import=PyQt5.QtCore',
        '--hidden-import=PyQt5.QtGui',
        
        '--exclude-module=PyQt5.QtWebEngine',
        '--exclude-module=PyQt5.QtWebEngineWidgets',
        '--exclude-module=PyQtWebEngine',
        
        '--hidden-import=xgboost',
        '--hidden-import=lightgbm',
        '--hidden-import=FinanceDataReader',
        '--hidden-import=yfinance',
        
        # ❌ [삭제] 기존에 있던 --collect-all 두 줄은 지워주세요!
        
        # 🟢 [여기로 교체!] 너무 무식하게 다 담지 말고, 딱 필요한 뼈대(DLL)와 데이터만 담으라고 지시합니다.
        '--collect-binaries=xgboost',
        '--collect-data=xgboost',
        '--collect-binaries=lightgbm',
        '--collect-data=lightgbm',
        
        # 🔥 [핵심 추가] 에러를 일으킨 주범인 'XGBoost 테스트용 폴더'는 아예 접근 금지령을 내립니다!
        '--exclude-module=xgboost.testing',
        '--exclude-module=hypothesis',
        
        '--clean',
        '--name=Jubby_AutoTrade_Engine',
        '--log-level=INFO',
        
        f'--distpath={os.path.join(current_dir, "dist")}',
        f'--workpath={os.path.join(current_dir, "build")}'
    ]

    try:
        PyInstaller.__main__.run(pyinstaller_options)
        print("\n✅ EXE 빌드가 성공적으로 완료되었습니다!")
        print(f"📁 생성된 파일 위치: {os.path.join(current_dir, 'dist', 'Jubby_AutoTrade_Engine')}")
        
    except Exception as e:
        print(f"\n❌ 빌드 중 에러가 발생했습니다: {e}")

if __name__ == '__main__':
    current_dir = os.path.dirname(os.path.abspath(__file__))
    build_dir = os.path.join(current_dir, 'build')
    dist_dir = os.path.join(current_dir, 'dist')
    
    print("🧹 기존 빌드 캐시를 청소 중입니다...")
    
    # 🔥 [수정] 프로그램이 켜져있어서 삭제를 거부당할 경우를 대비한 안전장치 추가!
    try:
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)
    except PermissionError:
        print("\n🚨 [권한 에러 발생! 빌드 중단]")
        print("💡 원인: 이전에 실행하신 주삐 프로그램(EXE)이 아직 백그라운드에서 켜져 있습니다.")
        print("💡 해결: 작업 관리자(Ctrl+Shift+Esc)를 열어 'Jubby_AutoTrade_Engine.exe'를 찾아 완전히 종료한 뒤 다시 실행해 주세요!")
        sys.exit()
        
    build_executable()