"""ReporterAgent — 报告生成Agent

职责：日报/周报/月报、市场总结、新闻情绪
"""

import os
import json
from datetime import datetime
from pathlib import Path
from loguru import logger
import pandas as pd
import traceback

from src.core.agent_base import BaseAgent, AgentConfig, Observation, Plan, ActionResult
from src.data.stock_names import stock_name


class ReporterAgent(BaseAgent):
    """报告Agent"""

    def __init__(self, context=None, message_bus=None):
        config = AgentConfig(name="reporter", description="报告生成、市场总结")
        super().__init__(config, context, message_bus)

    async def perceive(self, context) -> Observation:
        msg = context.read("user_message", "") if context else ""
        return Observation(content={"user_message": msg})

    async def think(self, observation: Observation) -> Plan:
        msg = observation.content.get("user_message", "")
        if "周报" in msg:
            return Plan(actions=[{"action": "weekly_report"}])
        elif "月报" in msg:
            return Plan(actions=[{"action": "monthly_report"}])
        elif "新闻" in msg or "情绪" in msg or "舆情" in msg:
            return Plan(actions=[{"action": "news_sentiment"}])
        return Plan(actions=[{"action": "daily_report"}])

    async def act(self, plan: Plan) -> ActionResult:
        action = plan.actions[0].get("action", "daily_report") if plan.actions else "daily_report"
        try:
            if action == "weekly_report":
                return await self._weekly_report()
            elif action == "monthly_report":
                return await self._monthly_report()
            elif action == "news_sentiment":
                return await self._news_sentiment()
            return await self._daily_report()
        except Exception as e:
            logger.error(f"报告生成失败: {e}\n{traceback.format_exc()}")
            return ActionResult(success=False, message=f"报告失败: {e}")

    async def _daily_report(self) -> ActionResult:
        """增强日报 — 指数 + 涨跌排行 + 评分 + 持仓"""
        now = datetime.now()
        lines = [f"📰 **StockRadar 日报** {now.strftime('%Y-%m-%d')}\n"]

        # 1) 市场指数
        qveris_key = os.environ.get("QVERIS_API_KEY", "")
        if qveris_key:
            try:
                from src.data.qveris_adapter import fetch_index_quote_qv
                idx = fetch_index_quote_qv("000300")
                if idx and idx.get("最新(点)", "") not in ("", "---"):
                    chg = idx.get("涨跌幅(%)", "0")
                    try:
                        chg_f = float(chg)
                        mood = "🔴" if chg_f < -1 else "🟡" if chg_f < 0 else "🟢"
                    except ValueError:
                        mood = ""
                    lines.append(f"{mood} **沪深300:** {idx.get('最新(点)')} ({chg}%)")
                    lines.append(f"   成交额: {idx.get('成交额', '?')}")
            except Exception as e:
                lines.append("   (实时行情暂不可用)")
                logger.warning(f"QVeris失败: {e}")

        # 2) 关注池涨跌
        quote = self.context.read("data.daily_quote") if self.context else None
        if quote is not None and not quote.empty:
            latest_date = quote["date"].max()
            day = quote[quote["date"] == latest_date]
            if not day.empty and "change_pct" in day.columns:
                gains = day[day["change_pct"] > 0].sort_values("change_pct", ascending=False)
                losses = day[day["change_pct"] < 0].sort_values("change_pct")
                lines.append(f"\n📊 **涨跌榜** ({latest_date.strftime('%m-%d')})")
                if not gains.empty:
                    lines.append("🟢 涨:")
                    for _, r in gains.head(3).iterrows():
                        lines.append(f"  {stock_name(r['code'])}({r['code']}) {r['change_pct']:+.2f}%")
                if not losses.empty:
                    lines.append("🔴 跌:")
                    for _, r in losses.head(3).iterrows():
                        lines.append(f"  {stock_name(r['code'])}({r['code']}) {r['change_pct']:+.2f}%")

        # 3) 评分Top5
        scores = self.context.get_scores() if self.context else None
        if scores is not None and not scores.empty:
            lines.append("\n📋 **评分Top5:**")
            for i, (code, row) in enumerate(scores.head(5).iterrows()):
                lines.append(f"  {i+1}. {stock_name(code)} | {row['score_total']:+.2f}")

        # 4) 持仓+净值
        lines.append("\n📦 **模拟持仓:**")
        from src.simulator.nav_tracker import NAVTracker
        nav_dir = Path(__file__).resolve().parent.parent.parent / "data"
        # 优先读 nav_state_balanced.json，兼容 nav_state.json
        nav_file = nav_dir / "nav_state_balanced.json"
        if not nav_file.exists():
            nav_file = nav_dir / "nav_state.json"
        if nav_file.exists():
            try:
                nav = NAVTracker.from_dict(json.loads(nav_file.read_text()))
                info = nav.get_nav()
                lines.append(f"  💰 净值: {info['nav']:.4f} | 收益: {info['total_return']:+.2f}%")
                lines.append(f"  📦 持仓: {info['holdings_count']}只 | 交易: {info['trades']}笔")
                if nav.holdings:
                    for code, h in sorted(nav.holdings.items()):
                        lines.append(f"  · {stock_name(code)} {h['shares']}股@¥{h['cost_price']:.2f}")
            except Exception:
                lines.append("  模拟模式")
        else:
            lines.append("  尚未建仓，发送'持仓建议'开始")

        # 5) 新闻情绪
        try:
            from src.data.news_sentiment import get_market_sentiment_report
            report = get_market_sentiment_report()
            # 提取情绪指标（只取前5行）
            for line in report.split("\n")[1:5]:
                if line.strip():
                    lines.append(line)
        except Exception:
            pass

        # 6) Tushare enrichment (northbound + sectors)
        try:
            from src.data.tushare_adapter import enrich_report_with_tushare
            ts_data = enrich_report_with_tushare()
            if ts_data:
                lines.append("")
                for v in ts_data.values():
                    lines.append(v)
        except Exception:
            pass

        # 7) 持仓诊断
        try:
            from src.evolution.strategy_doctor import diagnose_holdings
            import json as _json
            nav_f = Path(__file__).resolve().parent.parent.parent / "data"
            for f in sorted(nav_f.glob("nav_state*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:1]:
                nav_data = _json.loads(f.read_text())
                if nav_data.get("holdings"):
                    diag = diagnose_holdings(nav_data)
                    lines.append("\n" + diag)
        except Exception:
            pass

        return ActionResult(success=True, message="\n".join(lines))

    async def _weekly_report(self) -> ActionResult:
        """周报"""
        import json as _json
        lines = ["📰 **StockRadar 周报**\n"]
        
        # 找最新nav状态
        nav_dir = Path(__file__).resolve().parent.parent.parent / "data"
        nav_files = sorted(nav_dir.glob("nav_state*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not nav_files:
            lines.append("暂无数据，发送'持仓建议'开始")
            return ActionResult(success=True, message="\n".join(lines))
        
        try:
            from src.simulator.nav_tracker import NAVTracker
            nav = NAVTracker.from_dict(_json.loads(nav_files[0].read_text()))
            
            if len(nav.nav_history) < 5:
                lines.append("净值数据不足5天，继续运行中")
                return ActionResult(success=True, message="\n".join(lines))
            
            nav_df = pd.DataFrame(nav.nav_history)
            nav_df["date"] = pd.to_datetime(nav_df["date"])
            latest = nav_df["date"].max()
            week_ago = latest - pd.Timedelta(days=7)
            month_ago = latest - pd.Timedelta(days=30)
            
            week = nav_df[nav_df["date"] >= week_ago]
            month = nav_df[nav_df["date"] >= month_ago]
            
            # 1) 本周表现
            if len(week) >= 2:
                week_ret = (week["nav"].iloc[-1] / week["nav"].iloc[0] - 1) * 100
                week_high = week["nav"].max()
                week_low = week["nav"].min()
                lines.append(f"📊 **本周:** {week_ret:+.2f}%")
                lines.append(f"   高{week_high:.4f} | 低{week_low:.4f} | 振幅{(week_high/week_low-1)*100:.1f}%")
            
            # 2) 本月表现
            if len(month) >= 2:
                month_ret = (month["nav"].iloc[-1] / month["nav"].iloc[0] - 1) * 100
                lines.append(f"📅 **本月:** {month_ret:+.2f}%")
            
            # 3) 累计
            info = nav.get_nav()
            lines.append(f"💰 **累计:** {info['total_return']:+.2f}% | 净值{info['nav']:.4f}")
            lines.append(f"📦 持仓{info['holdings_count']}只 | 交易{info['trades']}笔")
            
            # 4) 持仓明细
            if nav.holdings:
                from src.data.industry import _load_industry
                ind_df = _load_industry()
                names = dict(zip(ind_df["code"], ind_df["name"])) if not ind_df.empty else {}
                
                lines.append("\n📋 **持仓周表现:**")
                daily_quote = self.context.read("data.daily_quote") if self.context else None
                
                stock_rets = []
                for code, pos in nav.holdings.items():
                    name = names.get(code, code)
                    if daily_quote is not None and not daily_quote.empty:
                        sd = daily_quote[daily_quote["code"] == code]
                        if len(sd) >= 5:
                            r5 = (sd["close"].iloc[-1] / sd["close"].iloc[-5] - 1) * 100
                            stock_rets.append((name, r5, code))
                        else:
                            stock_rets.append((name, 0, code))
                    else:
                        stock_rets.append((name, 0, code))
                
                stock_rets.sort(key=lambda x: x[1], reverse=True)
                for name, ret, _ in stock_rets:
                    emoji = "🟢" if ret > 0 else "🔴" if ret < 0 else "➖"
                    lines.append(f"  {emoji} {name}: {ret:+.1f}%")
            
            # 5) 新闻情绪
            try:
                from src.data.news_sentiment import get_market_sentiment_report
                report = get_market_sentiment_report()
                for line in report.split("\n")[1:3]:
                    if line.strip():
                        lines.append(f"\n{line}")
            except Exception:
                pass
            
            # 6) 持仓诊断
            try:
                from src.evolution.strategy_doctor import diagnose_holdings
                nav_data = _json.loads(nav_files[0].read_text())
                daily_quote = self.context.read("data.daily_quote") if self.context else None
                scores = self.context.get_scores() if self.context else None
                diag = diagnose_holdings(nav_data, daily_quote, scores)
                lines.append("\n" + diag)
            except Exception:
                pass
                
        except Exception as e:
            lines.append(f"报告生成失败: {e}")
        
        return ActionResult(success=True, message="\n".join(lines))

    async def _monthly_report(self) -> ActionResult:
        """月报"""
        import json as _json
        lines = ["📰 **StockRadar 月报**\n"]
        
        nav_dir = Path(__file__).resolve().parent.parent.parent / "data"
        nav_files = sorted(nav_dir.glob("nav_state*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not nav_files:
            lines.append("暂无数据")
            return ActionResult(success=True, message="\n".join(lines))
        
        try:
            from src.simulator.nav_tracker import NAVTracker
            nav = NAVTracker.from_dict(_json.loads(nav_files[0].read_text()))
            
            if len(nav.nav_history) < 10:
                lines.append("净值数据不足，继续运行中")
                return ActionResult(success=True, message="\n".join(lines))
            
            nav_df = pd.DataFrame(nav.nav_history)
            nav_df["date"] = pd.to_datetime(nav_df["date"])
            latest = nav_df["date"].max()
            month_ago = latest - pd.Timedelta(days=30)
            
            month = nav_df[nav_df["date"] >= month_ago]
            all_time = nav_df
            
            # 1) 月度表现
            if len(month) >= 2:
                month_ret = (month["nav"].iloc[-1] / month["nav"].iloc[0] - 1) * 100
                month_high = month["nav"].max()
                month_low = month["nav"].min()
                lines.append(f"📊 **本月收益:** {month_ret:+.2f}%")
                lines.append(f"   最高{month_high:.4f} | 最低{month_low:.4f}")
            
            # 2) 累计
            info = nav.get_nav()
            total_ret = info['total_return']
            lines.append(f"\n💰 **累计收益:** {total_ret:+.2f}%")
            lines.append(f"📦 持仓{info['holdings_count']}只 | 交易{info['trades']}笔")
            
            # 3) 净值曲线概览
            if len(all_time) >= 20:
                n = len(all_time)
                peak = all_time["nav"].max()
                trough = all_time["nav"].min()
                max_dd = ((all_time["nav"] / all_time["nav"].cummax()) - 1).min() * 100
                lines.append(f"\n📈 **净值统计:**")
                lines.append(f"   最高{peak:.4f} | 最低{trough:.4f}")
                lines.append(f"   最大回撤{max_dd:.1f}% | 数据{n}天")
            
            # 4) 回测摘要
            lines.append("\n📊 **历史回测参考:**")
            lines.append("  2024: +46.2% Sharpe 0.75")
            lines.append("  2025: +37.3% Sharpe 1.24")
            
            # 5) 新闻+诊断
            try:
                from src.data.news_sentiment import get_market_sentiment_report
                report = get_market_sentiment_report()
                for line in report.split("\n")[1:3]:
                    if line.strip():
                        lines.append(f"\n{line}")
            except Exception:
                pass
            
            try:
                from src.evolution.strategy_doctor import diagnose_holdings
                nav_data = _json.loads(nav_files[0].read_text())
                daily_quote = self.context.read("data.daily_quote") if self.context else None
                scores = self.context.get_scores() if self.context else None
                diag = diagnose_holdings(nav_data, daily_quote, scores)
                lines.append("\n" + diag)
            except Exception:
                pass
                
        except Exception as e:
            lines.append(f"月报生成失败: {e}")
        
        return ActionResult(success=True, message="\n".join(lines))

    async def _news_sentiment(self) -> ActionResult:
        """新闻情绪报告"""
        try:
            from src.data.news_sentiment import get_market_sentiment_report
            report = get_market_sentiment_report()
            return ActionResult(success=True, message=report)
        except Exception as e:
            return ActionResult(success=False, message="新闻情绪暂不可用: " + str(e))
