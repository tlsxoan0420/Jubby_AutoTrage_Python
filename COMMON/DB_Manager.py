import sqlite3
import os
import datetime
import pandas as pd  
import time
import random  # 🚀 [추가] 스레드 충돌 분산을 위한 랜덤 모듈
import threading  # 상단에 추가!

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
        _db_write_lock = threading.Lock()
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
        """
        [상세 주석]
        스레드별 안전한 DB 접근을 위한 SQLite 연결 객체 생성 함수입니다.
        초단타(스캘핑) 자동매매의 수많은 스레드가 동시에 읽기/쓰기를 요청할 때
        락(Lock)이 걸리거나 튕기지 않도록 최적의 방어 옵션을 주입합니다.
        """
        # 🔥 check_same_thread=False : PyQt5의 여러 일꾼(QThread)들이 동시에 접근해도 파이썬이 에러를 뿜지 않게 강제 허용합니다.
        # 🔥 timeout=30 : 동시 접근으로 DB가 잠기더라도 뻗지 않고 최대 30초까지 인내심을 갖고 대기합니다.
        # 🔥 isolation_level=None : 자동 커밋(Auto-Commit) 모드로 전환하여 락(Lock)이 걸려있는 시간을 극단적으로 짧게 만듭니다.
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30, isolation_level=None)
        
        # 🔥 WAL (Write-Ahead Logging) 모드 : 쓰는 중에도 다른 스레드가 동시에 읽을 수 있게 해주는 마법의 락 해제 옵션입니다!
        conn.execute('PRAGMA journal_mode = WAL;')  
        
        # 🔥 NORMAL 동기화 : 디스크 쓰기 속도를 대폭 향상시켜 초단타 틱 데이터 저장 시 병목 현상을 없앱니다.
        conn.execute('PRAGMA synchronous = NORMAL;')
        
        # 🔥 busy_timeout : SQLite 엔진 내부적으로 DB가 바쁠 때 5초(5000ms) 동안 알아서 재시도하게 만듭니다.
        conn.execute('PRAGMA busy_timeout = 5000;') 
        
        # 🚀 [추가 최적화] cache_size : 하드디스크 대신 RAM 메모리(약 64MB)를 캐시로 사용하여 
        # 조회(SELECT) 및 쓰기(INSERT) 속도를 비약적으로 끌어올립니다.
        conn.execute('PRAGMA cache_size = -64000;')
        
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

            conn.execute("""
                CREATE TABLE IF NOT EXISTS TickerLogs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    level TEXT,
                    message TEXT
                )
            """)

            # =================================================================
            # 🚀 [MarketStatus 컬럼 보정]
            # =================================================================
            try:
                cursor = conn.execute("PRAGMA table_info(MarketStatus)")
                m_cols = [c[1] for c in cursor.fetchall()]
                if "last_price" not in m_cols: conn.execute("ALTER TABLE MarketStatus ADD COLUMN last_price REAL")
                if "ask_size" not in m_cols: conn.execute("ALTER TABLE MarketStatus ADD COLUMN ask_size REAL")
                if "bid_size" not in m_cols: conn.execute("ALTER TABLE MarketStatus ADD COLUMN bid_size REAL")
                if "vol_power" not in m_cols: conn.execute("ALTER TABLE MarketStatus ADD COLUMN vol_power REAL") # 🔥 [핵심 추가] 이 방이 없어서 현재가 업데이트가 튕겼습니다!
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

    # =======================================================================
    # 🛡️ 다발적 덮어쓰기(executemany) 전용 Database is Locked 완벽 방어 래퍼
    # =======================================================================
    def execute_many_with_retry(self, db_path, delete_query, insert_query, data_list):
        max_retries = 10
        for attempt in range(max_retries):
            conn = self._get_connection(db_path)
            try:
                conn.execute("BEGIN TRANSACTION;")
                if delete_query:
                    conn.execute(delete_query)
                conn.executemany(insert_query, data_list)
                conn.execute("COMMIT;")
                return True
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower():
                    if attempt < max_retries - 1:
                        # 🔥 대기 시간을 0.05초 -> 0.1초로 늘려 DB가 숨쉴 틈을 더 줍니다.
                        time.sleep(0.1) 
                        continue
                print(f"🚨 [DB 에러] {e} (Query: {delete_query})")
                return None
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
        # 🚀 [치명적 버그 수정] REPLACE INTO 대신 ON CONFLICT DO UPDATE를 사용하여
        # 기존 행을 삭제하지 않고 필요한 값만 살짝 덮어씌웁니다. (Ticker 데이터 증발 완벽 방지!)
        self.execute_many_with_retry(
            self.shared_db_path,
            None, # DELETE 쿼리 제거 (기존 데이터를 보존해야 함)
            '''
            INSERT INTO MarketStatus (symbol, symbol_name, last_price, open_price, high_price, low_price, return_1m, trade_amount, vol_energy, disparity, volume) 
            VALUES (:symbol, :symbol_name, :last_price, :open_price, :high_price, :low_price, :return_1m, :trade_amount, :vol_energy, :disparity, :volume)
            ON CONFLICT(symbol) DO UPDATE SET
                last_price=excluded.last_price, open_price=excluded.open_price, 
                high_price=excluded.high_price, low_price=excluded.low_price, 
                return_1m=excluded.return_1m, trade_amount=excluded.trade_amount, 
                vol_energy=excluded.vol_energy, disparity=excluded.disparity, volume=excluded.volume
                -- 💡 주의: 여기서 vol_power, ask_size, bid_size는 업데이트하지 않아야 FormTicker가 저장한 실시간 데이터가 보존됩니다!
            ''',
            data_list
        )

    def update_account_table(self, data_list):
        if not data_list: return
        # 🚀 [치명적 버그 수정] AccountStatus 테이블도 증발을 막기 위해 동일하게 변경합니다.
        self.execute_many_with_retry(
            self.shared_db_path,
            "DELETE FROM AccountStatus", # 잔고는 전량 매도 시 0주가 되어 표에서 사라져야 하므로 DELETE 후 INSERT 하는 것이 맞습니다. (유지)
            "REPLACE INTO AccountStatus (symbol, symbol_name, quantity, avg_price, current_price, pnl_amt, pnl_rate, available_cash) VALUES (:symbol, :symbol_name, :quantity, :avg_price, :current_price, :pnl_amt, :pnl_rate, :available_cash)",
            data_list
        )

    def update_strategy_table(self, data_list):
        if not data_list: return
        
        # 🛡️ [수정] 다중 스레드 환경에서 락(Lock)이 걸렸을 때 데이터 유실을 막기 위해 
        # 최대 5번까지 0.1초 간격으로 재시도하는 강력한 방어막을 추가했습니다.
        max_retries = 5
        
        for attempt in range(max_retries):
            conn = self._get_connection(self.shared_db_path)
            try:
                conn.execute("BEGIN TRANSACTION;")
                # 🔥 REPLACE INTO 대신 INSERT ON CONFLICT를 사용하여, 기존의 status_msg(상태 메시지)가 
                # 덮어씌워져 날아가는 현상을 완벽하게 방지합니다!
                conn.executemany('''
                    INSERT INTO StrategyStatus (symbol, symbol_name, ai_prob, ma_5, ma_20, RSI, macd, signal, status_msg) 
                    VALUES (:symbol, :symbol_name, :ai_prob, :ma_5, :ma_20, :RSI, :macd, :signal, :status_msg)
                    ON CONFLICT(symbol) DO UPDATE SET
                    ai_prob=excluded.ai_prob, ma_5=excluded.ma_5, ma_20=excluded.ma_20, 
                    RSI=excluded.RSI, macd=excluded.macd, signal=excluded.signal, status_msg=excluded.status_msg
                ''', data_list)
                conn.execute("COMMIT;")
                return # 성공적으로 저장했으면 즉시 함수 탈출
                
            except sqlite3.OperationalError as e:
                conn.execute("ROLLBACK;") # 에러가 나면 찌꺼기가 남지 않게 무조건 롤백
                # 에러 원인이 'locked'(잠김) 이라면 숨 고르고 다시 시도
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    time.sleep(0.1) # 0.1초 대기 후 다시 문 두드리기
                    continue
                # 락 에러가 아니거나 최대 횟수를 초과하면 로그 출력 후 포기
                print(f"🚨 [DB 에러] 전략 상태 테이블 업데이트 실패: {e}")
                break
            finally:
                conn.close() # 통로는 무조건 닫아줌 (메모리 누수 방지)

    def insert_price_history(self, symbol, price):
        conn = self._get_connection(self.shared_db_path)
        try:
            conn.execute("INSERT INTO PriceHistory (symbol, price) VALUES (?, ?)", (symbol, price))
            conn.execute('''DELETE FROM PriceHistory WHERE symbol=? AND id NOT IN (SELECT id FROM PriceHistory WHERE symbol=? ORDER BY created_at DESC LIMIT 500)''', (symbol, symbol))
        finally: conn.close()

    def insert_log(self, log_level, message):
        conn = self._get_connection(self.shared_db_path)
        try:
            # 🚀 [추가] 파이썬에서 한국 시간(KST)을 정확히 계산합니다!
            kst_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
            time_str = kst_now.strftime("%Y-%m-%d %H:%M:%S")
            
            # 🚀 [핵심 수정] DB가 멋대로 시간을 찍게 두지 않고, 우리가 만든 'time_str'을 명시적으로 집어넣습니다.
            conn.execute("INSERT INTO SharedLogs (log_level, message, created_at) VALUES (?, ?, ?)", 
                         (log_level, message, time_str))
            conn.commit()
        except Exception as e: 
            print(f"로그 기록 중 에러: {e}")
        finally: 
            conn.close()

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
        
        # 🚀 [버그 완벽 수정] 15개의 수집기 스레드가 동시에 저장하려 할 때 병목(Lock)을 방지!
        # 자물쇠(Lock)를 채워서 오직 1명의 스레드만 순서대로 DB에 기록하게 만듭니다.
        with self._db_write_lock:
            max_retries = 10
            for attempt in range(max_retries):
                conn = self._get_connection(self.python_db_path)
                try:
                    # 쓰기 작업 실행
                    df.to_sql(table_name, conn, if_exists='append', index=False)
                    break # 성공 시 즉시 반복문 탈출
                except sqlite3.OperationalError as e:
                    # DB가 잠겨있을 경우 숨을 고르고 재시도
                    if "locked" in str(e).lower() and attempt < max_retries - 1:
                        time.sleep(random.uniform(0.1, 0.3))
                        continue
                    print(f"🚨 [DB 저장 에러] {table_name} 쓰기 실패: {e}")
                    break
                finally:
                    conn.close() # 작업이 끝난 통로는 무조건 닫기

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
        row = self.execute_with_retry(
            self.shared_db_path, 
            "SELECT last_price FROM MarketStatus WHERE symbol = ?", 
            (symbol,), 
            fetch='one' # 💡 1개만 가져와!
        )
        return float(row[0]) if row and row[0] is not None else 0.0
    
    def get_multiple_realtime_prices(self, symbol_list):
        """ 🚀 [핵심 최적화] 여러 종목의 현재가를 단 한 번의 쿼리로 싹 쓸어옵니다! """
        if not symbol_list: return {}
        
        # ?,?,? 형태로 종목 개수만큼 공간을 만듭니다.
        placeholders = ','.join('?' * len(symbol_list))
        query = f"SELECT symbol, last_price FROM MarketStatus WHERE symbol IN ({placeholders})"
        
        rows = self.execute_with_retry(
            self.shared_db_path, 
            query, 
            tuple(symbol_list), 
            fetch='all' # 💡 매칭되는 거 전부 다 가져와!
        )
        
        # {'005930': 75000.0, '000660': 150000.0} 형태의 딕셔너리로 예쁘게 포장해서 돌려줍니다.
        return {row[0]: float(row[1]) for row in rows} if rows else {}

    def update_shared_risk_status(self, is_locked):
        val = "Y" if is_locked else "N"
        self.execute_with_retry(
            self.shared_db_path,
            "INSERT OR REPLACE INTO SharedSettings (category, key, value) VALUES (?, ?, ?)",
            ("RISK", "IS_LOCKED", val)
            # 💡 fetch=None 이 기본값이므로 생략 (읽어올 게 없으니까!)
        )
    
    def insert_ticker_log(self, level, message):
        """ Ticker 전용 로그를 DB에 저장하는 함수 """
        try:
            # 💡 get_shared_db_path를 사용하여 공유 DB에 저장
            conn = self._get_connection(self.shared_db_path)
            # 한국 시간으로 저장하기 위해 datetime 사용
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute("INSERT INTO TickerLogs (time, level, message) VALUES (?, ?, ?)", 
                        (now, level, message))
            conn.close()
        except Exception as e:
            print(f"❌ Ticker 로그 저장 실패: {e}")

    # =======================================================================
    # 🛡️ [핵심 추가] Database is Locked 완벽 방어 만능 래퍼 함수
    # =======================================================================
    def execute_with_retry(self, db_path, query, params=(), fetch=None):
        """
        [상세 설명]
        동시 다발적 접근으로 인한 잠김(Lock) 발생 시 튕기지 않고 자동으로 대기 후 재시도합니다.
        """
        # 🚀 [수정 1] 스레드가 몰릴 때를 대비해 최대 30번(약 3~4초)까지 문을 두드리도록 대폭 증가!
        max_retries = 30 
        
        for attempt in range(max_retries):
            # 🚀 [수정 2] timeout=15.0 옵션을 주어 SQLite 자체적으로도 15초간 락 해제를 기다리게 합니다.
            conn = sqlite3.connect(db_path, timeout=15.0) 
            
            # WAL 모드 강제 적용 (기존 코드와 동일)
            conn.execute("PRAGMA journal_mode=WAL;")
            
            try:
                cursor = conn.execute(query, params)
                
                # 1. 목적에 맞게 데이터 읽어오기
                if fetch == 'one':
                    result = cursor.fetchone()
                elif fetch == 'all':
                    result = cursor.fetchall()
                else:
                    conn.commit() # 쓰기 작업 후에는 확실히 커밋 도장 꽝!
                    result = cursor.rowcount # 반영된 줄 수 리턴
                    
                return result # 성공하면 즉시 결과 돌려주고 함수 종료!
                
            except sqlite3.OperationalError as e:
                # 2. 에러가 났는데 만약 "Locked" (잠김) 이라면?
                if "locked" in str(e).lower():
                    if attempt < max_retries - 1:
                        # 🚀 [핵심 수정 3] 모든 스레드가 똑같은 시간에 깨어나서 다시 충돌하는 것을 막기 위해
                        # 0.05초 ~ 0.15초 사이의 '랜덤(Random)'한 시간만큼 대기하도록 분산시킵니다!
                        time.sleep(random.uniform(0.05, 0.15))
                        continue
                
                # 락 에러가 아니거나, 30번 다 실패하면 로그 출력 (실제로는 여기까지 안 옵니다)
                print(f"🚨 [DB 락 에러] 쿼리 실행 실패: {e}")
                return None
            finally:
                if conn:
                    conn.close() # 작업이 끝난 통로는 무조건 닫아서 다른 스레드에게 양보