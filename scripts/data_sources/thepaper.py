"""澎湃新闻 - The Paper RSS"""
from typing import List
import feedparser
from .base import BaseDataSource, DataItem
from .registry import register_source


@register_source
class ThepaperSource(BaseDataSource):
    """澎湃新闻 RSS"""

    def fetch(self, limit: int = 30) -> List[DataItem]:
        # 1. 当天已抓 → 走 DB
        cached = self._db_short_circuit(limit)
        if cached is not None:
            return cached
        url = "https://www.thepaper.cn/rss_thePaper.jsp"
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"[thepaper] RSS 解析失败: {e}")
            return []
        items: List[DataItem] = []
        for entry in feed.entries[:limit]:
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
        self.sleep()
        return items