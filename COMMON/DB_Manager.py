import sqlite3
import os
import datetime
import pandas as pd  

class JubbyDB_Manager:
    def __init__(self):
        """
        [생성자] 주삐 투 트랙 DB 매니저
        프로그램이 켜질 때 제일 먼저 실행되어, 주삐가 데이터를 기록할 '공책(DB)'을 준비합니다.
        """
        
        # 🔥 하드코딩 완전 삭제! 현재 파일 위치를 기준으로 부모의 부모 폴더를 알아서 찾아갑니다.
        # 1. os.path.abspath(__file__): 현재 파일(DB_Manager.py)의 절대 경로
        # 2. dirname 1번: COMMON 폴더
        # 3. dirname 2번: Jubby_AutoTrage_Python 폴더
        # 4. dirname 3번: Jubby Project 폴더 (C#과 공유하는 최종 목표 폴더!)
        
        current_file_path = os.path.abspath(__file__)
        common_dir = os.path.dirname(current_file_path)
        python_project_dir = os.path.dirname(common_dir)
        
        self.base_path = os.path.dirname(python_project_dir) 
        
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

        self.shared_db_path = os.path.join(self.base_path, "jubby_shared.db")
        self.python_db_path = os.path.join(self.base_path, "jubby_python.db")

        self._initialize_shared_db()
        self._initialize_python_db()
    # =======================================================================
    # 🔌 외부 연결 통로 개방 (C#과의 락(Lock) 충돌 완벽 방지)
    # =======================================================================
    @property
    def engine(self):
        return self._get_connection(self.shared_db_path)

    @property
    def conn(self):
        return self._get_connection(self.shared_db_path)

    def _get_connection(self, db_path):
        # 🔥 [마법의 락 해제 옵션] 
        # 1. timeout=20: C#이 읽고 있어서 잠겨있어도 팅기지 않고 문 밖에서 20초 대기합니다.
        # 2. isolation_level=None: Auto-commit 닌자 모드! 데이터를 쓰자마자 0.001초 만에 락을 풀고 도망칩니다.
        conn = sqlite3.connect(db_path, timeout=20, isolation_level=None)
        return conn

    # =======================================================================
    # 🌟 1. 공유 DB (Shared) - C# UI 화면에 띄워줄 데이터 저장소
    # =======================================================================
    def _initialize_shared_db(self):
        conn = self._get_connection(self.shared_db_path)
        try:
            # 🔥 [버그 수정] DB 환경설정(PRAGMA)은 매번 쓰지 않고 맨 처음 켤 때 딱 1번만!
            # 이렇게 해야 C#이 0.5초마다 읽을 때 락이 걸리지 않습니다.
            conn.execute('PRAGMA journal_mode = WAL;')  
            conn.execute('PRAGMA synchronous = NORMAL;')
            conn.execute('PRAGMA busy_timeout = 5000;') 

            conn.execute('''CREATE TABLE IF NOT EXISTS SharedSettings (category TEXT, key TEXT, value TEXT, PRIMARY KEY (category, key))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS SystemStatus (module TEXT PRIMARY KEY, status TEXT, progress INTEGER, last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS MarketStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, last_price REAL, open_price REAL, high_price REAL, low_price REAL, return_1m REAL, trade_amount REAL, vol_energy REAL, disparity REAL, volume REAL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS AccountStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, quantity INTEGER, avg_price REAL, current_price REAL, pnl_amt REAL, pnl_rate REAL, available_cash REAL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS StrategyStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, ma_5 REAL, ma_20 REAL, RSI REAL, macd REAL, signal TEXT)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS TradeHistory (id INTEGER PRIMARY KEY AUTOINCREMENT, trade_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, symbol TEXT, symbol_name TEXT, order_type TEXT, order_price REAL, order_quantity INTEGER, filled_quantity INTEGER, order_time TEXT, Status TEXT, order_yield TEXT)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS SharedLogs (id INTEGER PRIMARY KEY AUTOINCREMENT, log_level TEXT, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS PriceHistory (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, price REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS target_stocks (symbol TEXT, symbol_name TEXT, market_mode TEXT)''')
        except Exception as e:
            print(f"DB 초기화 에러: {e}")
        finally:
            conn.close()

    def update_system_status(self, module, status, progress=0):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("REPLACE INTO SystemStatus (module, status, progress, last_update) VALUES (?, ?, ?, CURRENT_TIMESTAMP)", (module, status, progress))
        finally:
            conn.close()

    def broadcast_settings(self, settings_dict):
        conn = self._get_connection(self.shared_db_path)
        try:
            for key, value in settings_dict.items():
                conn.execute("REPLACE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)", ("CURRENT_CONFIG", key, str(value)))
        finally:
            conn.close()

    def update_market_table(self, data_list):
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DELETE FROM MarketStatus") 
            conn.executemany('INSERT INTO MarketStatus (symbol, symbol_name, last_price, open_price, high_price, low_price, return_1m, trade_amount, vol_energy, disparity, volume) VALUES (:symbol, :symbol_name, :last_price, :open_price, :high_price, :low_price, :return_1m, :trade_amount, :vol_energy, :disparity, :volume)', data_list) 
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
        finally:
            conn.close()

    def update_account_table(self, data_list):
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DELETE FROM AccountStatus")
            conn.executemany('INSERT INTO AccountStatus (symbol, symbol_name, quantity, avg_price, current_price, pnl_amt, pnl_rate, available_cash) VALUES (:symbol, :symbol_name, :quantity, :avg_price, :current_price, :pnl_amt, :pnl_rate, :available_cash)', data_list)
            conn.execute("COMMIT;")
        except Exception as e: # 🚨 'as e' 를 추가!
            conn.execute("ROLLBACK;")
            print(f"🔥 Account DB 에러: {e}") # 🚨 에러 내용을 파이썬 창에 띄우도록 추가!
        finally:
            conn.close()

    def update_strategy_table(self, data_list):
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DELETE FROM StrategyStatus")
            conn.executemany('INSERT INTO StrategyStatus (symbol, symbol_name, ma_5, ma_20, RSI, macd, signal) VALUES (:symbol, :symbol_name, :ma_5, :ma_20, :RSI, :macd, :signal)', data_list)
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
        finally:
            conn.close()

    def update_realtime(self, symbol, current_price, ai_score, holding_str, status_msg):
        pass

    def insert_price_history(self, symbol, price):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO PriceHistory (symbol, price) VALUES (?, ?)", (symbol, price))
            conn.execute('''DELETE FROM PriceHistory WHERE symbol=? AND id NOT IN (SELECT id FROM PriceHistory WHERE symbol=? ORDER BY created_at DESC LIMIT 500)''', (symbol, symbol))
        finally:
            conn.close()

    # 🔥 여기가 에러났던 부분! 락 방어 코드로 완벽 세팅
    def insert_log(self, log_level, message):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO SharedLogs (log_level, message) VALUES (?, ?)", (log_level, message))
        except sqlite3.OperationalError as e:
            # 혹시라도 아주 찰나의 순간에 락이 걸려도 무시하고 넘어갑니다 (프로그램 팅김 방지)
            print(f"로그 기록 중 DB 락 발생 무시됨: {e}")
        finally:
            conn.close()

    def insert_trade_history(self, symbol, trade_type, price, qty, yield_rate=0.0, ai_score=0.0):
        conn = self._get_connection(self.shared_db_path)
        try:
            # C#에서 받아오는 데이터명과 일치하게 수정
            conn.execute('''INSERT INTO TradeHistory (symbol, symbol_name, order_type, order_price, order_quantity, filled_quantity, order_time, Status, order_yield) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                         (symbol, "-", trade_type, price, qty, qty, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "체결완료", f"{yield_rate}%"))
        except sqlite3.OperationalError:
            pass
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
            conn.execute("REPLACE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)", (category, key, str(value)))
        finally:
            conn.close()

    # =======================================================================
    # 🔒 2. 내부 DB (Python 전용)
    # =======================================================================
    def _initialize_python_db(self):
        conn = self._get_connection(self.python_db_path)
        try:
            conn.execute('PRAGMA journal_mode = WAL;')
            conn.execute('''CREATE TABLE IF NOT EXISTS AITrainingLogs (id INTEGER PRIMARY KEY AUTOINCREMENT, train_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, model_name TEXT, accuracy REAL, data_count INTEGER)''')
        finally:
            conn.close()

    def insert_ai_train_log(self, model_name, accuracy, data_count):
        conn = self._get_connection(self.python_db_path)
        try:
            conn.execute('INSERT INTO AITrainingLogs (model_name, accuracy, data_count) VALUES (?, ?, ?)', (model_name, accuracy, data_count))
        finally:
            conn.close()

    def save_training_data(self, df, market_mode):
        if df is None or df.empty: return
        if market_mode == "DOMESTIC": table_name = "TrainData_Domestic"
        elif market_mode == "OVERSEAS": table_name = "TrainData_Overseas"
        else: table_name = "TrainData_Futures" 
        
        conn = self._get_connection(self.python_db_path)
        try:
            df.to_sql(table_name, conn, if_exists='append', index=False)
        finally:
            conn.close()

    def get_training_data(self, market_mode):
        if market_mode == "DOMESTIC": table_name = "TrainData_Domestic"
        elif market_mode == "OVERSEAS": table_name = "TrainData_Overseas"
        else: table_name = "TrainData_Futures" 
        
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
        finally:
            conn.close()

    # 🔥 C# 락(Lock) 없이 완벽하게 실시간 데이터 초기화
    def clear_realtime_data(self):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DELETE FROM MarketStatus")
            conn.execute("DELETE FROM AccountStatus")
            conn.execute("DELETE FROM StrategyStatus")
            conn.execute("COMMIT;")
        except Exception as e:
            conn.execute("ROLLBACK;")
            print(f"청소 중 에러 발생: {e}")
        finally:
            conn.close()