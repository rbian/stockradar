"""GitHub项目扫描器 v2 — 真正搜索GitHub

搜索策略：
1. GitHub Search API (按star排序，关键词过滤)
2. GitHub Trending (每周热门)
3. 已知项目列表定期检查
4. awesome-list扫描

评估维度：Stars、最近活跃度、与StockRadar的相关性
"""

import json
from pathlib import Path
from datetime import datetime
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Finance-related keywords for relevance scoring
FINANCE_KEYWORDS = [
    "stock", "trading", "quantitative", "alpha", "factor", "portfolio",
    "backtest", "sharpe", "strategy", "signal", "sentiment", "financial",
    "market", "option", "futures", "candle", "ohlcv", "ticker", "A股",
    "量化", "选股", "回测", "策略", "因子",
]

# Known quality projects (always check)
KNOWN_PROJECTS = {
    "RKiding/Awesome-finance-skills": {"relevance": "high", "category": "skills"},
    "AI4Finance-Foundation/FinRL": {"relevance": "medium", "category": "rl"},
    "wilsonfreitas/awesome-quant": {"relevance": "high", "category": "awesome-list"},
    "thumlut/awesome-quant": {"relevance": "high", "category": "awesome-list"},
}


def search_github(query: str, min_stars: int = 100) -> list[dict]:
    """Search GitHub via web_fetch, parse results

    Args:
        query: search keywords
        min_stars: minimum star count filter

    Returns:
        list of {repo, description, url, relevance_score}
    """
    results = []
    try:
        url = f"https://github.com/search?q={query}+stars%3A%3E{min_stars}&s=stars&type=Repositories&o=desc"
        from web_fetch import web_fetch as _fetch
        # Can't use tool directly, use requests
        import requests
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            for item in items[:10]:
                repo = item.get("full_name", "")
                desc = item.get("description", "") or ""
                stars = item.get("stargazers_count", 0)
                lang = item.get("language", "")
                updated = item.get("updated_at", "")

                rel_score = _score_relevance(desc, lang)
                if rel_score > 0:
                    results.append({
                        "repo": repo,
                        "description": desc[:200],
                        "stars": stars,
                        "language": lang,
                        "updated": updated[:10],
                        "relevance_score": rel_score,
                        "source": f"search:{query}",
                    })
    except Exception as e:
        # Fallback: scrape HTML
        try:
            from web_fetch import web_fetch
            page = web_fetch(url, maxChars=5000)
            # Parse repo names from search results
            import re
            repos = re.findall(r'href="/([^/]+/[^/]+)"', page)
            for repo in repos[:10]:
                if repo not in [r["repo"] for r in results]:
                    results.append({
                        "repo": repo,
                        "description": "",
                        "stars": 0,
                        "relevance_score": 3,
                        "source": f"search:{query}",
                    })
        except Exception as e2:
            logger.warning(f"GitHub search failed: {e2}")

    return results


def scan_trending() -> list[dict]:
    """Scan GitHub Trending page for finance-related repos"""
    results = []
    try:
        import requests
        resp = requests.get(
            "https://github.com/trending/python?since=weekly",
            headers={"Accept": "text/html"},
            timeout=10,
        )
        if resp.status_code == 200:
            import re
            # Extract repo names and descriptions
            repos = re.findall(
                r'<h2 class="h3 lh-condensed">.*?href="/([^"]+)"[^>]*>[\s\S]*?([^<]+)',
                resp.text,
            )
            for path, desc in repos[:20]:
                path = path.strip().lstrip("/")
                desc = desc.strip()
                rel_score = _score_relevance(desc, "Python")
                if rel_score > 2:  # Only include relevant
                    results.append({
                        "repo": path,
                        "description": desc[:200],
                        "stars": 0,
                        "relevance_score": rel_score,
                        "source": "trending",
                    })
    except Exception as e:
        logger.warning(f"Trending scan failed: {e}")

    return results


def _score_relevance(description: str, language: str) -> int:
    """Score relevance to StockRadar (0-10)"""
    if not description:
        return 1
    desc_lower = description.lower()
    score = 0

    # Finance keywords
    finance_hits = sum(1 for k in FINANCE_KEYWORDS if k in desc_lower)
    score += min(finance_hits * 2, 8)

    # Language bonus
    if language in ("Python",):
        score += 1

    # Anti-patterns (unrelated)
    anti = ["game", "music", "video", "chat", "blog", "cms", "django", "flask-app"]
    if any(a in desc_lower for a in anti):
        score = max(0, score - 5)

    return score


def run_full_scan() -> dict:
    """Execute full GitHub scan: awesome-quant + trending + known + search

    Returns:
        {repos: [...], summary: str, actionable: [...]}
    """
    all_repos = {}  # repo_name -> repo_data

    # 1. Scan awesome-quant list (422+ projects)
    logger.info("Scanning awesome-quant list...")
    awesome_repos = _scan_awesome_list()
    for r in awesome_repos:
        all_repos[r["repo"]] = r

    # 2. Scan GitHub trending for finance repos
    logger.info("Scanning GitHub trending...")
    trending = scan_trending()
    for r in trending:
        if r["repo"] not in all_repos:
            all_repos[r["repo"]] = r

    # 3. Search GitHub for specific topics
    for query in ["stock alpha factor python", "A股 量化选股"]:
        results = search_github(query)
        for r in results:
            if r["repo"] not in all_repos:
                all_repos[r["repo"]] = r

    # 4. Check known projects
    for repo, info in KNOWN_PROJECTS.items():
        all_repos.setdefault(repo, {
            "repo": repo,
            "relevance_score": 8 if info["relevance"] == "high" else 5,
            "source": "known",
            "category": info["category"],
        })

    # Sort by relevance
    sorted_repos = sorted(
        all_repos.values(),
        key=lambda x: (x.get("relevance_score", 0), x.get("stars", 0)),
        reverse=True,
    )

    # Identify actionable items (high relevance)
    actionable = [r for r in sorted_repos[:10] if r.get("relevance_score", 0) >= 4]

    # Save
    _save_results(sorted_repos)

    summary = f"扫描完成: {len(sorted_repos)}个项目, {len(actionable)}个可借鉴"
    logger.info(summary)
    return {"repos": sorted_repos[:20], "summary": summary, "actionable": actionable}


def _scan_awesome_list() -> list[dict]:
    """Scan awesome-quant repo list for Python trading projects"""
    results = []
    try:
        import requests, re
        resp = requests.get(
            "https://raw.githubusercontent.com/wilsonfreitas/awesome-quant/master/README.md",
            timeout=15,
        )
        if resp.status_code == 200:
            links = re.findall(r'https://github\.com/([^\)"]+)', resp.text)
            links = [l for l in links if '/' in l
                     and not any(x in l for x in ['wilsonfreitas/awesome', 'badges', 'shields'])]
            unique = list(dict.fromkeys(links))

            # Filter for Python + trading relevant
            relevant_keywords = [
                "trading", "stock", "alpha", "factor", "backtest", "quant",
                "portfolio", "strategy", "signal", "sentiment", "candle",
                "A-share", "china", "选股", "量化",
            ]
            for repo in unique:
                repo_lower = repo.lower()
                hits = sum(1 for k in relevant_keywords if k in repo_lower)
                if hits > 0:
                    results.append({
                        "repo": repo,
                        "relevance_score": min(hits * 3, 9),
                        "source": "awesome-quant",
                        "description": "",
                        "stars": 0,
                    })
    except Exception as e:
        logger.warning(f"awesome-quant scan failed: {e}")

    logger.info(f"awesome-quant: {len(results)} relevant repos from list")
    return results


def _save_results(repos: list[dict]):
    """Save scan results to knowledge"""
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
        "repos_found": len(repos),
        "repos": repos[:20],
    })
    history = history[-12:]
    filepath.write_text(json.dumps(history, ensure_ascii=False, indent=2))


def format_scan_report(results: dict = None) -> str:
    """Format scan results into readable report"""
    if results is None:
        filepath = PROJECT_ROOT / "knowledge" / "github_scan_history.json"
        if not filepath.exists():
            return "暂无GitHub扫描记录"
        history = json.loads(filepath.read_text())
        if not history:
            return "暂无扫描记录"
        last = history[-1]
        repos = last.get("repos", [])
    else:
        repos = results.get("repos", [])

    if not repos:
        return "暂无发现"

    lines = [f"🔍 **GitHub扫描** (发现{len(repos)}个项目)\n"]

    for r in repos[:15]:
        score = r.get("relevance_score", 0)
        emoji = "🟢" if score >= 6 else "🟡" if score >= 3 else "⚪"
        stars = r.get("stars", 0)
        stars_str = f" ⭐{stars}" if stars else ""
        desc = r.get("description", "")[:60]
        lines.append(f"{emoji} **{r['repo']}**{stars_str}")
        if desc:
            lines.append(f"   {desc}")

    return "\n".join(lines)
