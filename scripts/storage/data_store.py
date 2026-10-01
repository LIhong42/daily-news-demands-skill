"""
SQLite 数据存储模块（精简移植自 TrendSearch-main 的 DataStore）
- 保留 news / demands / news_report / demands_report / daily_runs 五张表
- 去掉 users / verification_codes / embedding（认证/向量检索不在本 skill 范围）
- 保留 INSERT OR IGNORE 去重、PRAGMA WAL、batch executemany 等关键优化
"""
import sqlite3
import hashlib
import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager


def hash_url(url: str) -> str:
    """对 URL 做 SHA256 hash（用于 url_hash 字段去重）"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def generate_uuid() -> str:
    """生成 UUID（用于 news / demands 的 uuid 字段）"""
    return str(uuid.uuid4())


def now_iso() -> str:
    """当前 UTC 时间，ISO 8601 格式"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


class DataStore:
    """精简版 DataStore：news + demands + 报告 + 运行日志"""

    ALLOWED_ORDERS = {"created_at DESC", "created_at ASC",
                       "fetched_at DESC", "fetched_at ASC",
                       "score DESC", "score ASC",
                       "priority_score DESC", "priority_score ASC"}

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.output_dir = project_root / "data"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(self.output_dir / "daily_news.db")
        else:
            self.db_path = str(Path(db_path).parent / Path(db_path).name)
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    @contextmanager
    def get_cursor(self):
        conn = self._get_connection()
        try:
            with conn:
                yield conn.cursor()
        except Exception:
            raise

    def _init_db(self):
        with self.get_cursor() as cursor:
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    url_hash TEXT UNIQUE NOT NULL,
                    title TEXT,
                    summary TEXT,
                    content TEXT,
                    source TEXT,
                    main_points TEXT,
                    hot_reason TEXT,
                    score REAL DEFAULT 0,
                    fetched_at TEXT DEFAULT (datetime('now')),
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS demands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE NOT NULL,
                    derived_from_news_uuids TEXT DEFAULT '[]',
                    title TEXT NOT NULL,
                    demand_scenario TEXT,
                    user_profile TEXT,
                    description TEXT,
                    value TEXT,
                    proposed_solution TEXT,
                    feasibility TEXT DEFAULT '中' CHECK(feasibility IN ('高','中','低')),
                    priority_score REAL DEFAULT 0,
                    tags TEXT DEFAULT '[]',
                    evidence TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS news_report (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE NOT NULL,
                    report_markdown TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS demands_report (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uuid TEXT UNIQUE NOT NULL,
                    report_markdown TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS daily_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date TEXT UNIQUE NOT NULL,
                    fetched_count INTEGER DEFAULT 0,
                    mined_count INTEGER DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    notes TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_news_url_hash ON news(url_hash);
                CREATE INDEX IF NOT EXISTS idx_news_created_at ON news(created_at);
                CREATE INDEX IF NOT EXISTS idx_news_source ON news(source);
                CREATE INDEX IF NOT EXISTS idx_news_score ON news(score);
                CREATE INDEX IF NOT EXISTS idx_demands_created_at ON demands(created_at);
                CREATE INDEX IF NOT EXISTS idx_demands_priority ON demands(priority_score);
                CREATE INDEX IF NOT EXISTS idx_demands_feasibility ON demands(feasibility);
                CREATE INDEX IF NOT EXISTS idx_news_report_created_at ON news_report(created_at);
                CREATE INDEX IF NOT EXISTS idx_demands_report_created_at ON demands_report(created_at);
            """)

    # ==================== News ====================

    def add_news(self, news_data: Dict[str, Any]) -> Optional[str]:
        """添加单条新闻。返回 UUID 或 None（重复）"""
        uuid_val = news_data.get("uuid") or generate_uuid()
        url = news_data.get("url", "")
        if not url:
            return None
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT OR IGNORE INTO news
                (uuid, url, url_hash, title, summary, content, source, main_points, hot_reason, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uuid_val, url, hash_url(url),
                news_data.get("title"),
                news_data.get("summary", ""),
                news_data.get("content", ""),
                news_data.get("source"),
                news_data.get("main_points", ""),
                news_data.get("hot_reason", ""),
                news_data.get("score", 0),
            ))
            return uuid_val if cursor.rowcount > 0 else None

    def batch_add_news(self, news_list: List[Dict[str, Any]]) -> int:
        """批量添加新闻。返回成功条数"""
        if not news_list:
            return 0
        params = []
        for data in news_list:
            url = data.get("url", "")
            if not url:
                continue
            params.append((
                data.get("uuid") or generate_uuid(),
                url, hash_url(url),
                data.get("title"),
                data.get("summary", ""),
                data.get("content", ""),
                data.get("source"),
                data.get("main_points", ""),
                data.get("hot_reason", ""),
                data.get("score", 0),
            ))
        with self.get_cursor() as cursor:
            cursor.executemany("""
                INSERT OR IGNORE INTO news
                (uuid, url, url_hash, title, summary, content, source, main_points, hot_reason, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
            return cursor.rowcount

    def list_news(self,
                  source: Optional[str] = None,
                  category: Optional[str] = None,
                  hours: Optional[int] = None,
                  since: Optional[str] = None,
                  limit: int = 50,
                  order_by: str = "score DESC",
                  sources_by_category: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """查询新闻列表（多条件）。

        - ``source``: 单个 source 名（向后兼容）
        - ``sources_by_category``: 由调用方传入"该 category 下所有 source 名"列表
          （list_news 不读 config，便于测试 / 解耦）
        - ``category``: 仅作为参数签名兼容保留；实际过滤请传 ``sources_by_category``
        """
        order_by = order_by if order_by in self.ALLOWED_ORDERS else "score DESC"
        where_clauses, params = [], []
        # source 过滤（支持单值或多值）
        source_filter: Optional[List[str]] = None
        if sources_by_category:
            source_filter = list(sources_by_category)
        if source:
            # 多个 source 以英文逗号分隔
            parts = [s.strip() for s in str(source).split(",") if s.strip()]
            if source_filter is None:
                source_filter = parts
            else:
                source_filter = [s for s in parts if s in source_filter] or parts
        if source_filter:
            placeholders = ",".join("?" * len(source_filter))
            where_clauses.append(f"source IN ({placeholders})")
            params.extend(source_filter)
        if since:
            where_clauses.append("created_at >= ?")
            params.append(since)
        elif hours is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            where_clauses.append("created_at >= ?")
            params.append(cutoff)
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        sql = f"SELECT * FROM news WHERE {where_sql} ORDER BY {order_by} LIMIT ?"
        params.append(limit)
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_news_by_uuid(self, uuid_val: str) -> Optional[Dict[str, Any]]:
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM news WHERE uuid = ?", (uuid_val,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def random_news(self,
                    source: Optional[str] = None,
                    hours: Optional[int] = None,
                    limit: int = 5,
                    exclude_uuids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        随机返回 N 条新闻（SQLite ORDER BY RANDOM()）。
        可按 hours/source 过滤，可排除指定 uuid（避免重复浏览）。
        """
        where_clauses, params = [], []
        if source:
            where_clauses.append("source = ?")
            params.append(source)
        if hours is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            where_clauses.append("created_at >= ?")
            params.append(cutoff)
        if exclude_uuids:
            placeholders = ",".join("?" * len(exclude_uuids))
            where_clauses.append(f"uuid NOT IN ({placeholders})")
            params.extend(exclude_uuids)
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        sql = f"SELECT * FROM news WHERE {where_sql} ORDER BY RANDOM() LIMIT ?"
        params.append(limit)
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]

    def count_news(self, hours: Optional[int] = None) -> int:
        with self.get_cursor() as cursor:
            if hours is None:
                cursor.execute("SELECT COUNT(*) AS c FROM news")
            else:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("SELECT COUNT(*) AS c FROM news WHERE created_at >= ?", (cutoff,))
            return cursor.fetchone()["c"]

    def has_news_today(self, source: str, date: Optional[str] = None) -> bool:
        """判断指定日期指定源是否已有新闻（用于每日缓存）"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        with self.get_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS c FROM news WHERE source = ? AND date(created_at) = ?",
                (source, date),
            )
            return cursor.fetchone()["c"] > 0

    def list_news_by_date(self, date: str, source: str) -> List[Dict[str, Any]]:
        """查询指定日期指定源的全部新闻（用于缓存命中分支）"""
        with self.get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM news WHERE source = ? AND date(created_at) = ? "
                "ORDER BY score DESC, id DESC",
                (source, date),
            )
            return [dict(r) for r in cursor.fetchall()]

    def delete_news_for_date(self, date: str) -> int:
        """删除指定日期的所有新闻（用于 refresh 子命令强制重抓）"""
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM news WHERE date(created_at) = ?", (date,))
            cursor.execute(
                "DELETE FROM daily_runs WHERE run_date = ?", (date,)
            )
            return cursor.rowcount

    # ==================== Demands ====================

    def add_demand(self, demand_data: Dict[str, Any]) -> Optional[str]:
        """添加单条需求。返回 UUID 或 None"""
        uuid_val = demand_data.get("uuid") or generate_uuid()
        derived = json.dumps(demand_data.get("derived_from_news_uuids", []), ensure_ascii=False)
        tags = json.dumps(demand_data.get("tags", []), ensure_ascii=False)
        evidence = json.dumps(demand_data.get("evidence", {}), ensure_ascii=False)
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT OR IGNORE INTO demands
                (uuid, derived_from_news_uuids, title, demand_scenario, user_profile,
                 description, value, proposed_solution, feasibility,
                 priority_score, tags, evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                uuid_val, derived,
                demand_data.get("title", ""),
                demand_data.get("demand_scenario"),
                demand_data.get("user_profile"),
                demand_data.get("description"),
                demand_data.get("value"),
                demand_data.get("proposed_solution"),
                demand_data.get("feasibility", "中"),
                demand_data.get("priority_score", 0),
                tags, evidence,
            ))
            return uuid_val if cursor.rowcount > 0 else None

    def batch_add_demands(self, demands_list: List[Dict[str, Any]]) -> int:
        """批量添加需求。返回成功条数"""
        if not demands_list:
            return 0
        params = []
        for d in demands_list:
            params.append((
                d.get("uuid") or generate_uuid(),
                json.dumps(d.get("derived_from_news_uuids", []), ensure_ascii=False),
                d.get("title", ""),
                d.get("demand_scenario"),
                d.get("user_profile"),
                d.get("description"),
                d.get("value"),
                d.get("proposed_solution"),
                d.get("feasibility", "中"),
                d.get("priority_score", 0),
                json.dumps(d.get("tags", []), ensure_ascii=False),
                json.dumps(d.get("evidence", {}), ensure_ascii=False),
            ))
        with self.get_cursor() as cursor:
            cursor.executemany("""
                INSERT OR IGNORE INTO demands
                (uuid, derived_from_news_uuids, title, demand_scenario, user_profile,
                 description, value, proposed_solution, feasibility,
                 priority_score, tags, evidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, params)
            return cursor.rowcount

    def list_demands(self,
                     feasibility: Optional[str] = None,
                     min_priority: Optional[float] = None,
                     hours: Optional[int] = None,
                     limit: int = 50,
                     order_by: str = "priority_score DESC") -> List[Dict[str, Any]]:
        where_clauses, params = [], []
        if feasibility:
            where_clauses.append("feasibility = ?")
            params.append(feasibility)
        if min_priority is not None:
            where_clauses.append("priority_score >= ?")
            params.append(min_priority)
        if hours is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            where_clauses.append("created_at >= ?")
            params.append(cutoff)
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        order_by = order_by if order_by in self.ALLOWED_ORDERS else "priority_score DESC"
        sql = f"SELECT * FROM demands WHERE {where_sql} ORDER BY {order_by} LIMIT ?"
        params.append(limit)
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]

    def count_demands(self, hours: Optional[int] = None) -> int:
        with self.get_cursor() as cursor:
            if hours is None:
                cursor.execute("SELECT COUNT(*) AS c FROM demands")
            else:
                cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("SELECT COUNT(*) AS c FROM demands WHERE created_at >= ?", (cutoff,))
            return cursor.fetchone()["c"]

    def random_demands(self,
                       feasibility: Optional[str] = None,
                       min_priority: Optional[float] = None,
                       hours: Optional[int] = None,
                       limit: int = 5,
                       exclude_uuids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        随机返回 N 条需求（SQLite ORDER BY RANDOM()）。
        可按 feasibility/min_priority/hours 过滤，可排除指定 uuid。
        """
        where_clauses, params = [], []
        if feasibility:
            where_clauses.append("feasibility = ?")
            params.append(feasibility)
        if min_priority is not None:
            where_clauses.append("priority_score >= ?")
            params.append(min_priority)
        if hours is not None:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            where_clauses.append("created_at >= ?")
            params.append(cutoff)
        if exclude_uuids:
            placeholders = ",".join("?" * len(exclude_uuids))
            where_clauses.append(f"uuid NOT IN ({placeholders})")
            params.extend(exclude_uuids)
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        sql = f"SELECT * FROM demands WHERE {where_sql} ORDER BY RANDOM() LIMIT ?"
        params.append(limit)
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            return [dict(r) for r in cursor.fetchall()]

    # ==================== Reports ====================

    def add_news_report(self, markdown: str, date_str: Optional[str] = None) -> str:
        uuid_val = generate_uuid()
        with self.get_cursor() as cursor:
            cursor.execute("INSERT INTO news_report (uuid, report_markdown) VALUES (?, ?)",
                           (uuid_val, markdown))
        return uuid_val

    def add_demands_report(self, markdown: str, date_str: Optional[str] = None) -> str:
        uuid_val = generate_uuid()
        with self.get_cursor() as cursor:
            cursor.execute("INSERT INTO demands_report (uuid, report_markdown) VALUES (?, ?)",
                           (uuid_val, markdown))
        return uuid_val

    def get_latest_news_report(self) -> Optional[Dict[str, Any]]:
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM news_report ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_latest_demands_report(self) -> Optional[Dict[str, Any]]:
        with self.get_cursor() as cursor:
            cursor.execute("SELECT * FROM demands_report ORDER BY created_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    # ==================== Daily Runs ====================

    def start_run(self, run_date: str) -> int:
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO daily_runs (run_date, started_at) VALUES (?, datetime('now'))
                ON CONFLICT(run_date) DO UPDATE SET started_at = datetime('now')
            """, (run_date,))
            cursor.execute("SELECT id FROM daily_runs WHERE run_date = ?", (run_date,))
            return cursor.fetchone()["id"]

    def finish_run(self, run_date: str, fetched_count: int, mined_count: int, notes: str = ""):
        with self.get_cursor() as cursor:
            cursor.execute("""
                UPDATE daily_runs
                SET finished_at = datetime('now'),
                    fetched_count = ?, mined_count = ?, notes = ?
                WHERE run_date = ?
            """, (fetched_count, mined_count, notes, run_date))

    # ==================== 统计与归档 ====================

    def get_stats(self) -> Dict[str, Any]:
        """汇总统计"""
        with self.get_cursor() as cursor:
            cursor.execute("SELECT source, COUNT(*) AS c FROM news GROUP BY source ORDER BY c DESC")
            source_dist = {r["source"]: r["c"] for r in cursor.fetchall() if r["source"]}

            cursor.execute("SELECT feasibility, COUNT(*) AS c FROM demands GROUP BY feasibility")
            feas_dist = {r["feasibility"]: r["c"] for r in cursor.fetchall()}

            cursor.execute("""
                SELECT t.value AS tag, COUNT(*) AS c
                FROM demands, json_each(demands.tags) AS t
                GROUP BY t.value ORDER BY c DESC LIMIT 20
            """)
            top_tags = [(r["tag"], r["c"]) for r in cursor.fetchall()]

        return {
            "news_total": self.count_news(),
            "demands_total": self.count_demands(),
            "source_distribution": source_dist,
            "feasibility_distribution": feas_dist,
            "top_tags": top_tags,
            "db_path": self.db_path,
        }

    def clean_old_data(self, days: int = 30) -> Dict[str, int]:
        """删除超过 N 天的数据（移植自原项目 DataStore.clean_old_data）"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM demands WHERE created_at < ?", (cutoff,))
            demands_deleted = cursor.rowcount
            cursor.execute("DELETE FROM news WHERE created_at < ?", (cutoff,))
            news_deleted = cursor.rowcount
            cursor.execute("DELETE FROM news_report WHERE created_at < ?", (cutoff,))
            news_report_deleted = cursor.rowcount
            cursor.execute("DELETE FROM demands_report WHERE created_at < ?", (cutoff,))
            demands_report_deleted = cursor.rowcount
        return {
            "news": news_deleted,
            "demands": demands_deleted,
            "news_reports": news_report_deleted,
            "demands_reports": demands_report_deleted,
        }

    def close(self):
        if hasattr(self._local, "conn"):
            try:
                self._local.conn.close()
            except Exception:
                pass
            finally:
                del self._local.conn


# ===============================================
# 全局单例（沿用原项目 _global_datastore 模式）
# ===============================================
_global_datastore: Optional[DataStore] = None


def get_datastore(db_path: Optional[str] = None) -> DataStore:
    """获取全局 DataStore 单例"""
    global _global_datastore
    if _global_datastore is None:
        _global_datastore = DataStore(db_path)
    return _global_datastore


def reset_datastore():
    """重置单例（CLI 测试用）"""
    global _global_datastore
    if _global_datastore is not None:
        _global_datastore.close()
    _global_datastore = None