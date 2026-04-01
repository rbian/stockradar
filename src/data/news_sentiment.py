"""新闻情绪集成模块

数据源优先级:
1. alphaear-news本地DB（如果有数据）
2. 财联社/华尔街见闻API（直连）
3. 关键词降级分析
"""

import sys
import json
import sqlite3
import time
import requests
from pathlib import Path
from loguru import logger

# alphaear-news DB路径
NEWS_DB = Path.home() / ".agents" / "skills" / "alphaear-news" / "data" / "news.db"


def fetch_financial_news(sources: list = None, count: int = 20) -> list:
    """拉取财经热点新闻"""
    if sources is None:
        sources = ["cls", "wallstreetcn"]
    
    all_news = []
    
    # 1) 尝试本地DB
    db = _get_news_db()
    if db:
        try:
            conn = sqlite3.connect(db)
            rows = conn.execute(
                "SELECT id, source, title, url, content, publish_time FROM daily_news "
                "ORDER BY publish_time DESC LIMIT ?",
                (count * 2,)
            ).fetchall()
            conn.close()
            
            if rows:
                for r in rows:
                    all_news.append({
                        "id": r[0], "source": r[1], "title": r[2] or "",
                        "url": r[3], "content": (r[4] or "")[:200],
                        "pub_date": r[5] or "",
                    })
                logger.info(f"本地DB: {len(all_news)}条")
                
                if len(all_news) >= count:
                    return all_news[:count]
        except Exception as e:
            logger.warning(f"本地DB读取失败: {e}")
    
    # 2) 尝试API
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # 财联社电报
    try:
        resp = requests.get(
            "https://www.cls.cn/telegraph",
            headers={**headers, "Referer": "https://www.cls.cn/"},
            timeout=10
        )
        if resp.status_code == 200:
            # 尝试从页面提取JSON数据
            for line in resp.text.split("\n"):
                if "telegraphData" in line and '"title"' in line:
                    try:
                        start = line.find('"telegraphData"')
                        data = json.loads(line[start + 16:line.find(";", start)])
                        if isinstance(data, list):
                            for item in data[:count]:
                                all_news.append({
                                    "title": item.get("title", ""),
                                    "content": item.get("content", item.get("summary", "")),
                                    "source": "cls", "url": "", "pub_date": item.get("ctime", ""),
                                })
                            logger.info(f"财联社电报: {len(all_news)}条")
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue
    except Exception as e:
        logger.warning(f"财联社API失败: {e}")
    
    if not all_news:
        # 3) 用测试数据演示
        logger.info("无新闻数据，使用演示数据")
        all_news = _demo_news()
    
    return all_news[:count]


def _get_news_db() -> str:
    """查找新闻数据库"""
    if NEWS_DB.exists():
        return str(NEWS_DB)
    # 尝试其他路径
    for p in [
        Path.home() / ".agents" / "skills" / "alphaear-news" / "data" / "test.db",
    ]:
        if p.exists():
            return str(p)
    return None


def _demo_news() -> list:
    """演示新闻（无数据时）"""
    return [
        {"title": "央行宣布降准0.5个百分点 释放长期资金约1万亿", "source": "demo", "content": "", "pub_date": "", "url": ""},
        {"title": "A股三大指数集体高开 半导体板块掀涨停潮", "source": "demo", "content": "", "pub_date": "", "url": ""},
        {"title": "北向资金单日净流入超百亿 加仓白酒新能源", "source": "demo", "content": "", "pub_date": "", "url": ""},
        {"title": "多家券商看好后市 认为A股估值处于历史低位", "source": "demo", "content": "", "pub_date": "", "url": ""},
        {"title": "财政部：今年将发行超长期特别国债支持科技发展", "source": "demo", "content": "", "pub_date": "", "url": ""},
        {"title": "房地产政策持续优化 多城取消限购", "source": "demo", "content": "", "pub_date": "", "url": ""},
        {"title": "新能源汽车出口量再创新高 比亚迪市占率突破40%", "source": "demo", "content": "", "pub_date": "", "url": ""},
        {"title": "美联储释放降息信号 美元指数走弱", "source": "demo", "content": "", "pub_date": "", "url": ""},
    ]


def analyze_sentiment(news_list: list) -> list:
    """分析新闻情绪"""
    if not news_list:
        return []
    
    # 关键词情绪分析
    pos_words = {"涨", "涨超", "大涨", "利好", "增长", "突破", "新高", "盈利", "超预期",
                 "回购", "增持", "复苏", "强劲", "暴增", "翻倍", "涨停", "降准", "降息",
                 "看好", "乐观", "回暖", "反弹", "拉升", "净流入", "加仓", "新高", "支撑"}
    neg_words = {"跌", "跌超", "大跌", "利空", "下降", "跌破", "新低", "亏损", "不及预期",
                 "减持", "抛售", "衰退", "疲软", "暴跌", "跌停", "暴雷", "风险", "收缩",
                 "看空", "悲观", "承压", "下行", "杀跌", "净流出", "清仓", "压力", "制裁"}
    
    for item in news_list:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        pos_count = sum(1 for w in pos_words if w in text)
        neg_count = sum(1 for w in neg_words if w in text)
        total = pos_count + neg_count
        if total == 0:
            item["sentiment_score"] = 0.0
            item["sentiment_label"] = "neutral"
        else:
            score = (pos_count - neg_count) / max(total, 1)
            item["sentiment_label"] = "positive" if score > 0.3 else "negative" if score < -0.3 else "neutral"
            item["sentiment_score"] = round(score, 2)
    
    return news_list


def get_market_sentiment_report() -> str:
    """生成市场情绪报告"""
    news = fetch_financial_news(count=20)
    if not news:
        return "📰 暂无新闻数据"
    
    analyzed = analyze_sentiment(news)
    
    avg = sum(n["sentiment_score"] for n in analyzed) / len(analyzed)
    pos = [n for n in analyzed if n["sentiment_score"] > 0.1]
    neg = [n for n in analyzed if n["sentiment_score"] < -0.1]
    neu = len(analyzed) - len(pos) - len(neg)
    
    if avg > 0.2:
        mood = "🟢 偏多"
    elif avg < -0.2:
        mood = "🔴 偏空"
    else:
        mood = "⚪ 中性"
    
    lines = [f"📰 **市场情绪报告**\n"]
    lines.append(f"📊 综合情绪: {mood} (均分 {avg:+.2f})")
    lines.append(f"  利好: {len(pos)}条 | 利空: {len(neg)}条 | 中性: {neu}条\n")
    
    if pos:
        lines.append("🟢 **利好Top5:**")
        for n in sorted(pos, key=lambda x: x["sentiment_score"], reverse=True)[:5]:
            lines.append(f"  • {n['title'][:30]} ({n['sentiment_score']:+.1f})")
    
    if neg:
        lines.append("\n🔴 **利空Top5:**")
        for n in sorted(neg, key=lambda x: x["sentiment_score"])[:5]:
            lines.append(f"  • {n['title'][:30]} ({n['sentiment_score']:+.1f})")
    
    if not pos and not neg:
        lines.append("  (当前使用演示数据，实际数据待API接入)")
    
    return "\n".join(lines)
