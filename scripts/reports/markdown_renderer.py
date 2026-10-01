"""
Markdown 报告渲染（news.md / needs.md）
- 用 Jinja2 渲染 templates/news.md.j2 和 needs.md.j2
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
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


def render_news_md(date_str: str,
                   news: List[Dict],
                   store: Optional[DataStore] = None) -> Path:
    """渲染 news.md，按 source 分组卡片"""
    env = _env()
    template = env.get_template("news.md.j2")
    # 按 source 分组
    grouped: Dict[str, List[Dict]] = {}
    for n in news:
        grouped.setdefault(n.get("source") or "unknown", []).append(n)
    # 每组内按 score 倒序
    for k in grouped:
        grouped[k].sort(key=lambda x: x.get("score") or 0, reverse=True)
    content = template.render(
        date=date_str,
        total=len(news),
        grouped=grouped,
        sources_count=len(grouped),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    out_dir = REPORTS_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "news.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def render_needs_md(date_str: str,
                   demands: List[Dict],
                   store: Optional[DataStore] = None) -> Path:
    """渲染 needs.md，按可行性分组看板"""
    env = _env()
    template = env.get_template("needs.md.j2")
    # 按 feasibility 分组（保留 high → mid → low 顺序）
    groups = {"高": [], "中": [], "低": []}
    for d in demands:
        f = d.get("feasibility") or "中"
        groups.setdefault(f, []).append(d)
    # 每组内按 priority_score 倒序
    for k in groups:
        groups[k].sort(key=lambda x: x.get("priority_score") or 0, reverse=True)
    content = template.render(
        date=date_str,
        total=len(demands),
        groups=groups,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    out_dir = REPORTS_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "needs.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def fetch_and_render(date_str: Optional[str] = None,
                    hours: int = 24,
                    store: Optional[DataStore] = None) -> Dict[str, Path]:
    """一站式：从 DB 读数据 → 渲染 Markdown → 写文件"""
    store = store or get_datastore()
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    news = store.list_news(hours=hours, limit=500, order_by="score DESC")
    demands = store.list_demands(hours=hours, limit=200, order_by="priority_score DESC")

    news_path = render_news_md(date_str, news, store)
    needs_path = render_needs_md(date_str, demands, store)
    return {"news": news_path, "needs": needs_path}