import sqlite3
import os
import datetime
import pandas as pd  # 🔥 [추가] AI 학습 데이터를 DB에 쉽게 넣고 빼기 위해 필요합니다.

class JubbyDB_Manager:
    def __init__(self):
        """
        [생성자] 주삐 투 트랙 DB 매니저
        프로그램이 켜질 때 제일 먼저 실행되어, 주삐가 데이터를 기록할 '공책(DB)'을 준비합니다.
        C#과 함께 보는 '공유 공책(shared)'과 파이썬 혼자 보는 '비밀 공책(python)' 두 권을 만듭니다.
        """
        # 1. 주삐의 데이터가 저장될 폴더의 절대 경로를 지정합니다.
        self.base_path = r"C:\Users\atrjk\OneDrive\바탕 화면\Program\04.Taemoo\Jubby Project"
        
        # 만약 해당 폴더가 없다면 새로 만들어줍니다.
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

        # 2. 두 권의 공책(DB 파일) 경로를 지정합니다.
        self.shared_db_path = os.path.join(self.base_path, "jubby_shared.db")
        self.python_db_path = os.path.join(self.base_path, "jubby_python.db")

        # 3. 공책을 펴고, 데이터를 적을 표(Table)들의 틀을 미리 그려놓습니다.
        self._initialize_shared_db()
        self._initialize_python_db()

    def _get_connection(self, db_path):
        """
        [핵심 기술] DB 파일에 빨대를 꽂아 연결하는 함수입니다.
        """
        # timeout=15: C#이 데이터를 읽고 있어서 파일이 잠겨있더라도, 포기하지 않고 최대 15초를 기다립니다.
        conn = sqlite3.connect(db_path, timeout=15)
        
        # 🔥 마법의 주문 (WAL 모드): 원래 DB는 한 명만 쓸 수 있지만, 
        # 이 주문을 외우면 파이썬이 글을 쓰는 와중에도 C#이 자유롭게 글을 읽어갈 수 있습니다! (에러 방지)
        conn.execute('PRAGMA journal_mode = WAL;')  
        conn.execute('PRAGMA synchronous = NORMAL;') # 속도와 안정성을 모두 챙기는 설정
        return conn

    # =======================================================================
    # 🌟 1. 공유 DB (Shared) - C# UI 화면에 띄워줄 데이터 저장소
    # =======================================================================
    def _initialize_shared_db(self):
        """ [공유] C#이 화면을 그릴 때 필요한 모든 표(Table)의 양식을 만듭니다. """
        conn = self._get_connection(self.shared_db_path)
        cursor = conn.cursor()
        try:
            # [1] 설정값: C# 화면 상단에 "현재 모드: 국내", "목표금액: 100만" 등을 띄우기 위함
            cursor.execute('''CREATE TABLE IF NOT EXISTS SharedSettings (
                                category TEXT, key TEXT, value TEXT,
                                PRIMARY KEY (category, key))''')

            # [2] 진행 상태: C# 화면 하단의 진행률 바(ProgressBar)를 채우기 위함
            cursor.execute('''CREATE TABLE IF NOT EXISTS SystemStatus (
                                module TEXT PRIMARY KEY, 
                                status TEXT, 
                                progress INTEGER, 
                                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                                
            # [3] 시장 상황: C# 메인 화면의 '실시간 감시 종목' 그리드를 채우기 위함
            cursor.execute('''CREATE TABLE IF NOT EXISTS MarketStatus (
                                symbol TEXT PRIMARY KEY, 
                                symbol_name TEXT, 
                                last_price REAL, 
                                return_1m REAL, 
                                trade_amount REAL, 
                                volume REAL)''')
                                
            # [4] 내 계좌: C# 화면의 '보유 종목 및 수익률' 그리드를 채우기 위함
            cursor.execute('''CREATE TABLE IF NOT EXISTS AccountStatus (
                                symbol TEXT PRIMARY KEY, 
                                symbol_name TEXT, 
                                quantity INTEGER, 
                                avg_price REAL, 
                                current_price REAL, 
                                pnl_rate REAL)''')

            # [5] 전략 신호: C# 화면의 'AI 전략 분석' 그리드를 채우기 위함
            cursor.execute('''CREATE TABLE IF NOT EXISTS StrategyStatus (
                                symbol TEXT PRIMARY KEY, 
                                symbol_name TEXT, 
                                ma_5 REAL, 
                                ma_20 REAL, 
                                RSI REAL, 
                                macd REAL, 
                                signal TEXT)''')
                                
            # [6] 거래 영수증: C# 화면의 '매매 체결 내역' 그리드를 채우기 위함
            cursor.execute('''CREATE TABLE IF NOT EXISTS TradeHistory (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                trade_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                symbol TEXT,
                                trade_type TEXT, 
                                price REAL,
                                qty INTEGER,
                                yield_rate REAL,
                                ai_score REAL)''')

            # [7] 로그: 파이썬 검은 창에 뜨는 글씨들을 C# 리스트박스에도 똑같이 띄워주기 위함
            cursor.execute('''CREATE TABLE IF NOT EXISTS SharedLogs (
                                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                                log_level TEXT, 
                                message TEXT, 
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

            # [8] 주가 차트용: C#에서 예쁜 선 그래프를 그릴 수 있도록 가격의 발자취를 남깁니다.
            cursor.execute('''CREATE TABLE IF NOT EXISTS PriceHistory (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                symbol TEXT, 
                                price REAL, 
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.commit()
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # 파이썬(Master)이 정보를 업데이트할 때 쓰는 기능들
    # -----------------------------------------------------------------------
    def update_system_status(self, module, status, progress=0):
        """ 수집이나 학습이 몇 % 진행되었는지 C#에게 알려줍니다. """
        conn = self._get_connection(self.shared_db_path)
        try:
            # REPLACE INTO: 이미 같은 이름(module)이 있으면 덮어쓰고, 없으면 새로 만듭니다.
            conn.execute("REPLACE INTO SystemStatus (module, status, progress, last_update) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", 
                         (module, status, progress))
            conn.commit()
        finally:
            conn.close()

    def broadcast_settings(self, settings_dict):
        """ 파이썬이 현재 세팅한 값들을 C#이 알 수 있게 한꺼번에 뿌려줍니다. """
        conn = self._get_connection(self.shared_db_path)
        try:
            for key, value in settings_dict.items():
                conn.execute("REPLACE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)", 
                               ("CURRENT_CONFIG", key, str(value)))
            conn.commit()
        finally:
            conn.close()

    def update_market_table(self, data_list):
        """ 시장 감시 종목 리스트를 통째로 갈아 끼웁니다. (C#은 이거 그대로 표에 그리면 끝!) """
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            # 이전 데이터를 싹 지우고 최신 데이터로 채워 넣습니다.
            conn.execute("DELETE FROM MarketStatus") 
            conn.executemany('''
                INSERT INTO MarketStatus (symbol, symbol_name, last_price, return_1m, trade_amount, volume)
                VALUES (:symbol, :symbol_name, :last_price, :return_1m, :trade_amount, :volume)
            ''', data_list) # executemany는 리스트 안의 데이터를 한방에 밀어 넣는 고속 스킬입니다.
            conn.commit()
        finally:
            conn.close()

    def update_account_table(self, data_list):
        """ 계좌 잔고 데이터를 통째로 갈아 끼웁니다. """
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("DELETE FROM AccountStatus")
            conn.executemany('''
                INSERT INTO AccountStatus (symbol, symbol_name, quantity, avg_price, current_price, pnl_rate)
                VALUES (:symbol, :symbol_name, :quantity, :avg_price, :current_price, :pnl_rate)
            ''', data_list)
            conn.commit()
        finally:
            conn.close()

    def update_strategy_table(self, data_list):
        """ AI 전략 신호 데이터를 통째로 갈아 끼웁니다. """
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("DELETE FROM StrategyStatus")
            conn.executemany('''
                INSERT INTO StrategyStatus (symbol, symbol_name, ma_5, ma_20, RSI, macd, signal)
                VALUES (:symbol, :symbol_name, :ma_5, :ma_20, :RSI, :macd, :signal)
            ''', data_list)
            conn.commit()
        finally:
            conn.close()

    def insert_price_history(self, symbol, price):
        """ 실시간 주가를 기록하여 C#이 차트를 그릴 수 있도록 물감을 짜놓습니다. """
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO PriceHistory (symbol, price) VALUES (?, ?)", (symbol, price))
            # [센스] 물감이 너무 많아지면 DB가 무거워지니, 최근 500개만 남기고 옛날 기록은 알아서 지워줍니다.
            conn.execute('''DELETE FROM PriceHistory WHERE symbol=? AND id NOT IN 
                            (SELECT id FROM PriceHistory WHERE symbol=? ORDER BY created_at DESC LIMIT 500)''', (symbol, symbol))
            conn.commit()
        finally:
            conn.close()

    def insert_log(self, log_level, message):
        """ 파이썬에서 일어나는 모든 일을 C# 로그창으로 보냅니다. """
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO SharedLogs (log_level, message) VALUES (?, ?)", (log_level, message))
            conn.commit()
        finally:
            conn.close()

    def insert_trade_history(self, symbol, trade_type, price, qty, yield_rate=0.0, ai_score=0.0):
        """ 주식을 사고 팔았을 때 영수증을 발급합니다. """
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute('''INSERT INTO TradeHistory (symbol, trade_type, price, qty, yield_rate, ai_score)
                            VALUES (?, ?, ?, ?, ?, ?)''', (symbol, trade_type, price, qty, yield_rate, ai_score))
            conn.commit()
        finally:
            conn.close()

    def get_shared_setting(self, category, key, default_value=None):
        """ 설정값을 읽어옵니다. (없으면 기본값을 저장하고 반환합니다) """
        conn = self._get_connection(self.shared_db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM SharedSettings WHERE category = ? AND key = ?", (category, key))
            row = cursor.fetchone()
            if row: return row[0]
            else:
                self.set_shared_setting(category, key, default_value)
                return default_value
        finally:
            conn.close()

    def set_shared_setting(self, category, key, value):
        """ 설정값을 강제로 덮어씁니다. """
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("REPLACE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)",
                         (category, key, str(value)))
            conn.commit()
        finally:
            conn.close()


    # =======================================================================
    # 🔒 2. 내부 DB (Python 전용) - 파이썬 혼자 AI 학습용으로 쓰는 거대한 창고
    # =======================================================================
    def _initialize_python_db(self):
        """ 파이썬 전용 창고에 필요한 선반(Table)들을 조립합니다. """
        conn = self._get_connection(self.python_db_path)
        cursor = conn.cursor()
        try:
            # AI 학습 성적표 보관함
            cursor.execute('''CREATE TABLE IF NOT EXISTS AITrainingLogs (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                train_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                model_name TEXT,
                                accuracy REAL,
                                data_count INTEGER)''')
            conn.commit()
        finally:
            conn.close()

    def insert_ai_train_log(self, model_name, accuracy, data_count):
        """ AI가 학습을 마칠 때마다 몇 점을 맞았는지 기록해둡니다. """
        conn = self._get_connection(self.python_db_path)
        try:
            conn.execute('INSERT INTO AITrainingLogs (model_name, accuracy, data_count) VALUES (?, ?, ?)', 
                         (model_name, accuracy, data_count))
            conn.commit()
        finally:
            conn.close()

    # 🔥 [중요 추가] CSV(엑셀)를 버리고, 빅데이터를 SQL에 무한히 누적시키는 기능
    def save_training_data(self, df, market_mode):
        """ 수집기가 가져온 1000개 종목의 분봉 데이터를 DB에 안전하게 차곡차곡 쌓습니다. """
        if df is None or df.empty: return
        
        # 국내 주식과 미국 주식이 섞이지 않도록 방(테이블)을 나눠줍니다.
        table_name = "TrainData_Domestic" if market_mode == "DOMESTIC" else "TrainData_Overseas"
        
        conn = self._get_connection(self.python_db_path)
        try:
            # Pandas의 to_sql을 쓰면 DataFrame을 SQL에 한 방에 넣을 수 있습니다.
            # if_exists='append': 기존 데이터를 지우지 않고 그 밑에 계속 이어서 붙입니다! (핵심)
            df.to_sql(table_name, conn, if_exists='append', index=False)
            conn.commit()
        finally:
            conn.close()

    def get_training_data(self, market_mode):
        """ AI 학습기가 공부를 시작할 때, DB 창고에서 수십만 줄의 데이터를 꺼내옵니다. """
        table_name = "TrainData_Domestic" if market_mode == "DOMESTIC" else "TrainData_Overseas"
        
        conn = self._get_connection(self.python_db_path)
        try:
            # SELECT * 구문으로 창고에 있는 모든 데이터를 Pandas DataFrame으로 불러옵니다.
            query = f"SELECT * FROM {table_name}"
            df = pd.read_sql(query, conn)
            return df
        except Exception:
            return None # 테이블이 없거나 데이터가 없으면 None을 반환하여 에러를 막습니다.
        finally:
            conn.close()

    # =======================================================================
    # 🧹 3. 유지 보수 (DB가 뚱뚱해지지 않게 관리)
    # =======================================================================
    def cleanup_old_data(self):
        """ 
        [하우스키핑] 오래된 데이터를 지워줍니다. 
        프로그램 켤 때 한 번씩 실행되도록 FormMain에 넣어주면 좋습니다.
        """
        conn = self._get_connection(self.shared_db_path)
        try:
            # 로그는 3일 치만 보관하고 나머지는 삭-제
            conn.execute("DELETE FROM SharedLogs WHERE created_at < datetime('now', '-3 days')")
            # 그래프 기록은 하루 치만 보관하고 삭-제 (어차피 어제 차트는 안 보니까요!)
            conn.execute("DELETE FROM PriceHistory WHERE created_at < datetime('now', '-1 days')")
            conn.commit()
        finally:
            conn.close()