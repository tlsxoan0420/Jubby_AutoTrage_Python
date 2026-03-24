import sys
from PyQt5 import QtWidgets
from GUI.FormMain import FormMain

def main():
    print("주삐를 실행합니당")
    app = QtWidgets.QApplication(sys.argv)  # QApplication 생성
    window = FormMain()                     # FormMain 인스턴스 생성
    
    # =====================================================================
    # 🌟 [핵심] C#에서 몰래 켠 것(--connect)이 아닐 때만 창을 강제로 띄웁니다!
    # 이 부분이 없으면 무조건 창이 켜집니다.
    # =====================================================================
    if "--connect" not in sys.argv:
        window.show()                       # UI 창 띄우기
        
    sys.exit(app.exec_())                   # 이벤트 루프 실행

    print("UI 실행 완료")

if __name__ == "__main__":
    main()