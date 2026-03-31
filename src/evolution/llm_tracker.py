"""LLM预测准确率追踪

记录每次LLM分析结论，后续跟踪实际表现，定期计算准确率。
准确率下降时自动降低LLM因子权重。
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from src.infra.config import PROJECT_ROOT


class LLMTracker:
    """LLM预测追踪器

    用法:
        tracker = LLMTracker(store)
        # 记录预测
        tracker.record_prediction("300750", "earnings", "positive", 0.85, "2026-03-30")
        # 后续更新结果
        tracker.update_outcome("300750", "2026-03-30", 0.03)  # 实际涨了3%
        # 查看准确率
        tracker.get_accuracy_report()
    """

    def __init__(self, store=None):
        self.store = store
        self.knowledge_dir = PROJECT_ROOT / "knowledge"
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

    def record_prediction(self, code: str, analysis_type: str,
                          prediction: str, confidence: float,
                          date: str, details: str = ""):
        """记录一次LLM预测

        Args:
            code: 股票代码
            analysis_type: earnings / news_sentiment / stock_review
            prediction: positive / neutral / negative
            confidence: 置信度 0-1
            date: 预测日期
            details: 补充说明
        """
        record = {
            "code": code,
            "analysis_type": analysis_type,
            "prediction": prediction,
            "confidence": confidence,
            "date": date,
            "details": details,
            "outcome": None,       # 待后续填充
            "outcome_date": None,
            "verified": False,
        }

        # 存入DuckDB
        if self.store:
            df = pd.DataFrame([record])
            self.store.upsert_df("llm_predictions", df, ["code", "analysis_type", "date"])

    def update_outcome(self, code: str, prediction_date: str,
                       actual_return_5d: float):
        """更新预测的实际结果

        Args:
            code: 股票代码
            prediction_date: 预测日期
            actual_return_5d: 预测后5日实际收益率
        """
        if not self.store:
            return

        try:
            preds = self.store.get_table(
                "llm_predictions",
                where=f"code = '{code}' AND date = '{prediction_date}'"
            )
            if preds is None or preds.empty:
                return

            # 判断预测是否正确
            pred = preds.iloc[0]
            prediction = pred["prediction"]
            is_correct = self._judge_prediction(prediction, actual_return_5d)

            # 更新记录
            self.store.execute(f"""
                UPDATE llm_predictions
                SET outcome = {actual_return_5d},
                    outcome_date = '{datetime.now().strftime("%Y-%m-%d")}',
                    verified = true
                WHERE code = '{code}' AND date = '{prediction_date}'
            """)

            return is_correct

        except Exception as e:
            logger.debug(f"更新预测结果失败: {e}")
            return None

    def _judge_prediction(self, prediction: str, actual_return: float) -> bool:
        """判断预测是否正确"""
        if prediction == "positive":
            return actual_return > 0.005  # 涨超0.5%算正确
        elif prediction == "negative":
            return actual_return < -0.005
        else:  # neutral
            return abs(actual_return) < 0.01

    def get_accuracy_report(self, days: int = 90) -> dict:
        """获取LLM预测准确率报告"""
        if not self.store:
            return {"error": "store不可用"}

        try:
            preds = self.store.get_table("llm_predictions")
            if preds is None or preds.empty:
                return {"total": 0, "accuracy": None}

            # 只看已验证的
            verified = preds[preds["verified"] == True].copy()
            if verified.empty:
                return {"total": len(preds), "verified": 0, "accuracy": None}

            total = len(verified)
            correct = sum(
                self._judge_prediction(row["prediction"], row["outcome"])
                for _, row in verified.iterrows()
                if row["outcome"] is not None
            )

            # 按分析类型拆分
            by_type = {}
            for atype in verified["analysis_type"].unique():
                subset = verified[verified["analysis_type"] == atype]
                correct_t = sum(
                    self._judge_prediction(r["prediction"], r["outcome"])
                    for _, r in subset.iterrows()
                    if r["outcome"] is not None
                )
                by_type[atype] = {
                    "total": len(subset),
                    "correct": correct_t,
                    "accuracy": correct_t / len(subset) if len(subset) > 0 else 0,
                }

            return {
                "total": total,
                "correct": correct,
                "accuracy": correct / total if total > 0 else 0,
                "by_type": by_type,
            }

        except Exception as e:
            logger.debug(f"获取准确率报告失败: {e}")
            return {"error": str(e)}

    def get_llm_weight_modifier(self) -> float:
        """根据LLM准确率返回权重修正系数

        准确率 > 60%: 1.0（正常）
        准确率 50-60%: 0.7（降权）
        准确率 < 50%: 0.3（大幅降权）
        准确率 < 40%: 0.0（暂停LLM因子）
        """
        report = self.get_accuracy_report()
        accuracy = report.get("accuracy")

        if accuracy is None:
            return 1.0  # 没有足够数据，保持默认

        if accuracy > 0.6:
            return 1.0
        elif accuracy > 0.5:
            return 0.7
        elif accuracy > 0.4:
            return 0.3
        else:
            return 0.0

    def write_accuracy_to_knowledge(self):
        """将准确率报告写入知识库"""
        report = self.get_accuracy_report()
        if "error" in report:
            return

        lines = [
            f"## [{datetime.now().strftime('%Y-%m-%d')}] LLM预测准确率报告",
            f"",
            f"总预测: {report.get('total', 0)}次",
            f"已验证: {report.get('correct', 0)}次正确",
            f"准确率: {report.get('accuracy', 'N/A')}",
            f"权重修正: {self.get_llm_weight_modifier()}",
            f"",
        ]

        by_type = report.get("by_type", {})
        for atype, stats in by_type.items():
            lines.append(f"- {atype}: {stats['accuracy']:.1%} ({stats['correct']}/{stats['total']})")

        fpath = self.knowledge_dir / "llm_accuracy.md"
        with open(fpath, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
