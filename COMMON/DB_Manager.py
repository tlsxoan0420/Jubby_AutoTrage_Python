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
            # 🔥 DB 환경설정(PRAGMA)
            conn.execute('PRAGMA journal_mode = WAL;')  
            conn.execute('PRAGMA synchronous = NORMAL;')
            conn.execute('PRAGMA busy_timeout = 5000;') 

            # 테이블 생성
            conn.execute('''CREATE TABLE IF NOT EXISTS SharedSettings (category TEXT, key TEXT, value TEXT, PRIMARY KEY (category, key))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS SystemStatus (module TEXT PRIMARY KEY, status TEXT, progress INTEGER, last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS MarketStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, last_price REAL, open_price REAL, high_price REAL, low_price REAL, return_1m REAL, trade_amount REAL, vol_energy REAL, disparity REAL, volume REAL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS AccountStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, quantity INTEGER, avg_price REAL, current_price REAL, pnl_amt REAL, pnl_rate REAL, available_cash REAL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS StrategyStatus (symbol TEXT PRIMARY KEY, symbol_name TEXT, ai_prob REAL, ma_5 REAL, ma_20 REAL, RSI REAL, macd REAL, signal TEXT, status_msg TEXT)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS TradeHistory (id INTEGER PRIMARY KEY AUTOINCREMENT, trade_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, symbol TEXT, symbol_name TEXT, order_type TEXT, order_price REAL, order_quantity INTEGER, filled_quantity INTEGER, order_time TEXT, Status TEXT, order_yield TEXT)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS SharedLogs (id INTEGER PRIMARY KEY AUTOINCREMENT, log_level TEXT, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS PriceHistory (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, price REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS target_stocks (symbol TEXT, symbol_name TEXT, market_mode TEXT)''')

            conn.execute('''CREATE TABLE IF NOT EXISTS TradeHistory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_no TEXT,           -- 💡 한투 실제 주문번호
                    trade_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP, 
                    symbol TEXT, 
                    symbol_name TEXT, 
                    order_type TEXT, 
                    order_price REAL, 
                    order_quantity INTEGER, 
                    filled_quantity INTEGER, 
                    order_time TEXT, 
                    Status TEXT, 
                    order_yield TEXT
                )''')

            # 🟢 [수정 2] DB가 처음 생성될 때, C# 화면에서 조작할 수 있도록 기본 설정값들을 자동으로 깔아줍니다!
            # (INSERT OR IGNORE: 이미 개발자님이 수정한 값이 있다면 덮어쓰지 않고 유지합니다)
            default_settings = [
                ("TRADE", "RANKING_SCAN_COUNT", "150"),      # 스캔 종목 개수 (기본 150)
                ("TRADE", "USE_TRAILING", "Y"),             # 트레일링 스탑 사용 여부
                ("TRADE", "TRAILING_START_YIELD", "1.5"),   # 트레일링 스탑 발동 수익률
                ("TRADE", "TRAILING_STOP_GAP", "0.8"),      # 고점 대비 하락 허용치
                ("TRADE", "MAX_HOLDING_TIME", "20"),        # 최대 보유 시간 (분)
                ("TRADE", "LOSS_STREAK_LIMIT", "5"),        # 연패 차단 횟수
                ("TRADE", "ATR_HIGH_LIMIT", "5.0"),         # 널뛰기 테마주 감지 기준(%)
                ("TRADE", "ATR_HIGH_RATIO", "30.0"),        # 테마주 진입 시 예산 축소 비율(%)
                ("TRADE", "TIME_START_DOM", "0900"),        # 주간장 스캔 시작 시간
                ("TRADE", "TIME_CLOSE_DOM", "1500"),        # 주간장 마감 방어 모드 시간
                ("TRADE", "TIME_IMMINENT_DOM", "1515"),     # 묻지마 시장가 강제 청산 시간
                ("TRADE", "TIME_END_DOM", "1530"),           # 주간장 종료 시간
                # 🔥 [추가] 리스크 관리 셧다운 설정
                ("RISK", "MAX_CONSECUTIVE_LOSS", "5"),    # 연속 손절 시 매수 셧다운 횟수
                ("RISK", "DAILY_STOP_LOSS_PCT", "-15.0"), # 일일 누적 손실 제한 (%)
                ("RISK", "IS_LOCKED", "N"),               # 매수 기능 강제 잠금 여부 (Y/N)
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
        except Exception as e: 
            conn.execute("ROLLBACK;")
            print(f"🔥 Account DB 에러: {e}") 
        finally:
            conn.close()

    # 대표적으로 Strategy 테이블 수정 예시 (Market, Account도 동일하게 DELETE 대신 REPLACE INTO 권장)
    def update_strategy_table(self, data_list):
        if not data_list: return
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("BEGIN TRANSACTION;")
            # ❌ conn.execute("DELETE FROM StrategyStatus") (삭제)
            
            # ✅ (수정 후) ai_prob와 status_msg를 추가하고 REPLACE INTO로 덮어쓰기!
            conn.executemany('''
                REPLACE INTO StrategyStatus (symbol, symbol_name, ai_prob, ma_5, ma_20, RSI, macd, signal, status_msg) 
                VALUES (:symbol, :symbol_name, :ai_prob, :ma_5, :ma_20, :RSI, :macd, :signal, :status_msg)
            ''', data_list)
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
        finally:
            conn.close()

    # ✅ (수정 후) StrategyStatus 테이블에 실시간 메시지와 AI 점수를 즉각 업데이트!
    def update_realtime(self, symbol, current_price, ai_score, holding_str, status_msg):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("UPDATE StrategyStatus SET ai_prob = ?, status_msg = ? WHERE symbol = ?", (ai_score, status_msg, symbol))
        except Exception:
            pass # 락 걸려도 무시하고 다음 사이클에 업데이트
        finally:
            conn.close()

    def insert_price_history(self, symbol, price):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO PriceHistory (symbol, price) VALUES (?, ?)", (symbol, price))
            conn.execute('''DELETE FROM PriceHistory WHERE symbol=? AND id NOT IN (SELECT id FROM PriceHistory WHERE symbol=? ORDER BY created_at DESC LIMIT 500)''', (symbol, symbol))
        finally:
            conn.close()

    def insert_log(self, log_level, message):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO SharedLogs (log_level, message) VALUES (?, ?)", (log_level, message))
        except sqlite3.OperationalError as e:
            print(f"로그 기록 중 DB 락 발생 무시됨: {e}")
        finally:
            conn.close()

    # [DB_Manager.py] 함수 전체를 아래로 덮어쓰기 하세요.
    def insert_trade_history(self, order_no, symbol, trade_type, price, qty, yield_rate=0.0):
        """ 
        주문 내역을 DB에 '미체결' 상태로 먼저 기록합니다. 
        이후 Ticker(웹소켓)가 이 order_no를 찾아서 '체결완료'로 바꿉니다.
        """
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute('''INSERT INTO TradeHistory 
                (order_no, symbol, symbol_name, order_type, order_price, order_quantity, filled_quantity, order_time, Status, order_yield) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                (str(order_no), symbol, "-", trade_type, price, qty, 0, 
                 datetime.datetime.now().strftime("%H:%M:%S"), "미체결", f"{yield_rate}%"))
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