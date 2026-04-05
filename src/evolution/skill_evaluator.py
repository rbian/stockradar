"""Skill评估器 — 评估外部skill是否值得集成

流程: 发现skill → 阅读描述 → 评估兼容性 → 推荐/跳过
"""

import os
from pathlib import Path
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# Skills we already have integrated
INTEGRATED = {
    "tushare": "Tushare data adapter (northbound, sectors)",
    "stock-monitor": "7-rule alert system",
    "stock-daily-analysis": "Technical signal scoring",
}

# Skills evaluated and skipped (with reasons)
SKIPPED = {
    "stock-analyzer": "功能与已有因子引擎重叠",
    "openclaw-stock-skill": "数据源与BaoStock/Sina重复",
}


def evaluate_skill(skill_name: str, skill_dir: str = None) -> dict:
    """Evaluate a skill for integration potential

    Args:
        skill_name: skill identifier
        skill_dir: path to skill directory (if installed locally)

    Returns:
        {name, status: install|adapt|skip, reason, complexity, value}
    """
    if skill_name in INTEGRATED:
        return {"name": skill_name, "status": "installed", "reason": INTEGRATED[skill_name]}

    if skill_name in SKIPPED:
        return {"name": skill_name, "status": "skipped", "reason": SKIPPED[skill_name]}

    # Try to read SKILL.md
    skill_md = None
    search_paths = [
        Path(skill_dir) / "SKILL.md" if skill_dir else None,
        Path.home() / ".agents" / "skills" / skill_name / "SKILL.md",
        PROJECT_ROOT / "skills" / skill_name / "SKILL.md",
    ]

    for p in search_paths:
        if p and p.exists():
            skill_md = p.read_text(encoding="utf-8")[:3000]
            break

    if skill_md is None:
        return {"name": skill_name, "status": "unknown", "reason": "SKILL.md not found"}

    # Evaluate compatibility
    return _evaluate_from_md(skill_name, skill_md)


def _evaluate_from_md(name: str, md_content: str) -> dict:
    """Evaluate skill based on SKILL.md content"""
    md_lower = md_content.lower()

    # Check for useful capabilities we lack
    capabilities = []
    value_score = 0

    if any(k in md_lower for k in ["sentiment", "情绪", "finbert", "nlp"]):
        capabilities.append("情绪分析")
        value_score += 3

    if any(k in md_lower for k in ["predict", "预测", "forecast", "lstm", "transformer"]):
        capabilities.append("价格预测")
        value_score += 4

    if any(k in md_lower for k in ["signal", "信号", "alert", "预警", "monitor"]):
        capabilities.append("信号/预警")
        value_score += 2  # We already have this

    if any(k in md_lower for k in ["backtest", "回测", "sharpe"]):
        capabilities.append("回测")
        value_score += 1  # We have basic backtest

    if any(k in md_lower for k in ["news", "新闻", "rss"]):
        capabilities.append("新闻")
        value_score += 2  # We have news sentiment

    if any(k in md_lower for k in ["risk", "风险", "drawdown", "stop"]):
        capabilities.append("风控")
        value_score += 2

    # Check complexity
    complexity = "low"
    if any(k in md_lower for k in ["api key", "token", "database", "model download"]):
        complexity = "medium"
    if any(k in md_lower for k in ["docker", "gpu", "cuda", "train", "fine-tune"]):
        complexity = "high"

    # Decision
    if value_score >= 4:
        status = "recommend"
        reason = f"有价值的新能力: {', '.join(capabilities)}"
    elif value_score >= 2:
        status = "consider"
        reason = f"可能有用: {', '.join(capabilities)}"
    else:
        status = "skip"
        reason = "与现有功能重叠或价值有限"

    return {
        "name": name,
        "status": status,
        "value_score": value_score,
        "complexity": complexity,
        "capabilities": capabilities,
        "reason": reason,
    }


def batch_evaluate_skills(skill_names: list[str]) -> list[dict]:
    """Evaluate multiple skills"""
    results = []
    for name in skill_names:
        result = evaluate_skill(name)
        results.append(result)
    return sorted(results, key=lambda x: x.get("value_score", 0), reverse=True)


def format_skill_report(results: list[dict] = None) -> str:
    """Format skill evaluation results"""
    if results is None:
        # Auto-discover installed skills
        skill_dirs = []
        for base in [Path.home() / ".agents" / "skills", Path.home() / ".openclaw" / "skills"]:
            if base.exists():
                skill_dirs.extend([d.name for d in base.iterdir() if d.is_dir() and (d / "SKILL.md").exists()])

        results = []
        seen = set()
        for name in skill_dirs:
            if name not in seen:
                seen.add(name)
                results.append(evaluate_skill(name))

        # Add alphaear skills from Awesome-finance-skills
        for s in ["alphaear-sentiment", "alphaear-predictor", "alphaear-signal-tracker",
                   "alphaear-news", "alphaear-reporter"]:
            if s not in seen:
                results.append(evaluate_skill(s))

    if not results:
        return "暂无skill评估记录"

    status_emoji = {"recommend": "🟢", "consider": "🟡", "skip": "🔴",
                    "installed": "✅", "skipped": "⏭️", "unknown": "❓"}

    lines = ["🎯 **Skill评估报告**\n"]
    for r in sorted(results, key=lambda x: x.get("value_score", 0), reverse=True):
        emoji = status_emoji.get(r["status"], "❓")
        score = r.get("value_score", 0)
        cplx = r.get("complexity", "?")
        lines.append(f"{emoji} **{r['name']}** [{r['status']}] 价值:{score} 复杂度:{cplx}")
        lines.append(f"   {r.get('reason', '')}")

    return "\n".join(lines)
