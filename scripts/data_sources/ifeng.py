"""凤凰网 - 综合新闻 RSS"""
from typing import List
import feedparser
from .base import BaseDataSource, DataItem
from .registry import register_source


@register_source
class IfengSource(BaseDataSource):
    """凤凰网 RSS（综合新闻）"""

    def fetch(self, limit: int = 30) -> List[DataItem]:
        # 1. 当天已抓 → 走 DB
        cached = self._db_short_circuit(limit)
        if cached is not None:
            return cached
        # 凤凰网 RSS 列表（部分订阅源）
        urls = [
            "https://news.ifeng.com/rss/index.xml",
            "https://news.ifeng.com/rss/top.xml",
        ]
        items: List[DataItem] = []
        for url in urls:
            try:
                feed = feedparser.parse(url)
            except Exception as e:
                print(f"[ifeng] {url} 解析失败: {e}")
                continue
            for entry in feed.entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                items.append(DataItem(
                    title=title,
                    url=link,
                    content="",
                    source=self.SOURCE_NAME,
                    summary=entry.get("summary", "")[:300],
                ))
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
        self.sleep()
        return items[:limit]