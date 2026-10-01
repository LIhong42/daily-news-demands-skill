"""
数据源注册中心（移植自 TrendSearch-main 的 data_sources/__init__.py）
- 把每个数据源类注册到名字上
- get_all_data_sources() / get_source(name) 供 fetch 层调用
"""
from typing import Dict, Type
from .base import BaseDataSource

# 各数据源类（延迟导入，避免循环依赖）
_SOURCES: Dict[str, Type[BaseDataSource]] = {}


def register_source(cls: Type[BaseDataSource]) -> Type[BaseDataSource]:
    """类装饰器：注册数据源

    名字优先级：cls.SOURCE_NAME > 模块文件名（保留下划线）> 类名（去 Source 后缀）
    """
    import sys
    name = getattr(cls, "SOURCE_NAME", None)
    if not name:
        mod = sys.modules.get(cls.__module__, None)
        if mod and getattr(mod, "__file__", None):
            from pathlib import Path
            name = Path(mod.__file__).stem  # 例: bilibili_hot
    if not name:
        name = cls.__name__.lower().replace("source", "")
    _SOURCES[name] = cls
    cls.SOURCE_NAME = name
    return cls


def get_all_data_sources() -> Dict[str, BaseDataSource]:
    """实例化所有已注册的数据源"""
    from . import (  # noqa: F401 触发模块级 @register_source
        weibo, zhihu, douyin, bilibili_hot, toutiao, tieba,
        github_trending, hackernews, wallstreetcn_hot, cls_hot,
        ifeng, thepaper, baidu,
    )
    # 注入 store，让源类 fetch() 内可以做每日缓存命中
    from scripts.storage.data_store import get_datastore
    store = get_datastore()
    return {name: cls(name=name, store=store) for name, cls in _SOURCES.items()}


def get_source(name: str) -> BaseDataSource:
    """按名获取数据源实例"""
    sources = get_all_data_sources()
    if name not in sources:
        raise ValueError(f"数据源 '{name}' 未注册。可用: {list(sources.keys())}")
    return sources[name]


def list_registered_names() -> list:
    return list(_SOURCES.keys())