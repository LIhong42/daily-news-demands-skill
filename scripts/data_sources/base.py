"""
数据源抽象基类（精简移植自 TrendSearch-main 的 data_sources/base.py）
- DataItem: 同构数据项
- BaseDataSource: 所有数据源继承此类，实现统一接口
- 去掉 crawl4ai 浏览器渲染依赖，用 requests + BeautifulSoup 兜底
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import random
import time
import re
import os
import json
from pathlib import Path

import requests
from pydantic import BaseModel, Field

# 让非 CLI 入口（registry/single-source 测试）也能读到 .env
from dotenv import load_dotenv
_pkg_root = Path(__file__).resolve().parent.parent.parent
_env_path = _pkg_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv(_pkg_root / ".env.example")


class DataItem(BaseModel):
    """统一数据项（直接复用 TrendSearch 的字段）"""
    title: Optional[str] = Field("", description="标题")
    url: Optional[str] = Field("", description="链接")
    content: Optional[str] = Field("", description="正文/摘要内容")
    source: Optional[str] = Field("", description="数据源名称")
    summary: Optional[str] = Field("", description="摘要")
    extra: Optional[Dict[str, Any]] = Field(default_factory=dict, description="额外字段")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class BaseDataSource(ABC):
    """数据源基类。所有数据源实现 fetch() 方法即可。"""

    DEFAULT_HEADERS = {
        "User-Agent": os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }

    def __init__(self, name: Optional[str] = None,
                 store: Optional[Any] = None):
        # 默认用 cls.SOURCE_NAME（装饰器注入），便于无参实例化
        self.name = name or getattr(self, "SOURCE_NAME", self.__class__.__name__)
        self.timeout = int(os.getenv("REQUEST_TIMEOUT", 30))
        self.max_retries = int(os.getenv("MAX_RETRIES", 3))
        self.rate_delay = float(os.getenv("RATE_LIMIT_DELAY", 1.0))
        # store 由 registry 注入，源类 fetch() 可用它做每日缓存命中
        self.store = store

    @abstractmethod
    def fetch(self, limit: int = 20) -> List[DataItem]:
        """抓取数据。每个子类必须实现。"""
        ...

    # --------- 公共 HTTP 工具 ---------

    def _http_get(self, url: str, params: Optional[Dict] = None,
                  headers: Optional[Dict] = None) -> Optional[requests.Response]:
        """带重试的 GET 请求"""
        merged_headers = {**self.DEFAULT_HEADERS, **(headers or {})}
        for attempt in range(self.max_retries):
            try:
                resp = requests.get(
                    url, params=params, headers=merged_headers,
                    timeout=self.timeout, allow_redirects=True,
                )
                resp.raise_for_status()
                return resp
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.rate_delay * (attempt + 1))
                    continue
                print(f"[{self.name}] GET 失败 ({url}): {e}")
                return None

    def _http_get_json(self, url: str, params: Optional[Dict] = None,
                       headers: Optional[Dict] = None) -> Optional[Any]:
        """GET 并解析 JSON"""
        resp = self._http_get(url, params, headers)
        if resp is None:
            return None
        try:
            return resp.json()
        except Exception as e:
            print(f"[{self.name}] JSON 解析失败: {e}")
            return None

    def _newsnow_get(self, source_id: str) -> Optional[Any]:
        """
        参考 TrendSearch-main 的 BaseDataSource.fetch_data_with_news_now
        调用自建 NewsNow API（同时识别 NEWSNOW_BASE_URL 与 NEWS_API_URL）
        """
        base = (os.getenv("NEWSNOW_BASE_URL") or os.getenv("NEWS_API_URL") or "").strip()
        if not base:
            return None
        url = f"{base.rstrip('/')}?id={source_id}&latest"
        data = self._http_get_json(url)
        if data:
            time.sleep(self.rate_delay * random.uniform(0.5, 1.5))
        return data

    def _newsnow_fetch_items(self, newsnow_id: str, limit: int) -> List["DataItem"]:
        """
        统一走 NewsNow API → 返回 DataItem 列表
        - newsnow_id: sources.json 中 newsnow_id 字段（注意 bilibili_hot → bilibili）
        - limit: 最多返回多少条
        """
        data = self._newsnow_get(newsnow_id)
        if not data or not isinstance(data, dict):
            return []
        raw_items = data.get("items", []) or []
        items: List[DataItem] = []
        for entry in raw_items[:limit]:
            title = (entry.get("title") or "").strip()
            url = entry.get("url") or entry.get("mobileUrl") or ""
            if not title or not url:
                continue
            # 摘要：从 extra.info 或其他字段提取
            summary = ""
            try:
                extra = entry.get("extra") or {}
                info = extra.get("info") if isinstance(extra, dict) else None
                if isinstance(info, str):
                    summary = info[:300]
            except Exception:
                summary = ""
            items.append(DataItem(
                title=title,
                url=url,
                content="",
                source=self.name,
                summary=summary,
                extra={"newsnow_id": newsnow_id, "raw": entry},
            ))
        return items

    # --------- 每日缓存命中（默认实现：源类可重写以注入 NEWSNOW_ID）---------

    NEWSNOW_ID: Optional[str] = None  # 子类覆盖

    def _cached_or_newsnow(self, limit: int) -> List["DataItem"]:
        """统一 fetch() 模板：先查 DB 当天是否已有该源数据；没有则走 NewsNow。
        子类只需定义 NEWSNOW_ID 即可使用。非 NewsNow 源需重写 fetch()。"""
        from datetime import datetime as _dt
        today = _dt.now().strftime("%Y-%m-%d")
        if self.store is not None and self.store.has_news_today(self.name, today):
            rows = self.store.list_news_by_date(today, self.name)
            items: List[DataItem] = []
            for r in rows[:limit]:
                items.append(DataItem(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    content=r.get("content", "") or "",
                    source=self.name,
                    summary=r.get("summary", "") or "",
                ))
            return items
        if not self.NEWSNOW_ID:
            return []
        return self._newsnow_fetch_items(self.NEWSNOW_ID, limit)

    def _db_short_circuit(self, limit: int) -> Optional[List["DataItem"]]:
        """通用 DB 短路：当天该源已有数据时返回 DataItem 列表，否则返回 None 让子类继续抓。
        非 NewsNow 源（RSS/Trending）在 fetch() 开头调用此方法即可。"""
        from datetime import datetime as _dt
        if self.store is None:
            return None
        today = _dt.now().strftime("%Y-%m-%d")
        if not self.store.has_news_today(self.name, today):
            return None
        rows = self.store.list_news_by_date(today, self.name)
        items: List[DataItem] = []
        for r in rows[:limit]:
            items.append(DataItem(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", "") or "",
                source=self.name,
                summary=r.get("summary", "") or "",
            ))
        return items

    def clear_markdown_url(self, markdown: str) -> str:
        """清理 markdown 链接，只保留文字"""
        pattern = r"\[([^\]]*)\]\((https?://[^\)]+)\)"
        return re.sub(pattern, r"\1", markdown)

    def sleep(self):
        """礼貌延迟"""
        time.sleep(self.rate_delay * random.uniform(0.5, 1.5))

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r}>"