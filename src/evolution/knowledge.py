"""知识记忆系统 v2 — 结构化知识管理

knowledge/ 目录结构:
├── factor_discoveries.md   # 因子发现记录
├── factor_failures.md      # 因子失败记录
├── market_patterns.md      # 市场规律
├── failure_patterns.md     # 失败模式
├── regime_history.md       # 市场状态历史
├── strategy_evolution.md   # 策略演进记录
├── lessons_learned.md      # 永久教训（永不删除）
├── trade_reviews/          # 每日交易复盘
│   ├── 2026-04-03.md
│   └── 2026-04-03.json
├── error_patterns.json     # 错误模式库（结构化）
└── weekly_digests/         # 周度知识摘要
    └── 2026-W14.md
"""

from pathlib import Path
from datetime import datetime
from loguru import logger


class KnowledgeStore:
    """知识记忆管理器 v2"""

    FILES = [
        "factor_discoveries.md",
        "factor_failures.md",
        "market_patterns.md",
        "failure_patterns.md",
        "regime_history.md",
        "strategy_evolution.md",
        "lessons_learned.md",       # NEW: permanent lessons
        "external_learnings.md",    # NEW: learnings from external sources
    ]

    SUBDIRS = ["trade_reviews", "weekly_digests"]

    def __init__(self, knowledge_dir: str = None):
        if knowledge_dir is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            knowledge_dir = str(project_root / "knowledge")
        self.knowledge_dir = Path(knowledge_dir)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_structure()

    def _ensure_structure(self):
        """Ensure all knowledge files and subdirs exist"""
        for fname in self.FILES:
            fpath = self.knowledge_dir / fname
            if not fpath.exists():
                title = fname.replace(".md", "").replace("_", " ").title()
                header = f"# {title}\n\n> 自动维护的知识库\n\n"
                if fname == "lessons_learned.md":
                    header += "> ⚠️ 此文件记录永久教训，请勿删除条目\n\n"
                fpath.write_text(header, encoding="utf-8")
        for subdir in self.SUBDIRS:
            (self.knowledge_dir / subdir).mkdir(parents=True, exist_ok=True)

    def read(self, filename: str) -> str:
        fpath = self.knowledge_dir / filename
        if not fpath.exists():
            return ""
        return fpath.read_text(encoding="utf-8")

    def read_all(self) -> dict[str, str]:
        return {fname: self.read(fname) for fname in self.FILES}

    def append(self, filename: str, content: str):
        if filename not in self.FILES:
            return
        fpath = self.knowledge_dir / filename
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## [{timestamp}]\n{content}\n"
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.info(f"知识追加: {filename}")

    def write(self, filename: str, content: str):
        if filename not in self.FILES:
            return
        fpath = self.knowledge_dir / filename
        fpath.write_text(content, encoding="utf-8")
        logger.info(f"知识写入: {filename}")

    def record_lesson(self, lesson: str, context: str = ""):
        """Record a permanent lesson to lessons_learned.md"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n### [{timestamp}] {lesson}\n"
        if context:
            entry += f"> Context: {context}\n"
        self.append("lessons_learned.md", entry)

    def record_external_learning(self, source: str, finding: str, action: str = ""):
        """Record learning from external source (GitHub, paper, etc.)"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n### [{timestamp}] {source}\n- **发现**: {finding}\n"
        if action:
            entry += f"- **行动**: {action}\n"
        self.append("external_learnings.md", entry)

    def search(self, keyword: str) -> list[dict]:
        results = []
        keyword_lower = keyword.lower()
        for fname in self.FILES:
            content = self.read(fname)
            if keyword_lower in content.lower():
                lines = content.split("\n")
                matches = []
                for i, line in enumerate(lines):
                    if keyword_lower in line.lower():
                        start = max(0, i - 1)
                        end = min(len(lines), i + 3)
                        matches.append("\n".join(lines[start:end]))
                results.append({"file": fname, "matches": matches[:3]})
        return results

    def get_summary(self, max_chars: int = 3000) -> str:
        """Get summary of all knowledge for LLM context"""
        parts = []
        total = 0
        # Prioritize lessons and external learnings
        priority = ["lessons_learned.md", "failure_patterns.md", "external_learnings.md"]
        remaining = [f for f in self.FILES if f not in priority]

        for fname in priority + remaining:
            content = self.read(fname).strip()
            if content and len(content) > 50:
                budget = max_chars // min(len(self.FILES), 6)
                if len(content) > budget:
                    content = content[:budget] + "\n...(截断)"
                parts.append(f"### {fname}\n{content}")
                total += len(content)
            if total >= max_chars:
                break
        return "\n\n".join(parts) if parts else "（知识库暂无内容）"

    def get_stats(self) -> dict:
        """Get knowledge base statistics"""
        stats = {"files": {}, "trade_reviews": 0, "error_patterns": 0}
        for fname in self.FILES:
            content = self.read(fname)
            lines = [l for l in content.split("\n") if l.strip() and not l.startswith("#")]
            stats["files"][fname] = len(lines)

        review_dir = self.knowledge_dir / "trade_reviews"
        if review_dir.exists():
            stats["trade_reviews"] = len(list(review_dir.glob("*.md")))

        ep_file = self.knowledge_dir / "error_patterns.json"
        if ep_file.exists():
            import json
            patterns = json.loads(ep_file.read_text())
            stats["error_patterns"] = len(patterns)

        return stats
