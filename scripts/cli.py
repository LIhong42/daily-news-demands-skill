"""
Daily News Skill - CLI 门面
极简设计：6 个子命令
- init    初始化数据库
- fetch   抓取新闻
- save-needs / save-news-report / save-demand-report  接收 Claude 产出并入库
- report  从数据生成 Markdown / HTML 报告
- query   查询数据
- export  导出 CSV/JSON
- sources 管理数据源
- clean   清理过期数据
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List

# 让 `python scripts/cli.py` 与 `python -m scripts.cli` 都能跑
_PKG_PARENT = Path(__file__).resolve().parent.parent
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

import click
from dotenv import load_dotenv

# 加载 .env（若无 .env 则回退 .env.example，方便开箱即用）
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv(_env_path.parent / ".env.example")

from scripts.storage.data_store import (
    DataStore, get_datastore, generate_uuid,
)
from scripts.data_sources import get_all_data_sources, list_registered_names
from scripts.fetch import load_sources_config, filter_sources, fetch_all
from scripts.reports.markdown_renderer import fetch_and_render as render_md


# ============================================================
# 通用辅助
# ============================================================

def _get_store(ctx) -> DataStore:
    """从 click context 取 store"""
    return ctx.obj["store"]


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _cutoff_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _print_table(rows: List[dict], columns: List[str], max_width: int = 60):
    """简单表格打印"""
    if not rows:
        click.echo("（无数据）")
        return
    # 表头
    header = " | ".join(columns)
    click.echo(header)
    click.echo("-" * len(header))
    for r in rows:
        cells = []
        for c in columns:
            v = str(r.get(c, "") or "")
            if len(v) > max_width:
                v = v[:max_width - 3] + "..."
            cells.append(v)
        click.echo(" | ".join(cells))


# ============================================================
# CLI 入口
# ============================================================

@click.group()
@click.option("--db", default=None, help="数据库路径（默认 data/daily_news.db）")
@click.pass_context
def main(ctx, db):
    """Daily News Skill - 多源热点新闻 + 需求挖掘"""
    ctx.ensure_object(dict)
    ctx.obj["store"] = get_datastore(db)
    ctx.obj["db_path"] = db


# ----------- init -----------

@main.command()
@click.option("--with-sources/--no-sources", default=True, help="是否灌入默认 sources.json")
@click.pass_context
def init(ctx, with_sources):
    """初始化数据库（建表 + 可选灌入 sources）"""
    store: DataStore = _get_store(ctx)
    click.echo(f"✓ 数据库已就绪: {store.db_path}")
    if with_sources:
        cfg = load_sources_config()
        n = len(cfg.get("sources", []))
        click.echo(f"✓ 配置文件中已声明 {n} 个数据源（首次 fetch 时自动启用）")


# ----------- fetch -----------

@main.command()
@click.option("--source", default=None, help="只抓取指定源名")
@click.option("--category", default=None, help="按类别过滤")
@click.option("--limit", default=None, type=int, help="每源抓取上限")
@click.option("--hours", default=24, type=int, help="保留窗口（小时）")
@click.pass_context
def fetch(ctx, source, category, limit, hours):
    """抓取所有启用的源"""
    click.echo(f"⏳ 开始抓取...")
    result = fetch_all(
        name=source, category=category,
        limit_per_source=limit, hours=hours,
        store=_get_store(ctx),
    )
    click.echo(f"\n📊 抓取汇总:")
    click.echo(f"  - 源数: {len(result.get('sources', []))}")
    click.echo(f"  - 抓取条数: {result.get('fetched', 0)}")
    click.echo(f"  - 入库条数: {result.get('inserted', 0)}")
    click.echo(f"  - 耗时: {result.get('elapsed_seconds', 0)}s")
    # 状态
    for s in result.get("sources", []):
        st = s.get("status", "")
        if st == "ok":
            icon = "✓"
        elif st == "ok-cache":
            icon = "📦"
        elif st == "missing":
            icon = "⚠️"
        else:
            icon = "✗"
        click.echo(f"  {icon} {s.get('name')}: {s.get('fetched', 0)} 条 ({st})")


# ----------- save-needs -----------

@main.command("save-needs")
@click.option("--json", "json_path", default=None, help="JSON 文件路径（- 表示 stdin）")
@click.option("--date", default=None, help="日期（YYYY-MM-DD），仅做记录")
@click.pass_context
def save_needs(ctx, json_path, date):
    """
    接收 Claude 在对话中挖掘的需求 JSON 并入库。
    支持格式：JSON 数组，或 {"needs": [...]} 对象。
    """
    raw = _read_input(json_path)
    if not raw or not raw.strip():
        click.echo("❌ 空输入")
        sys.exit(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        click.echo(f"❌ JSON 解析失败: {e}")
        sys.exit(1)
    # 兼容 {needs: [...]} 包装
    if isinstance(data, dict) and "needs" in data:
        data = data["needs"]
    if not isinstance(data, list):
        click.echo("❌ 必须是 JSON 数组或 {'needs': [...]} 对象")
        sys.exit(1)
    # 简单字段校验
    valid = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            click.echo(f"  ⚠️ 第 {i+1} 条不是对象，跳过")
            continue
        if not item.get("title"):
            click.echo(f"  ⚠️ 第 {i+1} 条缺 title，跳过")
            continue
        # 兜底字段
        item.setdefault("demand_scenario", "")
        item.setdefault("user_profile", "")
        item.setdefault("description", "")
        item.setdefault("value", "")
        item.setdefault("proposed_solution", "")
        item.setdefault("feasibility", "中")
        item.setdefault("priority_score", 0)
        item.setdefault("tags", [])
        item.setdefault("derived_from_news_uuids", [])
        item.setdefault("evidence", {})
        item["uuid"] = generate_uuid()
        valid.append(item)
    store: DataStore = _get_store(ctx)
    n = store.batch_add_demands(valid)
    click.echo(f"✓ 已写入 {n} 条需求（输入 {len(valid)} 条有效）")
    # 写每日运行统计
    if date:
        store.finish_run(date, fetched_count=store.count_news(hours=24),
                        mined_count=n, notes=f"save-needs 写入 {n} 条")


def _read_input(json_path: Optional[str]) -> str:
    """从文件或 stdin 读输入"""
    if json_path and json_path != "-":
        return Path(json_path).read_text(encoding="utf-8")
    if json_path == "-":
        return sys.stdin.read()
    # 既无 --json 也不指定 → 等待管道输入或参数
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


# ----------- save-news-report / save-demand-report -----------

@main.command("save-news-report")
@click.option("--markdown", "md_path", default=None, help="Markdown 文件路径（- 表示 stdin）")
@click.option("--date", default=None, help="日期（YYYY-MM-DD）")
@click.pass_context
def save_news_report(ctx, md_path, date):
    """保存 Claude 撰写的新闻报告到 DB（也会写到 reports/<date>/news.md）"""
    md = _read_input(md_path)
    if not md.strip():
        click.echo("❌ 空 Markdown")
        sys.exit(1)
    store: DataStore = _get_store(ctx)
    uuid_val = store.add_news_report(md, date)
    if date:
        out = Path("reports") / date / "news.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
    click.echo(f"✓ 新闻报告已保存 (uuid={uuid_val[:8]}...)")


@main.command("save-demand-report")
@click.option("--markdown", "md_path", default=None, help="Markdown 文件路径（- 表示 stdin）")
@click.option("--date", default=None, help="日期（YYYY-MM-DD）")
@click.pass_context
def save_demand_report(ctx, md_path, date):
    """保存 Claude 撰写的需求报告到 DB（也会写到 reports/<date>/needs.md）"""
    md = _read_input(md_path)
    if not md.strip():
        click.echo("❌ 空 Markdown")
        sys.exit(1)
    store: DataStore = _get_store(ctx)
    uuid_val = store.add_demands_report(md, date)
    if date:
        out = Path("reports") / date / "needs.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
    click.echo(f"✓ 需求报告已保存 (uuid={uuid_val[:8]}...)")


# ----------- report -----------

@main.command()
@click.option("--date", default=None, help="日期（YYYY-MM-DD），默认今天")
@click.option("--format", "fmt", default="all", type=click.Choice(["md", "html", "all"]))
@click.option("--hours", default=24, type=int, help="数据窗口（小时）")
@click.pass_context
def report(ctx, date, fmt, hours):
    """从 DB 渲染报告（Markdown / HTML）"""
    store: DataStore = _get_store(ctx)
    date = date or _today()
    if fmt in ("md", "all"):
        paths = render_md(date_str=date, hours=hours, store=store)
        click.echo(f"✓ Markdown: {paths['news']}")
        click.echo(f"✓ Markdown: {paths['needs']}")
    if fmt in ("html", "all"):
        path = render_md_html(date_str=date, hours=hours, store=store)
        click.echo(f"✓ HTML: {path}")


def render_md_html(date_str, hours, store):
    from scripts.reports.html_renderer import fetch_and_render
    return fetch_and_render(date_str=date_str, hours=hours, store=store)


# ----------- query -----------

@main.group()
def query():
    """查询数据"""
    pass


@query.command("news")
@click.option("--source", default=None,
              help="source 名（多个用英文逗号分隔）")
@click.option("--category", multiple=True,
              help="按 sources.json 的 category 过滤（可多次传，如 --category tech --category finance）")
@click.option("--hours", default=24, type=int)
@click.option("--limit", default=50, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def q_news(ctx, source, category, hours, limit, as_json):
    """查询新闻列表"""
    store: DataStore = _get_store(ctx)
    # category → source 映射（基于 sources.json）
    sources_by_category = None
    if category:
        cfg = load_sources_config()
        wanted = set(category)
        sources_by_category = [
            s["name"] for s in cfg.get("sources", [])
            if s.get("category") in wanted and s.get("name")
        ]
        if not sources_by_category:
            click.echo(f"⚠️  category={category} 在 sources.json 中无匹配源")
    rows = store.list_news(
        source=source, hours=hours, limit=limit,
        order_by="score DESC",
        sources_by_category=sources_by_category,
    )
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return
    # 表格输出（截断 URL）
    display = []
    for r in rows:
        display.append({
            "id": r.get("id"),
            "title": r.get("title", ""),
            "source": r.get("source", ""),
            "score": r.get("score", 0),
            "url": r.get("url", "")[:50] + "..." if r.get("url", "") and len(r.get("url", "")) > 50 else r.get("url", ""),
        })
    _print_table(display, ["id", "title", "source", "score", "url"], max_width=50)
    click.echo(f"\n共 {len(rows)} 条")


@query.command("demands")
@click.option("--feasibility", default=None, type=click.Choice(["高", "中", "低"]))
@click.option("--min-score", default=None, type=float)
@click.option("--hours", default=24 * 7, type=int, help="默认 7 天")
@click.option("--limit", default=50, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def q_demands(ctx, feasibility, min_score, hours, limit, as_json):
    """查询需求列表"""
    store: DataStore = _get_store(ctx)
    rows = store.list_demands(
        feasibility=feasibility, min_priority=min_score,
        hours=hours, limit=limit, order_by="priority_score DESC",
    )
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return
    display = []
    for r in rows:
        display.append({
            "id": r.get("id"),
            "title": r.get("title", "")[:50],
            "feasibility": r.get("feasibility", ""),
            "priority": r.get("priority_score", 0),
            "scenario": (r.get("demand_scenario") or "")[:60],
        })
    _print_table(display, ["id", "title", "feasibility", "priority", "scenario"])


@query.command("stats")
@click.pass_context
def q_stats(ctx):
    """数据库统计"""
    store: DataStore = _get_store(ctx)
    stats = store.get_stats()
    click.echo(json.dumps(stats, ensure_ascii=False, indent=2, default=str))


@query.command("random")
@click.option("--kind", default="news", type=click.Choice(["news", "demands"]),
              help="随机返回 news 还是 demands")
@click.option("--source", default=None, help="仅 news：按 source 过滤")
@click.option("--feasibility", default=None, type=click.Choice(["高", "中", "低"]),
              help="仅 demands：按可行性过滤")
@click.option("--min-score", default=None, type=float,
              help="demands：最低 priority_score；news：最低 score")
@click.option("--hours", default=None, type=int, help="时间窗口（小时），留空=全部")
@click.option("--count", default=5, type=int, help="返回条数")
@click.option("--exclude-uuid", multiple=True, help="排除的 uuid（可多次传，避免重复）")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def q_random(ctx, kind, source, feasibility, min_score, hours, count, exclude_uuid, as_json):
    """随机返回 N 条新闻或需求（ORDER BY RANDOM()）"""
    store: DataStore = _get_store(ctx)
    exclude = list(exclude_uuid) if exclude_uuid else None
    if kind == "news":
        rows = store.random_news(
            source=source, hours=hours, limit=count, exclude_uuids=exclude
        )
    else:
        rows = store.random_demands(
            feasibility=feasibility, min_priority=min_score,
            hours=hours, limit=count, exclude_uuids=exclude,
        )
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return
    if not rows:
        click.echo("（无数据）")
        return
    if kind == "news":
        display = [{
            "id": r.get("id"),
            "title": r.get("title", ""),
            "source": r.get("source", ""),
            "score": r.get("score", 0),
        } for r in rows]
        _print_table(display, ["id", "title", "source", "score"], max_width=50)
    else:
        display = [{
            "id": r.get("id"),
            "title": (r.get("title", "") or "")[:40],
            "feasibility": r.get("feasibility", ""),
            "priority": r.get("priority_score", 0),
        } for r in rows]
        _print_table(display, ["id", "title", "feasibility", "priority"], max_width=40)
    click.echo(f"\n随机 {kind} {len(rows)} 条")


# ----------- export -----------

@main.group()
def export():
    """导出数据"""
    pass


@export.command("news")
@click.option("--date", default=None)
@click.option("--hours", default=24, type=int)
@click.option("--format", "fmt", default="csv", type=click.Choice(["csv", "json"]))
@click.option("--output", default=None, help="输出文件路径")
@click.pass_context
def e_news(ctx, date, hours, fmt, output):
    """导出新闻"""
    store: DataStore = _get_store(ctx)
    rows = store.list_news(hours=hours, limit=10000, order_by="score DESC")
    _do_export(rows, fmt, output or f"news_{date or _today()}.{fmt}")


@export.command("demands")
@click.option("--hours", default=24 * 7, type=int)
@click.option("--format", "fmt", default="csv", type=click.Choice(["csv", "json"]))
@click.option("--output", default=None)
@click.pass_context
def e_demands(ctx, hours, fmt, output):
    """导出需求"""
    store: DataStore = _get_store(ctx)
    rows = store.list_demands(hours=hours, limit=10000, order_by="priority_score DESC")
    _do_export(rows, fmt, output or f"demands_{_today()}.{fmt}")


def _do_export(rows, fmt, output):
    if not rows:
        click.echo("无数据可导出")
        return
    if fmt == "json":
        Path(output).write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    else:
        keys = list(rows[0].keys())
        with open(output, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for r in rows:
                row = {k: (str(v) if not isinstance(v, (str, int, float, type(None))) else v) for k, v in r.items()}
                writer.writerow(row)
    click.echo(f"✓ 已导出 {len(rows)} 条到 {output}")


# ----------- sources -----------

@main.group()
def sources():
    """管理数据源"""
    pass


@sources.command("list")
@click.pass_context
def s_list(ctx):
    """列出所有数据源"""
    cfg = load_sources_config()
    sources_cfg = cfg.get("sources", [])
    registered = list_registered_names()
    display = []
    for s in sources_cfg:
        display.append({
            "name": s.get("name", ""),
            "category": s.get("category", ""),
            "type": s.get("type", ""),
            "enabled": "✓" if s.get("enabled", True) else "✗",
            "implemented": "✓" if s.get("name") in registered else "✗",
            "limit": s.get("limit", ""),
        })
    _print_table(display, ["name", "category", "type", "enabled", "implemented", "limit"])


@sources.command("enable")
@click.argument("name")
@click.pass_context
def s_enable(ctx, name):
    """启用数据源"""
    _toggle_source(name, True)


@sources.command("disable")
@click.argument("name")
@click.pass_context
def s_disable(ctx, name):
    """禁用数据源"""
    _toggle_source(name, False)


def _toggle_source(name: str, enabled: bool):
    cfg_path = Path("config") / "sources.json"
    if not cfg_path.exists():
        click.echo("❌ config/sources.json 不存在")
        return
    cfg = load_sources_config(cfg_path)
    found = False
    for s in cfg.get("sources", []):
        if s.get("name") == name:
            s["enabled"] = enabled
            found = True
            break
    if not found:
        click.echo(f"❌ 找不到数据源: {name}")
        return
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    click.echo(f"✓ {name} 已{'启用' if enabled else '禁用'}")


# ----------- clean -----------

@main.command()
@click.option("--days", default=30, type=int, help="保留天数")
@click.option("--yes", is_flag=True, help="跳过确认")
@click.pass_context
def clean(ctx, days, yes):
    """清理 N 天前的旧数据"""
    if not yes:
        click.confirm(f"确认删除 {days} 天前的所有数据？", abort=True)
    store: DataStore = _get_store(ctx)
    deleted = store.clean_old_data(days=days)
    click.echo(f"✓ 已清理: {deleted}")


# ----------- refresh -----------

@main.command()
@click.option("--date", default=None, help="日期 YYYY-MM-DD；默认今天")
@click.option("--limit", default=None, type=int, help="每源抓取上限")
@click.option("--source", default=None, help="只刷新指定源")
@click.option("--category", default=None, help="按类别过滤")
@click.option("--yes", is_flag=True, help="跳过确认直接清空")
@click.pass_context
def refresh(ctx, date, limit, source, category, yes):
    """强制重抓指定日期的源：先清掉当天 DB 数据 → 再走 fetch"""
    store: DataStore = _get_store(ctx)
    target_date = date or _today()
    if not yes:
        click.confirm(
            f"将删除 {target_date} 当天的所有新闻并重新抓取，确认？", abort=True
        )
    deleted = store.delete_news_for_date(target_date)
    click.echo(f"🗑  已清空 {target_date} 的 {deleted} 条新闻 + 1 条 daily_runs")
    # 走 fetch：每个源 fetch() 内部发现当天 DB 空 → 触发 NewsNow
    result = fetch_all(
        name=source, category=category,
        limit_per_source=limit, store=store,
    )
    click.echo(f"\n📊 重抓汇总:")
    click.echo(f"  - 源数: {len(result.get('sources', []))}")
    click.echo(f"  - 抓取条数: {result.get('fetched', 0)}")
    click.echo(f"  - 入库条数: {result.get('inserted', 0)}")
    click.echo(f"  - 耗时: {result.get('elapsed_seconds', 0)}s")
    for s in result.get("sources", []):
        icon = "✓" if s.get("status") == "ok" else "✗"
        click.echo(f"  {icon} {s.get('name')}: {s.get('fetched', 0)} 条 ({s.get('status')})")


if __name__ == "__main__":
    main(obj={})