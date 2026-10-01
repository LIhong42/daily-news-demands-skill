"""
HTML 报告渲染（自包含单文件 report.html）
- 含 Mermaid CDN（可视化图表）
- 含原生 JS（搜索 / 过滤 / Tab 切换）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scripts.storage.data_store import DataStore, get_datastore

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=("html",)),
        trim_blocks=True,
    )


def render_html_report(date_str: str,
                       news: List[Dict],
                       demands: List[Dict],
                       stats: Optional[Dict] = None,
                       store: Optional[DataStore] = None) -> Path:
    """渲染单文件 HTML 报告"""
    env = _env()
    template = env.get_template("report.html.j2")

    # 序列化给前端
    news_json = json.dumps(news, ensure_ascii=False, default=str)
    demands_json = json.dumps(demands, ensure_ascii=False, default=str)

    # 来源分布 + 可行性分布 + 标签云
    source_dist: Dict[str, int] = {}
    for n in news:
        src = n.get("source") or "unknown"
        source_dist[src] = source_dist.get(src, 0) + 1

    feas_dist = {"高": 0, "中": 0, "低": 0}
    for d in demands:
        f = d.get("feasibility") or "中"
        feas_dist[f] = feas_dist.get(f, 0) + 1

    tag_freq: Dict[str, int] = {}
    for d in demands:
        tags_raw = d.get("tags") or "[]"
        if isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except Exception:
                tags = []
        else:
            tags = tags_raw or []
        for t in tags:
            tag_freq[t] = tag_freq.get(t, 0) + 1
    top_tags = sorted(tag_freq.items(), key=lambda x: -x[1])[:30]

    content = template.render(
        date=date_str,
        total_news=len(news),
        total_demands=len(demands),
        news_json=news_json,
        demands_json=demands_json,
        source_dist=source_dist,
        feas_dist=feas_dist,
        top_tags=top_tags,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        stats=stats or {},
    )
    out_dir = REPORTS_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.html"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def fetch_and_render(date_str: Optional[str] = None,
                     hours: int = 24,
                     store: Optional[DataStore] = None) -> Path:
    """一站式：从 DB → 渲染 HTML → 写文件"""
    store = store or get_datastore()
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    news = store.list_news(hours=hours, limit=500, order_by="score DESC")
    demands = store.list_demands(hours=hours, limit=200, order_by="priority_score DESC")
    stats = store.get_stats()
    return render_html_report(date_str, news, demands, stats=stats, store=store)