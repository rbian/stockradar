"""进化月报生成器 — 汇总月度进化成果

输出到 knowledge/evolution_reports/YYYY-MM.md
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def generate_monthly_report() -> str:
    """Generate evolution report for current month"""
    knowledge_dir = PROJECT_ROOT / "knowledge"
    now = datetime.now()
    month_key = now.strftime("%Y-%m")

    sections = []

    # 1. Factor Evolution
    sections.append(_section_factors())

    # 2. Trade Reviews
    sections.append(_section_trade_reviews())

    # 3. Error Patterns
    sections.append(_section_error_patterns())

    # 4. External Learnings
    sections.append(_section_external())

    # 5. Knowledge Base Stats
    sections.append(_section_knowledge_stats())

    # 6. Params
    sections.append(_section_params())

    report = f"📈 **StockRadar 进化月报** {month_key}\n\n" + "\n\n".join(s for s in sections if s)

    # Save
    report_dir = knowledge_dir / "evolution_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"{month_key}.md").write_text(report, encoding="utf-8")

    logger.info(f"进化月报已生成: {month_key}")
    return report


def _section_factors() -> str:
    """Factor evolution section"""
    lines = ["## 因子进化"]
    try:
        from src.evolution.factor_tracker import FactorTracker
        tracker = FactorTracker()
        df = tracker.get_status()
        if df.empty:
            lines.append("暂无IC数据")
            return "\n".join(lines)

        active = df[~df["is_suspended"]]
        suspended = df[df["is_suspended"]]
        declining = active[active["weight_multiplier"] < 0.95]

        lines.append(f"- 活跃: {len(active)}个 | 暂停: {len(suspended)}个 | 衰退: {len(declining)}个")

        if not declining.empty:
            lines.append(f"- **衰退因子:**")
            for _, r in declining.iterrows():
                lines.append(f"  · {r['factor']}: IC={r.get('ic_20d_avg', 0):.4f}, 权重×{r['weight_multiplier']:.2f}")

        if not suspended.empty:
            lines.append(f"- **暂停因子:** {', '.join(suspended['factor'].tolist())}")

        # Dynamic factors
        from src.evolution.auto_register import AutoRegister
        registry = AutoRegister()
        df_dyn = registry.get_status()
        if not df_dyn.empty:
            active_dyn = df_dyn[df_dyn["is_active"]]
            lines.append(f"- 动态因子: {len(active_dyn)}个活跃")

    except Exception as e:
        lines.append(f"读取失败: {e}")

    return "\n".join(lines)


def _section_trade_reviews() -> str:
    """Trade review summary"""
    lines = ["## 交易复盘"]
    review_dir = PROJECT_ROOT / "knowledge" / "trade_reviews"

    if not review_dir.exists():
        lines.append("暂无复盘记录")
        return "\n".join(lines)

    reviews = sorted(review_dir.glob("*.md"))
    if not reviews:
        lines.append("暂无复盘记录")
        return "\n".join(lines)

    lines.append(f"- 复盘报告: {len(reviews)}份")

    # Read latest review
    latest = reviews[-1]
    content = latest.read_text()
    # Extract key stats
    for line in content.split("\n"):
        if "总交易" in line or "✅ 正确" in line or "❌" in line:
            lines.append(f"- {line.strip()}")

    return "\n".join(lines)


def _section_error_patterns() -> str:
    """Error patterns section"""
    lines = ["## 错误模式"]
    ep_file = PROJECT_ROOT / "knowledge" / "error_patterns.json"

    if not ep_file.exists():
        lines.append("暂无已识别的模式")
        return "\n".join(lines)

    patterns = json.loads(ep_file.read_text())
    if not patterns:
        lines.append("暂无模式")
        return "\n".join(lines)

    lines.append(f"- 已识别: {len(patterns)}个模式")
    for p in patterns:
        status = "✅" if p["status"] == "verified" else "👁️"
        lines.append(f"  {status} **{p['name']}** — {p['count']}次, 规则: {p.get('fix_rule', '待制定')}")

    return "\n".join(lines)


def _section_external() -> str:
    """External learnings section"""
    lines = ["## 外部学习"]
    ep_file = PROJECT_ROOT / "knowledge" / "github_scan_history.json"

    if ep_file.exists():
        history = json.loads(ep_file.read_text())
        if history:
            latest = history[-1]
            lines.append(f"- 最近扫描: {latest['date']}, 发现{latest['repos_found']}个项目")
            for r in latest.get("results", [])[:3]:
                rel = r.get("relevance", "?")
                lines.append(f"  · {r['repo']} ({rel})")

    # Read external learnings
    el_file = PROJECT_ROOT / "knowledge" / "external_learnings.md"
    if el_file.exists():
        content = el_file.read_text()
        entries = content.count("### [")
        if entries > 0:
            lines.append(f"- 学习记录: {entries}条")

    if len(lines) == 1:
        lines.append("暂无外部学习记录")

    return "\n".join(lines)


def _section_knowledge_stats() -> str:
    """Knowledge base statistics"""
    lines = ["## 知识库"]
    try:
        from src.evolution.knowledge import KnowledgeStore
        ks = KnowledgeStore()
        stats = ks.get_stats()

        total_lines = sum(stats["files"].values())
        lines.append(f"- 文件: {len(stats['files'])}个, 总计{total_lines}行")
        lines.append(f"- 交易复盘: {stats['trade_reviews']}份")
        lines.append(f"- 错误模式: {stats['error_patterns']}个")
    except Exception:
        lines.append("读取失败")

    return "\n".join(lines)


def _section_params() -> str:
    """Best parameters section"""
    lines = ["## 最优参数"]
    pp_file = PROJECT_ROOT / "knowledge" / "params_history.json"

    if not pp_file.exists():
        lines.append("暂未运行参数优化")
        return "\n".join(lines)

    history = json.loads(pp_file.read_text())
    if not history:
        lines.append("暂无结果")
        return "\n".join(lines)

    latest = history[-1]
    results = latest.get("results", [])
    if results:
        best = results[0]
        p = best["params"]
        lines.append(f"- 调仓: {p['rebalance_days']}天 | 持仓: {p['top_n']}只")
        lines.append(f"- 止损: {p['stop_loss']*100:.0f}% | 止盈: {p['stop_profit']*100:.0f}%")
        lines.append(f"- Sharpe: {best['sharpe']} | 收益: {best['total_return']}%")

    return "\n".join(lines)
