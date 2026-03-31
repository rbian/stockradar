"""知识记忆系统 - 管理知识库文件的读写

knowledge/ 目录下维护多个markdown文件，记录系统的发现、教训和规律。
LLM分析时可读取知识库，避免重复犯错。
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional

from loguru import logger

from src.infra.config import get_settings


class KnowledgeStore:
    """知识记忆管理器"""

    FILES = [
        "factor_discoveries.md",
        "factor_failures.md",
        "market_patterns.md",
        "failure_patterns.md",
        "regime_history.md",
        "strategy_evolution.md",
    ]

    def __init__(self, knowledge_dir: str = None):
        if knowledge_dir is None:
            settings = get_settings()
            project_root = Path(__file__).resolve().parent.parent.parent
            knowledge_dir = str(project_root / "knowledge")
        self.knowledge_dir = Path(knowledge_dir)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_files()

    def _ensure_files(self):
        """确保所有知识文件存在"""
        for fname in self.FILES:
            fpath = self.knowledge_dir / fname
            if not fpath.exists():
                title = fname.replace(".md", "").replace("_", " ").title()
                fpath.write_text(f"# {title}\n\n> 自动维护的知识库，由系统写入\n\n", encoding="utf-8")

    def read(self, filename: str) -> str:
        """读取某个知识文件的全部内容"""
        fpath = self.knowledge_dir / filename
        if not fpath.exists():
            logger.warning(f"知识文件不存在: {filename}")
            return ""
        return fpath.read_text(encoding="utf-8")

    def read_all(self) -> dict[str, str]:
        """读取所有知识文件"""
        return {fname: self.read(fname) for fname in self.FILES}

    def append(self, filename: str, content: str):
        """向知识文件追加内容"""
        if filename not in self.FILES:
            logger.warning(f"未知知识文件: {filename}")
            return
        fpath = self.knowledge_dir / filename
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"\n## [{timestamp}]\n{content}\n"
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.info(f"知识追加: {filename}")

    def write(self, filename: str, content: str):
        """覆盖写入知识文件"""
        if filename not in self.FILES:
            logger.warning(f"未知知识文件: {filename}")
            return
        fpath = self.knowledge_dir / filename
        fpath.write_text(content, encoding="utf-8")
        logger.info(f"知识写入: {filename}")

    def search(self, keyword: str) -> list[dict]:
        """在所有知识文件中搜索关键词"""
        results = []
        keyword_lower = keyword.lower()
        for fname in self.FILES:
            content = self.read(fname)
            if keyword_lower in content.lower():
                # 找到关键词所在的段落
                lines = content.split("\n")
                matches = []
                for i, line in enumerate(lines):
                    if keyword_lower in line.lower():
                        start = max(0, i - 1)
                        end = min(len(lines), i + 3)
                        matches.append("\n".join(lines[start:end]))
                results.append({
                    "file": fname,
                    "matches": matches[:3],  # 最多返回3个匹配段
                })
        return results

    def get_summary(self, max_chars: int = 2000) -> str:
        """获取所有知识文件的摘要（用于LLM上下文）"""
        parts = []
        total = 0
        for fname in self.FILES:
            content = self.read(fname).strip()
            if content and len(content) > 50:  # 跳过几乎空的文件
                # 只取前N个字符
                budget = max_chars // len(self.FILES)
                if len(content) > budget:
                    content = content[:budget] + "\n...(截断)"
                parts.append(f"### {fname}\n{content}")
                total += len(content)
            if total >= max_chars:
                break
        return "\n\n".join(parts) if parts else "（知识库暂无内容）"
