"""抖音热榜 - 统一 NewsNow API（每日缓存命中后直接读 DB）"""
from typing import List
from .base import BaseDataSource, DataItem
from .registry import register_source


@register_source
class DouyinSource(BaseDataSource):
    """抖音热榜（NewsNow id: douyin）"""
    NEWSNOW_ID = "douyin"

    def fetch(self, limit: int = 20) -> List[DataItem]:
        return self._cached_or_newsnow(limit)
