"""
多源抓取编排
- 读取 config/sources.json
- 按启用列表调用各源 fetch()
- 去重 + 入库（INSERT OR IGNORE）
- 写 daily_runs 日志
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from scripts.data_sources import get_all_data_sources, DataItem
from scripts.storage.data_store import DataStore, get_datastore


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.json"


def load_sources_config(path: Path = CONFIG_PATH) -> Dict:
    if not path.exists():
        return {"sources": [], "fetch_strategy": {}}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def filter_sources(config: Dict,
                   name: Optional[str] = None,
                   category: Optional[str] = None) -> List[Dict]:
    sources = config.get("sources", [])
    out = []
    for s in sources:
        if not s.get("enabled", True):
            continue
        if name and s.get("name") != name:
            continue
        if category and s.get("category") != category:
            continue
        out.append(s)
    return out


def fetch_all(name: Optional[str] = None,
              category: Optional[str] = None,
              hours: int = 24,
              limit_per_source: Optional[int] = None,
              store: Optional[DataStore] = None) -> Dict:
    """
    主入口：抓取所有启用的源，去重后入库。
    返回统计信息 dict。
    """
    config = load_sources_config()
    target = filter_sources(config, name=name, category=category)
    if not target:
        print("⚠️ 没有匹配的数据源（检查 sources.json 与筛选条件）")
        return {"fetched": 0, "inserted": 0, "sources": []}

    store = store or get_datastore()
    today = datetime.now().strftime("%Y-%m-%d")
    run_id = store.start_run(today)

    started = time.time()
    all_items: List[Dict] = []
    source_stats: List[Dict] = []

    for src_cfg in target:
        src_name = src_cfg["name"]
        limit = limit_per_source or src_cfg.get("limit", 20)
        try:
            source = get_all_data_sources()[src_name]
        except KeyError:
            print(f"⚠️ 数据源 '{src_name}' 未实现，跳过")
            source_stats.append({"name": src_name, "fetched": 0, "status": "missing"})
            continue

        # 检测当天缓存命中：has_news_today=True 时跳过远端（fetch() 也会走缓存分支）
        cache_hit = bool(source.store and source.store.has_news_today(src_name, today))

        try:
            items: List[DataItem] = source.fetch(limit=limit)
        except Exception as e:
            print(f"❌ {src_name} 抓取异常: {e}")
            source_stats.append({"name": src_name, "fetched": 0, "status": "error", "error": str(e)})
            continue

        count = 0
        for it in items:
            d = it.to_dict()
            d["source"] = src_name  # 确保 source 与配置一致
            # 缓存命中时不重复入库
            if not cache_hit:
                all_items.append(d)
            count += 1
        status = "ok-cache" if cache_hit else "ok"
        source_stats.append({"name": src_name, "fetched": count, "status": status})
        tag = "📦" if cache_hit else "✓"
        print(f"  {tag} {src_name}: {count} 条{'（缓存）' if cache_hit else ''}")

    # 批量入库
    inserted = store.batch_add_news(all_items)

    elapsed = round(time.time() - started, 2)
    store.finish_run(today, fetched_count=inserted, mined_count=0,
                     notes=f"耗时 {elapsed}s, 源数: {len(source_stats)}")

    return {
        "fetched": sum(s["fetched"] for s in source_stats),
        "inserted": inserted,
        "elapsed_seconds": elapsed,
        "sources": source_stats,
    }