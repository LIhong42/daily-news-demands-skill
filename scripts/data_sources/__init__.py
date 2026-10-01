"""
数据源包入口
"""
from .base import BaseDataSource, DataItem
from .registry import register_source, get_all_data_sources, get_source, list_registered_names

# 触发各源模块的 @register_source 注册
from . import weibo  # noqa: F401
from . import zhihu  # noqa: F401
from . import douyin  # noqa: F401
from . import bilibili_hot  # noqa: F401
from . import toutiao  # noqa: F401
from . import tieba  # noqa: F401
from . import github_trending  # noqa: F401
from . import hackernews  # noqa: F401
from . import wallstreetcn_hot  # noqa: F401
from . import cls_hot  # noqa: F401
from . import ifeng  # noqa: F401
from . import thepaper  # noqa: F401
from . import baidu  # noqa: F401

__all__ = [
    "BaseDataSource",
    "DataItem",
    "register_source",
    "get_all_data_sources",
    "get_source",
    "list_registered_names",
]