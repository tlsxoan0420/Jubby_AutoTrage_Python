import sqlite3
import os
import datetime
import pandas as pd  # 🔥 AI 학습 데이터를 DB에 쉽게 넣고 빼기 위해 필요합니다.

class JubbyDB_Manager:
    def __init__(self):
        """
        [생성자] 주삐 투 트랙 DB 매니저
        프로그램이 켜질 때 제일 먼저 실행되어, 주삐가 데이터를 기록할 '공책(DB)'을 준비합니다.
        """
        # 1. 주삐의 데이터가 저장될 폴더의 절대 경로를 지정합니다.
        self.base_path = r"C:\Users\atrjk\OneDrive\바탕 화면\Program\04.Taemoo\Jubby Project"
        
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

        # 2. 두 권의 공책(DB 파일) 경로를 지정합니다.
        self.shared_db_path = os.path.join(self.base_path, "jubby_shared.db")
        self.python_db_path = os.path.join(self.base_path, "jubby_python.db")

        # 3. 공책을 펴고, 데이터를 적을 표(Table)들의 틀을 미리 그려놓습니다.
        self._initialize_shared_db()
        self._initialize_python_db()

    # =======================================================================
    # 🔌 [에러 해결!] Pandas용 외부 연결 통로 개방 (engine / conn)
    # =======================================================================
    @property
    def engine(self):
        """ FormMain.py 등에서 pd.read_sql, df.to_sql을 사용할 때 쓰이는 연결 통로입니다. """
        return self._get_connection(self.shared_db_path)

    @property
    def conn(self):
        """ engine과 동일하게 작동하도록 만든 예비 통로입니다. """
        return self._get_connection(self.shared_db_path)

    def _get_connection(self, db_path):
        """ [핵심 기술] DB 파일에 빨대를 꽂아 연결하는 함수입니다. """
        conn = sqlite3.connect(db_path, timeout=15)
        conn.execute('PRAGMA journal_mode = WAL;')  
        conn.execute('PRAGMA synchronous = NORMAL;') 
        return conn

    # =======================================================================
    # 🌟 1. 공유 DB (Shared) - C# UI 화면에 띄워줄 데이터 저장소
    # =======================================================================
    def _initialize_shared_db(self):
        conn = self._get_connection(self.shared_db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''CREATE TABLE IF NOT EXISTS SharedSettings (
                                category TEXT, key TEXT, value TEXT,
                                PRIMARY KEY (category, key))''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS SystemStatus (
                                module TEXT PRIMARY KEY, 
                                status TEXT, 
                                progress INTEGER, 
                                last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                                
            cursor.execute('''CREATE TABLE IF NOT EXISTS MarketStatus (
                                symbol TEXT PRIMARY KEY, 
                                symbol_name TEXT, 
                                last_price REAL, 
                                return_1m REAL, 
                                trade_amount REAL, 
                                volume REAL)''')
                                
            cursor.execute('''CREATE TABLE IF NOT EXISTS AccountStatus (
                                symbol TEXT PRIMARY KEY, 
                                symbol_name TEXT, 
                                quantity INTEGER, 
                                avg_price REAL, 
                                current_price REAL, 
                                pnl_rate REAL)''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS StrategyStatus (
                                symbol TEXT PRIMARY KEY, 
                                symbol_name TEXT, 
                                ma_5 REAL, 
                                ma_20 REAL, 
                                RSI REAL, 
                                macd REAL, 
                                signal TEXT)''')
                                
            cursor.execute('''CREATE TABLE IF NOT EXISTS TradeHistory (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                trade_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                symbol TEXT,
                                trade_type TEXT, 
                                price REAL,
                                qty INTEGER,
                                yield_rate REAL,
                                ai_score REAL)''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS SharedLogs (
                                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                                log_level TEXT, 
                                message TEXT, 
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS PriceHistory (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                symbol TEXT, 
                                price REAL, 
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
                                
            # 🔥 [추가] 종목 사전을 저장할 테이블 (CSV 대체용)
            cursor.execute('''CREATE TABLE IF NOT EXISTS target_stocks (
                                symbol TEXT, 
                                symbol_name TEXT, 
                                market_mode TEXT)''')
            conn.commit()
        finally:
            conn.close()

    def update_system_status(self, module, status, progress=0):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("REPLACE INTO SystemStatus (module, status, progress, last_update) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", 
                         (module, status, progress))
            conn.commit()
        finally:
            conn.close()

    def broadcast_settings(self, settings_dict):
        conn = self._get_connection(self.shared_db_path)
        try:
            for key, value in settings_dict.items():
                conn.execute("REPLACE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)", 
                               ("CURRENT_CONFIG", key, str(value)))
            conn.commit()
        finally:
            conn.close()

    def update_market_table(self, data_list):
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("DELETE FROM MarketStatus") 
            conn.executemany('''
                INSERT INTO MarketStatus (symbol, symbol_name, last_price, return_1m, trade_amount, volume)
                VALUES (:symbol, :symbol_name, :last_price, :return_1m, :trade_amount, :volume)
            ''', data_list) 
            conn.commit()
        finally:
            conn.close()

    def update_account_table(self, data_list):
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
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO PriceHistory (symbol, price) VALUES (?, ?)", (symbol, price))
            conn.execute('''DELETE FROM PriceHistory WHERE symbol=? AND id NOT IN 
                            (SELECT id FROM PriceHistory WHERE symbol=? ORDER BY created_at DESC LIMIT 500)''', (symbol, symbol))
            conn.commit()
        finally:
            conn.close()

    def insert_log(self, log_level, message):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO SharedLogs (log_level, message) VALUES (?, ?)", (log_level, message))
            conn.commit()
        finally:
            conn.close()

    def insert_trade_history(self, symbol, trade_type, price, qty, yield_rate=0.0, ai_score=0.0):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute('''INSERT INTO TradeHistory (symbol, trade_type, price, qty, yield_rate, ai_score)
                            VALUES (?, ?, ?, ?, ?, ?)''', (symbol, trade_type, price, qty, yield_rate, ai_score))
            conn.commit()
        finally:
            conn.close()

    def get_shared_setting(self, category, key, default_value=None):
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
        conn = self._get_connection(self.python_db_path)
        cursor = conn.cursor()
        try:
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
        conn = self._get_connection(self.python_db_path)
        try:
            conn.execute('INSERT INTO AITrainingLogs (model_name, accuracy, data_count) VALUES (?, ?, ?)', 
                         (model_name, accuracy, data_count))
            conn.commit()
        finally:
            conn.close()

    # 🔥 [중요 수정] 해외선물(OVERSEAS_FUTURES) 전용 테이블 이름 부여!
    def save_training_data(self, df, market_mode):
        if df is None or df.empty: return
        
        # 국내 주식 / 미국 주식 / 해외선물 방(테이블)을 분리합니다.
        if market_mode == "DOMESTIC": table_name = "TrainData_Domestic"
        elif market_mode == "OVERSEAS": table_name = "TrainData_Overseas"
        else: table_name = "TrainData_Futures" # 🚀 해외선물 전용 데이터 방!
        
        conn = self._get_connection(self.python_db_path)
        try:
            df.to_sql(table_name, conn, if_exists='append', index=False)
            conn.commit()
        finally:
            conn.close()

    # 🔥 [중요 수정] 해외선물(OVERSEAS_FUTURES) 전용 데이터 불러오기
    def get_training_data(self, market_mode):
        if market_mode == "DOMESTIC": table_name = "TrainData_Domestic"
        elif market_mode == "OVERSEAS": table_name = "TrainData_Overseas"
        else: table_name = "TrainData_Futures" # 🚀 해외선물 전용 데이터 방!
        
        conn = self._get_connection(self.python_db_path)
        try:
            query = f"SELECT * FROM {table_name}"
            df = pd.read_sql(query, conn)
            return df
        except Exception:
            return None 
        finally:
            conn.close()

    # =======================================================================
    # 🧹 3. 유지 보수 (DB가 뚱뚱해지지 않게 관리)
    # =======================================================================
    def cleanup_old_data(self):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("DELETE FROM SharedLogs WHERE created_at < datetime('now', '-3 days')")
            conn.execute("DELETE FROM PriceHistory WHERE created_at < datetime('now', '-1 days')")
            conn.commit()
        finally:
            conn.close()