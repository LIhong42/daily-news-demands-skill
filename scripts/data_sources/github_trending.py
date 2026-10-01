"""GitHub Trending - 直接抓 trending 页面"""
from typing import List
from bs4 import BeautifulSoup
from .base import BaseDataSource, DataItem
from .registry import register_source


@register_source
class GithubTrendingSource(BaseDataSource):
    """GitHub Trending (今日榜)"""

    def fetch(self, limit: int = 15) -> List[DataItem]:
        # 1. 当天已抓 → 走 DB
        cached = self._db_short_circuit(limit)
        if cached is not None:
            return cached
        url = "https://github.com/trending"
        resp = self._http_get(url)
        if not resp:
            return []
        try:
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            soup = BeautifulSoup(resp.text, "html.parser")
        items: List[DataItem] = []
        # GitHub trending 用 <article> 包裹每个仓库
        for article in soup.select("article.Box-row")[:limit]:
            a_tag = article.select_one("h2 a")
            if not a_tag:
                continue
            href = a_tag.get("href", "").strip()
            if not href:
                continue
            full_url = f"https://github.com{href}" if href.startswith("/") else href
            # title 文本（带空格分隔 repo owner/name）
            title = a_tag.get_text(strip=True).replace(" / ", "/")
            desc_tag = article.select_one("p.col-9")
            desc = desc_tag.get_text(strip=True) if desc_tag else ""
            items.append(DataItem(
                title=title,
                url=full_url,
                content=desc,
                source=self.SOURCE_NAME,
                summary=desc[:300],
            ))
        self.sleep()
        return items