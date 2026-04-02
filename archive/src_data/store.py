"""DuckDB + Parquet 分层存储模块"""

from pathlib import Path

import duckdb
import pandas as pd
from loguru import logger

from src.infra.config import get_settings, PROJECT_ROOT

# SQL建表语句
DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS daily_quote (
        code        VARCHAR,
        date        DATE,
        open        DOUBLE,
        high        DOUBLE,
        low         DOUBLE,
        close       DOUBLE,
        volume      DOUBLE,
        amount      DOUBLE,
        turnover    DOUBLE,
        pre_close   DOUBLE,
        change_pct  DOUBLE,
        PRIMARY KEY (code, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS adj_factor (
        code        VARCHAR,
        date        DATE,
        forward_adj DOUBLE,
        PRIMARY KEY (code, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS northbound_stock (
        code        VARCHAR,
        date        DATE,
        buy_amount  DOUBLE,
        sell_amount DOUBLE,
        net_amount  DOUBLE,
        hold_share  DOUBLE,
        hold_ratio  DOUBLE,
        PRIMARY KEY (code, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS northbound_daily (
        date        DATE PRIMARY KEY,
        total_net   DOUBLE,
        sh_net      DOUBLE,
        sz_net      DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS financial_indicator (
        code        VARCHAR,
        end_date    DATE,
        roe         DOUBLE,
        roa         DOUBLE,
        gross_margin DOUBLE,
        net_margin  DOUBLE,
        debt_ratio  DOUBLE,
        ocf_ratio   DOUBLE,
        revenue_yoy DOUBLE,
        profit_yoy  DOUBLE,
        revenue     DOUBLE,
        net_profit  DOUBLE,
        ar_ratio    DOUBLE,
        goodwill_ratio DOUBLE,
        PRIMARY KEY (code, end_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_index_daily (
        index_code  VARCHAR,
        date        DATE,
        open        DOUBLE,
        high        DOUBLE,
        low         DOUBLE,
        close       DOUBLE,
        volume      DOUBLE,
        amount      DOUBLE,
        PRIMARY KEY (index_code, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS industry_index_daily (
        industry_code VARCHAR,
        date        DATE,
        open        DOUBLE,
        high        DOUBLE,
        low         DOUBLE,
        close       DOUBLE,
        volume      DOUBLE,
        amount      DOUBLE,
        PRIMARY KEY (industry_code, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_sentiment (
        date        DATE PRIMARY KEY,
        up_count    INTEGER,
        down_count  INTEGER,
        flat_count  INTEGER,
        limit_up    INTEGER,
        limit_down  INTEGER,
        total_amount DOUBLE,
        ad_ratio    DOUBLE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suspension (
        code        VARCHAR,
        date        DATE,
        is_suspended BOOLEAN,
        PRIMARY KEY (code, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_info (
        code        VARCHAR PRIMARY KEY,
        name        VARCHAR,
        sw_l1       VARCHAR,
        sw_l2       VARCHAR,
        sw_l3       VARCHAR,
        sector      VARCHAR,
        list_date   DATE,
        is_st       BOOLEAN
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS concept_stock (
        code        VARCHAR,
        concept     VARCHAR,
        PRIMARY KEY (code, concept)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_score (
        code        VARCHAR,
        date        DATE,
        score_total DOUBLE,
        score_fundamental DOUBLE,
        score_technical DOUBLE,
        score_capital DOUBLE,
        score_llm   DOUBLE,
        delta_s     DOUBLE,
        delta_s_accel DOUBLE,
        rank        INTEGER,
        PRIMARY KEY (code, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS portfolio (
        code        VARCHAR PRIMARY KEY,
        buy_date    DATE,
        buy_price   DOUBLE,
        shares      INTEGER,
        current_price DOUBLE,
        pnl_pct     DOUBLE,
        target_weight DOUBLE,
        status      VARCHAR,
        updated_at  TIMESTAMP
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS trade_log_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS trade_log (
        id          INTEGER PRIMARY KEY DEFAULT nextval('trade_log_seq'),
        code        VARCHAR,
        action      VARCHAR,
        price       DOUBLE,
        shares      INTEGER,
        amount      DOUBLE,
        reason      VARCHAR,
        score_at_action DOUBLE,
        date        DATE,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS alert_log_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS alert_log (
        id          INTEGER PRIMARY KEY DEFAULT nextval('alert_log_seq'),
        code        VARCHAR,
        alert_type  VARCHAR,
        severity    VARCHAR,
        message     VARCHAR,
        data_json   VARCHAR,
        date        DATE,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS llm_cache (
        cache_key   VARCHAR PRIMARY KEY,
        code        VARCHAR,
        analysis_type VARCHAR,
        date        DATE,
        result_json VARCHAR,
        model       VARCHAR,
        prompt_hash VARCHAR,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS nav_history (
        date        DATE PRIMARY KEY,
        nav         DOUBLE,
        total_assets DOUBLE,
        cash        DOUBLE,
        market_value DOUBLE,
        daily_return DOUBLE,
        cumulative_return DOUBLE,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS news_seq START 1
    """,
    """
    CREATE TABLE IF NOT EXISTS news (
        id          INTEGER PRIMARY KEY DEFAULT nextval('news_seq'),
        code        VARCHAR,
        publish_time TIMESTAMP,
        title       VARCHAR,
        source      VARCHAR,
        content     VARCHAR,
        sentiment_score DOUBLE,
        summary     VARCHAR,
        importance  VARCHAR,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]


class DataStore:
    """DuckDB + Parquet 数据存储"""

    def __init__(self, db_path: str = None, parquet_dir: str = None):
        settings = get_settings()
        storage = settings.get("storage", {})

        self.db_path = db_path or str(PROJECT_ROOT / storage.get("duckdb_path", "data/stockradar.duckdb"))
        self.parquet_dir = Path(parquet_dir or str(PROJECT_ROOT / storage.get("parquet_dir", "data/parquet")))

        # 确保目录存在
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.parquet_dir.mkdir(parents=True, exist_ok=True)

        self.conn = duckdb.connect(self.db_path)
        self._init_tables()

    def _init_tables(self):
        """初始化所有表"""
        for ddl in DDL_STATEMENTS:
            try:
                self.conn.execute(ddl)
            except duckdb.CatalogException as e:
                if "already exists" not in str(e).lower():
                    raise
        logger.info("DuckDB表初始化完成")

    def upsert_df(self, table: str, df: pd.DataFrame, pk_cols: list):
        """向表中写入数据（存在则删除旧数据再插入）

        Args:
            table: 表名
            df: 数据
            pk_cols: 主键列名列表
        """
        if df is None or df.empty:
            return

        # 注册DataFrame为临时视图
        self.conn.register("temp_data", df)

        # 删除已有记录
        if pk_cols:
            conditions = " AND ".join(
                f"{col} IN (SELECT DISTINCT {col} FROM temp_data)" for col in pk_cols
            )
            self.conn.execute(f"DELETE FROM {table} WHERE {conditions}")

        # 插入新数据
        cols = ", ".join(df.columns)
        self.conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM temp_data")

        self.conn.unregister("temp_data")
        logger.info(f"写入 {table}: {len(df)} 条记录")

    def query(self, sql: str, params=None) -> pd.DataFrame:
        """执行SQL查询，返回DataFrame"""
        if params:
            return self.conn.execute(sql, params).df()
        return self.conn.execute(sql).df()

    def execute(self, sql: str, params=None):
        """执行SQL（无返回）"""
        if params:
            self.conn.execute(sql, params)
        else:
            self.conn.execute(sql)

    def get_table(self, table: str, columns: str = "*",
                  where: str = None) -> pd.DataFrame:
        """读取整张表（可选过滤）"""
        sql = f"SELECT {columns} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return self.conn.execute(sql).df()

    def get_latest_date(self, table: str, date_col: str = "date") -> pd.Timestamp:
        """获取表中最新日期"""
        try:
            result = self.conn.execute(
                f"SELECT MAX({date_col}) FROM {table}"
            ).fetchone()
            return pd.Timestamp(result[0]) if result[0] else None
        except Exception:
            return None

    # ============ Parquet 冷数据操作 ============

    def save_to_parquet(self, df: pd.DataFrame, filename: str):
        """保存数据到Parquet文件"""
        path = self.parquet_dir / filename
        df.to_parquet(path, engine="pyarrow", index=False)
        logger.info(f"保存Parquet: {path}, {len(df)} 条记录")

    def read_from_parquet(self, filename: str) -> pd.DataFrame:
        """从Parquet文件读取"""
        path = self.parquet_dir / filename
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path, engine="pyarrow")

    def query_parquet(self, filename: str, sql_suffix: str = "") -> pd.DataFrame:
        """直接查询Parquet文件（DuckDB原生支持）"""
        path = self.parquet_dir / filename
        if not path.exists():
            return pd.DataFrame()
        sql = f"SELECT * FROM read_parquet('{path}')"
        if sql_suffix:
            sql += f" {sql_suffix}"
        return self.conn.execute(sql).df()

    def archive_to_parquet(self, table: str, year: int, date_col: str = "date"):
        """将指定年份的数据归档到Parquet"""
        filename = f"{table}_{year}.parquet"

        # 读取该年数据
        df = self.conn.execute(
            f"SELECT * FROM {table} WHERE YEAR({date_col}) = {year}"
        ).df()

        if df.empty:
            logger.info(f"{table} 表 {year} 年无数据，跳过归档")
            return

        # 合并已有Parquet文件
        existing = self.read_from_parquet(filename)
        if not existing.empty:
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates()

        self.save_to_parquet(df, filename)

        # 删除DuckDB中已归档的数据
        self.conn.execute(
            f"DELETE FROM {table} WHERE YEAR({date_col}) = {year}"
        )
        logger.info(f"归档 {table} {year} 年数据到 {filename}")

    def get_daily_quote_with_cold(self, code: str = None,
                                  start_date: str = None,
                                  end_date: str = None) -> pd.DataFrame:
        """联合查询热数据(DuckDB)和冷数据(Parquet)

        DuckDB 可以直接 union 冷热数据
        """
        conditions = []
        if code:
            conditions.append(f"code = '{code}'")
        if start_date:
            conditions.append(f"date >= '{start_date}'")
        if end_date:
            conditions.append(f"date <= '{end_date}'")

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        # 查热数据
        hot_sql = f"SELECT * FROM daily_quote{where}"

        # 查冷数据（扫描所有年份Parquet文件）
        parquet_files = sorted(self.parquet_dir.glob("daily_quote_*.parquet"))
        if parquet_files:
            parquet_paths = [str(f) for f in parquet_files]
            union_parts = []
            for p in parquet_paths:
                union_parts.append(f"SELECT * FROM read_parquet('{p}')")
            cold_sql = " UNION ALL ".join(union_parts) + where

            full_sql = f"({hot_sql}) UNION ALL ({cold_sql}) ORDER BY code, date"
        else:
            full_sql = f"{hot_sql} ORDER BY code, date"

        return self.conn.execute(full_sql).df()

    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
            logger.info("DuckDB连接已关闭")
