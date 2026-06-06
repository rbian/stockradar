"""FinBERT Sentiment Adapter — 金融文本情绪分析

Based on alphaear-sentiment from Awesome-finance-skills.
Uses FinBERT (Prospectus) model for financial sentiment analysis.

Score: -1.0 (negative) to +1.0 (positive)
"""

from loguru import logger

_model = None
_tokenizer = None


def _get_model():
    """Lazy load FinBERT model"""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch

        model_name = "ProsusAI/finbert"
        logger.info(f"Loading FinBERT model: {model_name}")
        _tokenizer = AutoTokenizer.from_pretrained(model_name)
        _model = AutoModelForSequenceClassification.from_pretrained(model_name)
        _model.eval()
        logger.info("FinBERT loaded successfully")
        return _model, _tokenizer
    except Exception as e:
        logger.warning(f"FinBERT load failed: {e}")
        return None, None


def analyze_sentiment(text: str) -> dict:
    """Analyze sentiment of a single financial text

    Uses FinBERT for English text, keyword fallback for Chinese.

    Returns:
        {'score': float (-1.0 to 1.0), 'label': str, 'reason': str}
    """
    model, tokenizer = _get_model()
    if model is None:
        return {"score": 0.0, "label": "neutral", "reason": "model unavailable"}

    try:
        import torch
        import re

        # If mostly CJK, use keyword analysis (FinBERT is English-only)
        cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
        if cjk > len(text) * 0.3:
            return _analyze_chinese(text)

        # FinBERT for English
        inputs = tokenizer(text[:512], return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)[0]
        scores = {"positive": probs[0].item(), "negative": probs[1].item(), "neutral": probs[2].item()}
        best_label = max(scores, key=scores.get)

        if best_label == "positive":
            score = round(float(scores["positive"]), 3)
        elif best_label == "negative":
            score = -round(float(scores["negative"]), 3)
        else:
            score = 0.0

        reason = f"pos={scores['positive']:.2f} neg={scores['negative']:.2f} neu={scores['neutral']:.2f}"
        return {"score": score, "label": best_label, "reason": reason}

    except Exception as e:
        logger.warning(f"Sentiment analysis failed: {e}")
        return {"score": 0.0, "label": "neutral", "reason": str(e)}


def _analyze_chinese(text: str) -> dict:
    """Keyword-based Chinese financial sentiment analysis"""
    bullish_words = [
        "增长", "超预期", "利好", "上涨", "突破", "新高", "回购",
        "增持", "大增", "暴涨", "利好", "盈利", "扭亏", "预增",
        "订单", "中标", "签约", "获批", "创纪录", "翻倍", "暴涨",
        "政策支持", "市场份额", "强劲",
    ]
    bearish_words = [
        "下跌", "暴跌", "亏损", "预亏", "减持", "处罚",
        "放缓", "下滑", "萎缩", "风险", "预警", "违约",
        "不及预期", "下降", "跌停", "承压", "低迷", "困境",
        "负增长", "缩水", "退市", "调查", "涉嫌", "造假",
        "被罚", "诉讼", "召回", "减值",
    ]

    bull_hits = sum(1 for w in bullish_words if w in text)
    bear_hits = sum(1 for w in bearish_words if w in text)
    total = bull_hits + bear_hits

    if total == 0:
        return {"score": 0.0, "label": "neutral", "reason": "无明显情绪词"}

    # Calculate score with intensity
    intensity_modifiers = {"大幅": 1.5, "显著": 1.5, "持续": 1.3, "严重": 1.5, "超": 1.3}
    modifier = 1.0
    for m, mult in intensity_modifiers.items():
        if m in text:
            modifier = max(modifier, mult)

    net = (bull_hits - bear_hits) / total * modifier
    score = round(min(1.0, max(-1.0, net)), 3)

    if score > 0.15:
        label = "positive"
    elif score < -0.15:
        label = "negative"
    else:
        label = "neutral"

    reason = f"bull={bull_hits} bear={bear_hits} modifier={modifier:.1f}"
    return {"score": score, "label": label, "reason": reason}


def batch_analyze(texts: list[str]) -> list[dict]:
    """Analyze sentiment of multiple texts (batched for efficiency)"""
    model, tokenizer = _get_model()
    if model is None:
        return [{"score": 0.0, "label": "neutral", "reason": "model unavailable"}] * len(texts)

    results = []
    for text in texts:
        results.append(analyze_sentiment(text))
    return results


def analyze_stock_news(code: str, news: list[str]) -> dict:
    """Analyze sentiment for a stock based on its news

    Args:
        code: stock code
        news: list of news headlines/descriptions

    Returns:
        {'code': str, 'avg_score': float, 'positive_count': int,
         'negative_count': int, 'news_count': int, 'signals': list}
    """
    if not news:
        return {"code": code, "avg_score": 0.0, "positive_count": 0,
                "negative_count": 0, "news_count": 0, "signals": []}

    sentiments = batch_analyze(news)
    scores = [s["score"] for s in sentiments]
    avg_score = sum(scores) / len(scores) if scores else 0.0

    positive = sum(1 for s in sentiments if s["label"] == "positive")
    negative = sum(1 for s in sentiments if s["label"] == "negative")

    signals = []
    for i, (news_item, sent) in enumerate(zip(news, sentiments)):
        if abs(sent["score"]) > 0.5:  # Only include strong signals
            signals.append({
                "news": news_item[:100],
                "score": sent["score"],
                "label": sent["label"],
            })

    return {
        "code": code,
        "avg_score": round(avg_score, 3),
        "positive_count": positive,
        "negative_count": negative,
        "news_count": len(news),
        "signals": sorted(signals, key=lambda x: abs(x["score"]), reverse=True),
    }


def format_sentiment_report(analysis: dict) -> str:
    """Format stock news sentiment into readable report"""
    if not analysis or analysis.get("news_count", 0) == 0:
        return "暂无新闻情绪数据"

    score = analysis["avg_score"]
    emoji = "🟢" if score > 0.1 else "🔴" if score < -0.1 else "⚪"

    lines = [f"{emoji} **{analysis['code']}** 情绪评分: {score:+.2f}"]
    lines.append(f"   新闻: {analysis['news_count']}条 | 正面: {analysis['positive_count']} | 负面: {analysis['negative_count']}")

    if analysis.get("signals"):
        lines.append(f"\n   强信号 (top 3):")
        for sig in analysis["signals"][:3]:
            tag = "📈" if sig["score"] > 0 else "📉"
            lines.append(f"     {tag} [{sig['label']}] {sig['news']}")

    return "\n".join(lines)
