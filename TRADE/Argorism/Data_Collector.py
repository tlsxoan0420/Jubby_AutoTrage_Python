import sqlite3
import os

class JubbyDB:
    def __init__(self):
        """
        [생성자] 주삐 투 트랙 DB 매니저
        """
        # 1. 사용자 지정 절대 경로 셋팅 (r을 앞에 붙여서 백슬래시(\) 오류 방지)
        self.base_path = r"C:\Users\atrjk\OneDrive\바탕 화면\Program\04.Taemoo\Jubby Project"
        
        # 만약 해당 경로에 폴더가 없다면 자동으로 생성해줍니다.
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)
            print(f"📁 DB 폴더 생성 완료: {self.base_path}")

        # 2. 투 트랙 DB 파일 경로 지정
        self.shared_db_path = os.path.join(self.base_path, "jubby_shared.db") # C#과 공유
        self.python_db_path = os.path.join(self.base_path, "jubby_python.db") # Python 전용

        # DB 초기화 (테이블 생성)
        self._initialize_shared_db()
        self._initialize_python_db()

    def _get_connection(self, db_path):
        """
        [공통] DB 연결 객체를 반환합니다. WAL 모드 적용!
        """
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute('PRAGMA journal_mode = WAL;')
        conn.execute('PRAGMA synchronous = NORMAL;')
        return conn

    # =======================================================================
    # 🌟 1. 공유 DB (Shared) 세팅 : C# ↔ Python
    # =======================================================================
    def _initialize_shared_db(self):
        conn = self._get_connection(self.shared_db_path)
        cursor = conn.cursor()
        try:
            # 설정값 테이블 (UI에서 조작하는 매매 세팅 등)
            cursor.execute('''CREATE TABLE IF NOT EXISTS SharedSettings (
                                category TEXT, key TEXT, value TEXT,
                                PRIMARY KEY (category, key))''')
                                
            # 실시간 상태 테이블 (C# UI에 띄워줄 주가 및 AI 점수)
            cursor.execute('''CREATE TABLE IF NOT EXISTS RealtimeStatus (
                                symbol TEXT PRIMARY KEY, current_price INTEGER, 
                                ai_score REAL, status_message TEXT, 
                                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                                
            # C# UI에 띄워줄 로그 테이블
            cursor.execute('''CREATE TABLE IF NOT EXISTS SharedLogs (
                                id INTEGER PRIMARY KEY AUTOINCREMENT, log_level TEXT, 
                                message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.commit()
            print("✅ [주삐 DB] 공유용(Shared) DB 세팅 완료!")
        finally:
            conn.close()

    def update_realtime_status(self, symbol, current_price, ai_score, status_message):
        """ C# UI로 보낼 실시간 데이터를 공유 DB에 저장 """
        conn = self._get_connection(self.shared_db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                REPLACE INTO RealtimeStatus (symbol, current_price, ai_score, status_message, last_update)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (symbol, current_price, ai_score, status_message))
            conn.commit()
        finally:
            conn.close()

    # =======================================================================
    # 🔒 2. 내부 DB (Python 전용) 세팅 : AI 및 데이터 수집용
    # =======================================================================
    def _initialize_python_db(self):
        conn = self._get_connection(self.python_db_path)
        cursor = conn.cursor()
        try:
            # 파이썬 전용 설정 (AI 모델 파라미터 등)
            cursor.execute('''CREATE TABLE IF NOT EXISTS PythonSettings (
                                category TEXT, key TEXT, value TEXT,
                                PRIMARY KEY (category, key))''')
                                
            # 방대한 학습용 수집 데이터 (C#은 알 필요 없음)
            cursor.execute('''CREATE TABLE IF NOT EXISTS RawTickData (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                symbol TEXT, time TEXT, close INTEGER, volume INTEGER)''')
            conn.commit()
            print("✅ [주삐 DB] 내부용(Python) DB 세팅 완료!")
        finally:
            conn.close()

    def set_python_setting(self, category, key, value):
        """ Python 전용 설정 저장 """
        conn = self._get_connection(self.python_db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("REPLACE INTO PythonSettings (category, key, value) VALUES (?, ?, ?)",
                           (category, key, str(value)))
            conn.commit()
        finally:
            conn.close()