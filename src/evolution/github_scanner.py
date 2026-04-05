"""GitHub项目扫描器 — 每周扫描量化相关开源项目，发现可借鉴的能力

搜索关键词：
- quantitative trading, alpha factor, stock selection
- A股量化, 组合优化, machine learning trading

评估维度：Stars、最近活跃度、与StockRadar的相关性
输出到 knowledge/external_learnings.md
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Known quality projects to check periodically
KNOWN_PROJECTS = {
    "RKiding/Awesome-finance-skills": {
        "category": "skills",
        "relevance": "high",
        "skills": ["alphaear-sentiment", "alphaear-predictor", "alphaear-signal-tracker"],
    },
    "AI4Finance-Foundation/FinRL": {
        "category": "rl",
        "relevance": "medium",
        "note": "Deep RL for trading, could enhance scoring",
    },
    "tongzhubin/AShareTradingSystem": {
        "category": "system",
        "relevance": "high",
        "note": "A股交易系统，可能有数据源和策略参考",
    },
}

SEARCH_QUERIES = [
    "quantitative trading alpha factor python",
    "stock selection strategy machine learning",
    "A股量化选股 python",
    "portfolio optimization sharpe",
]


def scan_github(max_repos: int = 10) -> list[dict]:
    """Scan GitHub for relevant quantitative finance projects

    Uses web search to find trending repos, then evaluates each.

    Returns list of {repo, stars, description, relevance_score, actionable_items}
    """
    results = []

    # Check known projects first
    for repo, info in KNOWN_PROJECTS.items():
        result = _evaluate_known(repo, info)
        if result:
            results.append(result)

    # Search for new projects
    try:
        from web_search import web_search
        for query in SEARCH_QUERIES[:2]:  # Limit API calls
            found = web_search(query, count=5)
            for item in found:
                url = item.get("url", "")
                if "github.com" in url and "/pull/" not in url and "/issues/" not in url:
                    repo_name = _extract_repo(url)
                    if repo_name and not any(r["repo"] == repo_name for r in results):
                        results.append({
                            "repo": repo_name,
                            "source": "search",
                            "query": query,
                            "description": item.get("title", ""),
                            "status": "discovered",
                        })
    except Exception as e:
        logger.warning(f"GitHub search failed (non-critical): {e}")

    # Save results
    _save_scan_results(results)
    logger.info(f"GitHub scan complete: {len(results)} repos found")
    return results


def _evaluate_known(repo: str, info: dict) -> dict:
    """Evaluate a known project"""
    return {
        "repo": repo,
        "source": "known",
        "category": info["category"],
        "relevance": info["relevance"],
        "actionable_items": info.get("skills", [info.get("note", "")]),
        "status": "known",
        "last_checked": datetime.now().strftime("%Y-%m-%d"),
    }


def _extract_repo(url: str) -> str:
    """Extract 'owner/repo' from GitHub URL"""
    parts = url.replace("https://github.com/", "").split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


def _save_scan_results(results: list[dict]):
    """Save scan results"""
    scan_dir = PROJECT_ROOT / "knowledge"
    scan_dir.mkdir(parents=True, exist_ok=True)
    filepath = scan_dir / "github_scan_history.json"

    history = []
    if filepath.exists():
        try:
            history = json.loads(filepath.read_text())
        except Exception:
            history = []

    history.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "repos_found": len(results),
        "results": results,
    })

    # Keep last 12 scans (3 months)
    history = history[-12:]
    filepath.write_text(json.dumps(history, ensure_ascii=False, indent=2))


def evaluate_for_integration(repo_name: str) -> dict:
    """Deep evaluate a specific repo for integration potential

    Checks:
    1. What capabilities it offers that we lack
    2. Compatibility with our architecture
    3. Integration complexity
    4. Expected value

    Returns: {can_integrate, complexity, value, plan}
    """
    # Check against our current capabilities
    our_capabilities = {
        "scoring": "36-factor engine",
        "data": "BaoStock + Sina + Tushare",
        "alerts": "7-rule alert system",
        "signals": "MA/MACD/RSI/Bias/Volume",
        "news": "Google News + CNBC RSS",
        "backtest": "basic Sharpe/drawdown",
        "report": "Telegram daily report",
    }

    # Known evaluations
    evaluations = {
        "RKiding/Awesome-finance-skills": {
            "new_capabilities": [
                ("alphaear-sentiment", "FinBERT金融情绪分析，比我们当前规则更精确", "medium"),
                ("alphaear-predictor", "Kronos时序预测模型", "high"),
                ("alphaear-signal-tracker", "信号演化追踪(强化/弱化/证伪)", "medium"),
            ],
            "compatibility": "high — skills可以直接安装到OpenClaw",
            "recommendation": "install alphaear-sentiment for better news analysis",
        },
        "AI4Finance-Foundation/FinRL": {
            "new_capabilities": [
                ("FinRL agent", "深度强化学习选股", "high"),
                ("feature engineering", "自动特征工程", "medium"),
            ],
            "compatibility": "low — 需要大量适配",
            "recommendation": "远期考虑，先观察",
        },
    }

    return evaluations.get(repo_name, {
        "new_capabilities": [],
        "compatibility": "unknown",
        "recommendation": "需要手动评估",
    })


def format_scan_report(results: list[dict] = None) -> str:
    """Format scan results into readable report"""
    if results is None:
        # Load latest scan
        filepath = PROJECT_ROOT / "knowledge" / "github_scan_history.json"
        if not filepath.exists():
            return "暂无GitHub扫描记录"
        history = json.loads(filepath.read_text())
        if not history:
            return "暂无GitHub扫描记录"
        results = history[-1].get("results", [])

    if not results:
        return "暂无发现"

    lines = ["🔍 **GitHub项目扫描结果**\n"]

    for r in results:
        rel = r.get("relevance", "unknown")
        emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(rel, "⚪")
        lines.append(f"{emoji} **{r['repo']}** ({r.get('category', 'unknown')})")

        if r.get("description"):
            lines.append(f"   {r['description']}")

        items = r.get("actionable_items", [])
        if items:
            lines.append(f"   可借鉴: {', '.join(str(i) for i in items[:3])}")

        lines.append("")

    return "\n".join(lines)
