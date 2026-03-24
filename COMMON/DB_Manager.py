import sqlite3 # 파이썬 기본 내장 SQLite 라이브러리
import os      # 파일 경로 제어를 위한 라이브러리
import json    # 딕셔너리 같은 복잡한 데이터를 문자열로 변환해 저장할 때 사용

class JubbyDB:
    def __init__(self, db_name="jubby_data.db"):
        """
        [생성자] 주삐 DB 매니저가 실행될 때 가장 먼저 호출됩니다.
        """
        # DB 파일이 저장될 경로 (현재 실행되는 파이썬 파일과 같은 폴더에 생성됩니다)
        self.db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), db_name)
        
        # DB가 초기화되면서 필요한 테이블들을 모두 만들어냅니다.
        self._initialize_tables()

    def _get_connection(self):
        """
        [핵심 로직] DB와 연결 통로를 만드는 내부 함수입니다.
        C#과 파이썬이 동시에 접근해도 에러가 안 나도록 WAL 모드와 Timeout을 설정합니다.
        """
        # timeout=10 : 만약 C#이 데이터를 쓰고 있어서 잠겨있다면, 튕기지 말고 최대 10초까지 기다리라는 뜻!
        conn = sqlite3.connect(self.db_path, timeout=10)
        
        # ★ 가장 중요한 동시성 설정 (WAL 모드) ★
        # 읽기와 쓰기가 동시에 가능하게 만들어주는 마법의 설정입니다.
        conn.execute('PRAGMA journal_mode = WAL;')
        
        # DB 동기화 속도를 NORMAL로 맞춰서 속도와 안정성의 밸런스를 잡습니다.
        conn.execute('PRAGMA synchronous = NORMAL;')
        return conn

    def _initialize_tables(self):
        """
        프로그램에 필요한 모든 테이블(엑셀의 시트 역할)을 생성합니다.
        IF NOT EXISTS 덕분에 이미 테이블이 있으면 무시하고 안전하게 넘어갑니다.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # 1. 설정값 테이블 (AI 세팅, 시스템 세팅, 매매 세팅 모두 저장)
            # category: 어떤 설정인지 분류 (예: 'AI', 'TRADE', 'SYSTEM')
            # key: 설정 이름 (예: 'learning_rate', 'buy_amount')
            # value: 실제 설정 값 (문자열로 저장하고 꺼내서 변환)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Settings (
                    category TEXT,
                    key TEXT,
                    value TEXT,
                    PRIMARY KEY (category, key) -- 카테고리와 키의 조합은 중복될 수 없게 설정 (덮어쓰기 용도)
                )
            ''')

            # 2. 실시간 상태 테이블 (C# UI가 화면에 그릴 수 있도록 현재 데이터를 던져두는 곳)
            # symbol: 종목 코드 (예: 005930)
            # current_price: 현재가
            # ai_score: AI가 계산한 상승 확률 (0~100)
            # last_update: 마지막으로 정보가 업데이트된 시간
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS RealtimeStatus (
                    symbol TEXT PRIMARY KEY,
                    current_price INTEGER,
                    ai_score REAL,
                    status_message TEXT,
                    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 3. 로그 테이블 (파이썬에서 발생한 로그를 C# UI로 넘겨주기 위한 테이블)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS SystemLogs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_level TEXT,    -- INFO, ERROR, WARNING 등
                    message TEXT,      -- 로그 내용
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit() # 변경사항 실제 파일에 저장
            print("✅ [주삐 DB] 테이블 초기화 및 WAL 모드 세팅 완료!")
        except Exception as e:
            print(f"🚨 [주삐 DB] 테이블 초기화 실패: {e}")
        finally:
            conn.close() # 작업이 끝나면 반드시 연결을 닫아줍니다!

    # =======================================================================
    # 데이터베이스 조작 메서드 (사용하기 쉽게 만든 도구들)
    # =======================================================================

    def set_setting(self, category, key, value):
        """
        설정값을 DB에 저장하거나 수정합니다.
        (예: db.set_setting('AI', 'epoch', 100))
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # REPLACE INTO: 기존에 같은 category와 key가 있으면 값을 덮어쓰고, 없으면 새로 넣습니다.
            cursor.execute(
                "REPLACE INTO Settings (category, key, value) VALUES (?, ?, ?)",
                (category, key, str(value)) # 모든 값은 텍스트(문자열)로 변환하여 저장
            )
            conn.commit()
        finally:
            conn.close()

    def get_setting(self, category, key, default_value=None):
        """
        DB에서 특정 설정값을 가져옵니다. 값이 없으면 default_value를 반환합니다.
        (예: db.get_setting('AI', 'epoch', 50) -> 없으면 50 반환)
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT value FROM Settings WHERE category = ? AND key = ?",
                (category, key)
            )
            row = cursor.fetchone() # 하나만 가져오기
            if row:
                return row[0] # 값이 있으면 반환
            else:
                # DB에 값이 없다면 우리가 설정한 기본값을 넣어주고 그걸 반환합니다.
                self.set_setting(category, key, default_value)
                return default_value
        finally:
            conn.close()

    def update_realtime_status(self, symbol, current_price, ai_score, status_message):
        """
        [C#과 통신하는 핵심 함수] 
        파이썬이 종목의 현재가와 AI 분석 결과를 계속 이 함수로 갱신해주면,
        C#은 DB에서 이걸 읽어가서 UI 화면에 예쁘게 띄워줍니다.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # CURRENT_TIMESTAMP를 사용해 언제 저장된 정보인지 시간도 갱신해줍니다.
            cursor.execute('''
                REPLACE INTO RealtimeStatus (symbol, current_price, ai_score, status_message, last_update)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (symbol, current_price, ai_score, status_message))
            conn.commit()
        finally:
            conn.close()

    def insert_log(self, log_level, message):
        """
        에러나 정보를 로그 테이블에 저장합니다.
        C# UI에서 이 테이블을 읽어 '로그 화면'에 표시해줄 수 있습니다.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO SystemLogs (log_level, message)
                VALUES (?, ?)
            ''', (log_level, message))
            conn.commit()
        finally:
            conn.close()