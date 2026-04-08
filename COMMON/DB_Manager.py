import sqlite3
import os
import datetime
import pandas as pd  

# 방금 만든 공통 경로를 불러옵니다.
from COMMON.Flag import SystemConfig 

# 🟢 [수정 1] 중복 선언된 함수 삭제 및 깔끔하게 하나로 통일!
def get_smart_path(filename):
    """ 하드코딩 없이 무조건 최상위 경로(SystemConfig.PROJECT_ROOT)를 바라봄 """
    return os.path.join(SystemConfig.PROJECT_ROOT, filename)

class JubbyDB_Manager:
    def __init__(self):
        """ [생성자] 주삐 투 트랙 DB 매니저 """
        self.shared_db_path = get_smart_path("jubby_shared.db")
        self.python_db_path = get_smart_path("jubby_python.db")

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
        # timeout을 30초로 넉넉히 주고, 매번 연결할 때마다 WAL(동시 읽기/쓰기) 모드와 동기화 설정을 강제 주입합니다!
        conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
        conn.execute('PRAGMA journal_mode = WAL;')  
        conn.execute('PRAGMA synchronous = NORMAL;')
        conn.execute('PRAGMA busy_timeout = 5000;') 
        return conn

    # =======================================================================
    # 🌟 1. 공유 DB (Shared) - C# UI 화면에 띄워줄 데이터 저장소
    # =======================================================================
    def _initialize_shared_db(self):
        conn = self._get_connection(self.shared_db_path)
        try:
            # 🔥 DB 환경설정(PRAGMA)
            conn.execute('PRAGMA journal_mode = WAL;')  
            conn.execute('PRAGMA synchronous = NORMAL;')
            conn.execute('PRAGMA busy_timeout = 5000;') 

            # [공통 테이블 생성]
            conn.execute('''CREATE TABLE IF NOT EXISTS SharedSettings (category TEXT, key TEXT, value TEXT, PRIMARY KEY (category, key))''')
            
            # 🔥 CURRENT_TIMESTAMP를 한국 시간으로 변경 완료!
            conn.execute('''CREATE TABLE IF NOT EXISTS SystemStatus (module TEXT PRIMARY KEY, status TEXT, progress INTEGER, last_update TIMESTAMP DEFAULT (datetime('now', '+9 hours')))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS MarketStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, last_price REAL, open_price REAL, high_price REAL, low_price REAL, return_1m REAL, trade_amount REAL, vol_energy REAL, disparity REAL, volume REAL, ask_size REAL, bid_size REAL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS AccountStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, quantity INTEGER, avg_price REAL, current_price REAL, pnl_amt REAL, pnl_rate REAL, available_cash REAL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS StrategyStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, ai_prob REAL, ma_5 REAL, ma_20 REAL, RSI REAL, macd REAL, signal TEXT, status_msg TEXT)''')
            
            conn.execute('''CREATE TABLE IF NOT EXISTS SharedLogs (id INTEGER PRIMARY KEY AUTOINCREMENT, log_level TEXT, message TEXT, created_at TIMESTAMP DEFAULT (datetime('now', '+9 hours')))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS PriceHistory (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, price REAL, created_at TIMESTAMP DEFAULT (datetime('now', '+9 hours')))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS target_stocks (symbol TEXT, symbol_name TEXT, market_mode TEXT)''')

            # =================================================================
            # 🛒 [수정] TradeHistory 테이블 생성 및 자동 컬럼 추가 로직
            # =================================================================
            # 1. 일단 기본 구조로 테이블 생성 시도
            conn.execute("""
                CREATE TABLE IF NOT EXISTS TradeHistory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT,
                    symbol TEXT,
                    symbol_name TEXT,
                    type TEXT,
                    price REAL,
                    quantity INTEGER,
                    Status TEXT,
                    filled_quantity INTEGER,
                    order_price REAL,
                    order_time TEXT,
                    order_yield TEXT
                )
            """)

            # 2. ⭐ [강력 보정 로직] 기존 데이터 100% 보존 + 누락된 최신 컬럼 전체 자동 검사 및 추가
            cursor = conn.execute("PRAGMA table_info(TradeHistory)")
            cols = [c[1].lower() for c in cursor.fetchall()] # 대소문자 구분 없이 비교하기 위해 소문자 변환
            
            # 주삐 최신 엔진에 필요한 컬럼과 기본 데이터 타입 목록
            required_columns = {
                'time': 'TEXT',
                'symbol': 'TEXT',
                'symbol_name': 'TEXT DEFAULT "-"',
                'type': 'TEXT',
                'price': 'REAL DEFAULT 0.0',
                'quantity': 'INTEGER DEFAULT 0',
                'order_no': 'TEXT',
                'Status': 'TEXT DEFAULT "미체결"',
                'filled_quantity': 'INTEGER DEFAULT 0',
                'order_price': 'REAL DEFAULT 0.0',
                'order_time': 'TEXT',
                'order_yield': 'TEXT'
            }
            
            # 현재 DB에 없는 컬럼만 쏙쏙 골라서 안전하게 추가합니다.
            for col_name, col_type in required_columns.items():
                if col_name.lower() not in cols:
                    try:
                        conn.execute(f"ALTER TABLE TradeHistory ADD COLUMN {col_name} {col_type}")
                        print(f"🔧 [DB 시스템] TradeHistory에 '{col_name}' 컬럼을 안전하게 추가했습니다.")
                    except Exception as e:
                        pass # 이미 있거나 충돌나면 무시하고 다음으로 넘어감

            # =================================================================
            # 🚀 [MarketStatus 컬럼 보정]
            # =================================================================
            try:
                cursor = conn.execute("PRAGMA table_info(MarketStatus)")
                m_cols = [c[1] for c in cursor.fetchall()]
                if "last_price" not in m_cols: conn.execute("ALTER TABLE MarketStatus ADD COLUMN last_price REAL")
                if "ask_size" not in m_cols: conn.execute("ALTER TABLE MarketStatus ADD COLUMN ask_size REAL")
                if "bid_size" not in m_cols: conn.execute("ALTER TABLE MarketStatus ADD COLUMN bid_size REAL")
            except Exception: pass

            # 🟢 [기본 설정값 세팅]
            default_settings = [
                ("TRADE", "RANKING_SCAN_COUNT", "150"),
                ("TRADE", "USE_TRAILING", "Y"),
                ("TRADE", "TRAILING_START_YIELD", "1.5"),
                ("TRADE", "TRAILING_STOP_GAP", "0.8"),
                ("TRADE", "MAX_HOLDING_TIME", "20"),
                ("TRADE", "LOSS_STREAK_LIMIT", "5"),
                ("TRADE", "ATR_HIGH_LIMIT", "5.0"),
                ("TRADE", "ATR_HIGH_RATIO", "30.0"),
                ("TRADE", "TIME_START_DOM", "0900"),
                ("TRADE", "TIME_CLOSE_DOM", "1500"),
                ("TRADE", "TIME_IMMINENT_DOM", "1515"),
                ("TRADE", "TIME_END_DOM", "1530"),
                ("RISK", "MAX_CONSECUTIVE_LOSS", "5"),
                ("RISK", "DAILY_STOP_LOSS_PCT", "-15.0"),
                ("RISK", "IS_LOCKED", "N"),
            ]
            for category, key, val in default_settings:
                conn.execute("INSERT OR IGNORE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)", (category, key, val))

        except Exception as e:
            print(f"DB 초기화 에러: {e}")
        finally:
            conn.close()

    def update_system_status(self, module, status, progress=0):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("REPLACE INTO SystemStatus (module, status, progress, last_update) VALUES (?, ?, ?, datetime('now', '+9 hours'))", (module, status, progress))
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
            # 🔥 [핵심 수정] INSERT INTO -> REPLACE INTO 로 변경하여 UNIQUE 에러 완벽 차단!
            conn.executemany('REPLACE INTO MarketStatus (symbol, symbol_name, last_price, open_price, high_price, low_price, return_1m, trade_amount, vol_energy, disparity, volume) VALUES (:symbol, :symbol_name, :last_price, :open_price, :high_price, :low_price, :return_1m, :trade_amount, :vol_energy, :disparity, :volume)', data_list) 
            conn.execute("COMMIT;")
        except Exception as e:
            conn.execute("ROLLBACK;")
            print(f"🔥 Market DB 에러: {e}")
        finally:
            conn.close()

    def update_account_table(self, data_list):
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            conn.execute("DELETE FROM AccountStatus")
            # 🌟 [수정 확인] REPLACE INTO 가 아주 잘 적용되어 있습니다!
            conn.executemany('REPLACE INTO AccountStatus (symbol, symbol_name, quantity, avg_price, current_price, pnl_amt, pnl_rate, available_cash) VALUES (:symbol, :symbol_name, :quantity, :avg_price, :current_price, :pnl_amt, :pnl_rate, :available_cash)', data_list)
            conn.execute("COMMIT;")
        except Exception as e: 
            conn.execute("ROLLBACK;")
            print(f"🔥 Account DB 에러: {e}") 
        finally:
            conn.close()

    def update_strategy_table(self, data_list):
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            conn.executemany('''
                REPLACE INTO StrategyStatus (symbol, symbol_name, ai_prob, ma_5, ma_20, RSI, macd, signal, status_msg) 
                VALUES (:symbol, :symbol_name, :ai_prob, :ma_5, :ma_20, :RSI, :macd, :signal, :status_msg)
            ''', data_list)
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
        finally:
            conn.close()

    def update_realtime(self, symbol, current_price, ai_score, holding_str, status_msg):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("UPDATE StrategyStatus SET ai_prob = ?, status_msg = ? WHERE symbol = ?", (ai_score, status_msg, symbol))
        except Exception: pass
        finally: conn.close()

    def insert_price_history(self, symbol, price):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO PriceHistory (symbol, price) VALUES (?, ?)", (symbol, price))
            conn.execute('''DELETE FROM PriceHistory WHERE symbol=? AND id NOT IN (SELECT id FROM PriceHistory WHERE symbol=? ORDER BY created_at DESC LIMIT 500)''', (symbol, symbol))
        finally: conn.close()

    def insert_log(self, log_level, message):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO SharedLogs (log_level, message) VALUES (?, ?)", (log_level, message))
        except Exception as e: print(f"로그 기록 중 에러: {e}")
        finally: conn.close()

    def insert_trade_history(self, order_no, symbol, trade_type, price, qty, yield_rate=0.0, status="미체결", filled_qty=0):
        """ 주문 내역을 DB에 동적으로 상태를 지정하여 기록 """
        conn = self._get_connection(self.shared_db_path)
        try:
            kst_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
            time_str = kst_now.strftime("%Y-%m-%d %H:%M:%S")
            short_time_str = kst_now.strftime("%H:%M:%S")
            
            conn.execute('''INSERT INTO TradeHistory 
                (time, symbol, symbol_name, type, price, quantity, order_no, Status, filled_quantity, order_price, order_time, order_yield) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                (time_str, symbol, "-", trade_type, price, qty, str(order_no), 
                 status, filled_qty, price, short_time_str, f"{yield_rate}%"))
        except Exception as e:
            print(f"🚨 TradeHistory 저장 에러: {e}")
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
        finally: conn.close()

    def set_shared_setting(self, category, key, value):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("REPLACE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)", (category, key, str(value)))
        finally: conn.close()

    def _initialize_python_db(self):
        conn = self._get_connection(self.python_db_path)
        try:
            conn.execute('PRAGMA journal_mode = WAL;')
            conn.execute('''CREATE TABLE IF NOT EXISTS AITrainingLogs (id INTEGER PRIMARY KEY AUTOINCREMENT, train_date TIMESTAMP DEFAULT (datetime('now', '+9 hours')), model_name TEXT, accuracy REAL, data_count INTEGER)''')
        finally: conn.close()

    def insert_ai_train_log(self, model_name, accuracy, data_count):
        conn = self._get_connection(self.python_db_path)
        try:
            conn.execute('INSERT INTO AITrainingLogs (model_name, accuracy, data_count) VALUES (?, ?, ?)', (model_name, accuracy, data_count))
        finally: conn.close()

    def save_training_data(self, df, market_mode):
        if df is None or df.empty: return
        table_name = "TrainData_Domestic" if market_mode == "DOMESTIC" else "TrainData_Overseas" if market_mode == "OVERSEAS" else "TrainData_Futures"
        conn = self._get_connection(self.python_db_path)
        try: df.to_sql(table_name, conn, if_exists='append', index=False)
        finally: conn.close()

    def get_training_data(self, market_mode):
        table_name = "TrainData_Domestic" if market_mode == "DOMESTIC" else "TrainData_Overseas" if market_mode == "OVERSEAS" else "TrainData_Futures"
        conn = self._get_connection(self.python_db_path)
        try: return pd.read_sql(f"SELECT * FROM {table_name}", conn)
        except: return None 
        finally: conn.close()

    def cleanup_old_data(self):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("DELETE FROM SharedLogs WHERE created_at < datetime('now', '-3 days')")
            conn.execute("DELETE FROM PriceHistory WHERE created_at < datetime('now', '-1 days')")
        finally: conn.close()

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
        finally: conn.close()

    def get_realtime_price(self, symbol):
        conn = self._get_connection(self.shared_db_path)
        try:
            cursor = conn.execute("SELECT last_price FROM MarketStatus WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            return float(row[0]) if row and row[0] is not None else 0.0
        except: return 0.0
        finally: conn.close()

    def update_shared_risk_status(self, is_locked):
        """
        [상세 설명]
        오늘 손실이 너무 크면 C# UI와 공유하는 DB에 '잠금' 상태를 기록합니다.
        C#은 이 값을 읽어서 화면에 '자동매매 중단' 경고를 띄울 수 있습니다.
        """
        conn = self._get_connection(self.shared_db_path)
        try:
            val = "Y" if is_locked else "N"
            conn.execute("INSERT OR REPLACE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)",
                        ("RISK", "IS_LOCKED", val))
        finally:
            conn.close()