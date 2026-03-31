"""回测入口脚本

用法:
    python scripts/run_backtest.py --start 2020-01-01 --end 2024-12-31
    python scripts/run_backtest.py --walk-forward
    python scripts/run_backtest.py --start 2020-01-01 --end 2024-12-31 --capital 2000000
"""

import argparse
import sys
from pathlib import Path

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

from src.backtest.engine import BacktestEngine
from src.backtest.report import BacktestReport
from src.data.store import DataStore
from src.infra.config import get_settings
from src.infra.logger import setup_logger


def parse_args():
    parser = argparse.ArgumentParser(description="A股策略回测")
    parser.add_argument(
        "--start", type=str, default="2020-01-01",
        help="回测开始日期 (默认 2020-01-01)",
    )
    parser.add_argument(
        "--end", type=str, default="2024-12-31",
        help="回测结束日期 (默认 2024-12-31)",
    )
    parser.add_argument(
        "--capital", type=float, default=None,
        help="初始资金 (默认从配置读取)",
    )
    parser.add_argument(
        "--benchmark", type=str, default="000300",
        help="基准指数代码 (默认 沪深300)",
    )
    parser.add_argument(
        "--walk-forward", action="store_true",
        help="运行 Walk-Forward 验证",
    )
    parser.add_argument(
        "--train-years", type=int, default=3,
        help="Walk-Forward 训练窗口年数 (默认 3)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="报告输出文件路径 (默认 打印到控制台)",
    )
    return parser.parse_args()


def run_simple_backtest(engine: BacktestEngine, args):
    """运行简单回测"""
    logger.info(f"运行回测: {args.start} ~ {args.end}")

    result = engine.run(
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
        benchmark_code=args.benchmark,
    )

    # 生成报告
    report_gen = BacktestReport()
    report = report_gen.generate(result)

    # 输出报告
    print(report["summary_text"])

    # 交易分析
    ta = report.get("trade_analysis", {})
    if ta.get("total_trades", 0) > 0:
        print(f"\n平均持仓天数: {ta.get('avg_hold_days', 0):.1f}")

    # 最佳/最差交易
    top_trades = report.get("top_trades", {})
    if top_trades.get("best"):
        print("\n── 最佳交易 Top5 ──")
        for t in top_trades["best"]:
            print(f"  {t['code']} @ {t['date']}: +{t['pnl']:,.0f} ({t['pnl_pct']:.1%})")

    if top_trades.get("worst"):
        print("\n── 最差交易 Top5 ──")
        for t in top_trades["worst"]:
            print(f"  {t['code']} @ {t['date']}: {t['pnl']:,.0f} ({t['pnl_pct']:.1%})")

    # 保存到文件
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report["summary_text"])
        logger.info(f"报告已保存到 {output_path}")

    return result, report


def run_walk_forward(engine: BacktestEngine, args):
    """运行Walk-Forward验证"""
    start_year = int(args.start[:4])
    end_year = int(args.end[:4])

    logger.info(
        f"运行 Walk-Forward: {start_year}~{end_year}, "
        f"训练{args.train_years}年"
    )

    wf_result = engine.run_walk_forward(
        start_year=start_year,
        end_year=end_year,
        train_years=args.train_years,
        benchmark_code=args.benchmark,
    )

    # 生成WF报告
    report_gen = BacktestReport()
    wf_report = report_gen.generate_walk_forward_report(wf_result)

    print(wf_report["summary_text"])

    # 保存到文件
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(wf_report["summary_text"])
        logger.info(f"Walk-Forward报告已保存到 {output_path}")

    return wf_result, wf_report


def main():
    args = parse_args()

    # 初始化
    setup_logger()
    store = DataStore()
    engine = BacktestEngine(store=store)

    if args.walk_forward:
        run_walk_forward(engine, args)
    else:
        run_simple_backtest(engine, args)


if __name__ == "__main__":
    main()
