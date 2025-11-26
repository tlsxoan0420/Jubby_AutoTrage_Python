from PyQt5 import QtWidgets
from GUI.FormMain import FormMain
import sys

def main():
    
    print("주삐를 실행합니당")
    app = QtWidgets.QApplication(sys.argv)  # QApplication 생성
    window = FormMain()                     # FormMain 인스턴스 생성
    window.show()                           # UI 창 띄우기
    sys.exit(app.exec_())                   # 이벤트 루프 실행

    print("UI 실행 완료")

if __name__ == "__main__":
    main()