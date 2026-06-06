"""数据源健康巡检 — 检测各数据源缓存新鲜度，超期告警

监控项:
- 新浪行情: data/parquet/hs300_daily.parquet 最新日期
- Tushare缓存: northbound/sector/dragon_tiger 最新缓存日期
- Bot进程: 是否存活、PID是否匹配
- 日志异常: 近24h WARNING/ERROR 数量

触发: 每个交易日 9:35 (开盘前5分钟) + 每天 18:00 (收盘后)
告警: 超过阈值则通过 Telegram 推送
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"

# ── 告警状态持久化 (避免重复告警) ──
_ALERT_STATE_FILE = DATA_DIR / "cache" / "data_health_state.json"
# 已告警的问题: {"key": "last_alert_timestamp"}
_alert_state: dict = {}

# ── 配置 ──
WARN_STALE_DAYS = 3  # 超过3天未更新 → 告警
ALERT_STALE_DAYS = 7  # 超过7天 → 严重告警
ALERT_COOLDOWN = 86400  # 同一问题24h内不重复告警


def _load_alert_state():
    global _alert_state
    if _ALERT_STATE_FILE.exists():
        try:
            _alert_state = json.loads(_ALERT_STATE_FILE.read_text())
        except Exception:
            _alert_state = {}
    return _alert_state


def _save_alert_state():
    try:
        _ALERT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ALERT_STATE_FILE.write_text(json.dumps(_alert_state))
    except Exception:
        pass


def _should_alert(key: str) -> bool:
    """检查是否应该告警（避免重复）"""
    now = datetime.now().timestamp()
    last = _alert_state.get(key, 0)
    if now - last < ALERT_COOLDOWN:
        return False
    _alert_state[key] = now
    _save_alert_state()
    return True


# ── 检查函数 ──

def check_sina_daily() -> dict:
    """检查新浪行情parquet最新日期"""
    result = {"name": "新浪行情", "status": "ok", "detail": ""}
    try:
        import pandas as pd
        pq_path = DATA_DIR / "parquet" / "hs300_daily.parquet"
        if not pq_path.exists():
            result["status"] = "missing"
            result["detail"] = "parquet文件不存在"
            return result
        
        df = pd.read_parquet(pq_path, columns=["date"])
        if df.empty:
            result["status"] = "empty"
            result["detail"] = "无数据"
            return result
        
        latest = pd.to_datetime(df["date"]).max()
        age = (datetime.now() - latest.to_pydatetime()).days
        result["detail"] = f"最新={latest.strftime('%Y-%m-%d')}, 距今{age}天"
        
        if age > ALERT_STALE_DAYS:
            result["status"] = "alert"
        elif age > WARN_STALE_DAYS:
            result["status"] = "warn"
    except Exception as e:
        result["status"] = "error"
        result["detail"] = str(e)
    
    return result


def check_tushare_caches() -> list:
    """检查Tushare各缓存项"""
    results = []
    tushare_dir = CACHE_DIR / "tushare"
    
    for prefix, label in [
        ("northbound", "北向资金"),
        ("sector", "行业强弱"),
        ("dragon_tiger", "龙虎榜"),
    ]:
        item = {"name": label, "status": "ok", "detail": ""}
        subdir = tushare_dir / prefix
        
        if not subdir.exists():
            item["status"] = "missing"
            item["detail"] = "缓存目录不存在"
            results.append(item)
            continue
        
        files = list(subdir.glob("*.parquet"))
        if not files:
            item["status"] = "missing"
            item["detail"] = "无缓存文件"
            results.append(item)
            continue
        
        latest_file = max(files, key=lambda f: f.stat().st_mtime)
        mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
        age = (datetime.now() - mtime).days
        item["detail"] = f"最新={latest_file.stem}, 距今{age}天"
        
        if age > ALERT_STALE_DAYS:
            item["status"] = "alert"
        elif age > WARN_STALE_DAYS:
            item["status"] = "warn"
        
        results.append(item)
    
    return results


def check_bot_process() -> dict:
    """检查Bot进程状态"""
    result = {"name": "Bot进程", "status": "ok", "detail": ""}
    pid_file = DATA_DIR / "bot.pid"
    
    if not pid_file.exists():
        result["status"] = "warn"
        result["detail"] = "PID文件不存在"
        return result
    
    try:
        pid = int(pid_file.read_text().strip())
        pid_path = Path(f"/proc/{pid}")
        if not pid_path.exists():
            result["status"] = "alert"
            result["detail"] = f"PID {pid} 进程已死"
        else:
            result["detail"] = f"PID={pid}, 运行中"
    except Exception as e:
        result["status"] = "warn"
        result["detail"] = str(e)
    
    return result


def check_log_errors(hours: int = 24) -> dict:
    """检查日志中WARNING/ERROR数量"""
    result = {"name": "日志告警", "status": "ok", "detail": ""}
    
    try:
        log_file = PROJECT_ROOT / "logs" / "bot_stderr.log"
        if not log_file.exists():
            result["detail"] = "日志文件不存在"
            return result
        
        mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
        if (datetime.now() - mtime).total_seconds() > hours * 3600:
            result["detail"] = f"日志超过{hours}h未更新"
            return result
        
        content = log_file.read_text(errors="replace")
        warnings = content.count("WARNING")
        errors = content.count("ERROR")
        
        # 只统计最近的行 (避免统计历史)
        lines = content.strip().split("\n")
        recent_lines = []
        cutoff = datetime.now() - timedelta(hours=hours)
        for line in lines[-5000:]:  # 只看最后5000行
            match = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if match:
                try:
                    ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
                    if ts >= cutoff:
                        recent_lines.append(line)
                except ValueError:
                    continue
        
        recent_warnings = sum(1 for l in recent_lines if "WARNING" in l)
        recent_errors = sum(1 for l in recent_lines if "ERROR" in l)
        result["detail"] = f"近{hours}h: {recent_warnings} WARNING, {recent_errors} ERROR"
        
        if recent_errors > 10:
            result["status"] = "alert"
        elif recent_errors > 3 or recent_warnings > 20:
            result["status"] = "warn"
    except Exception as e:
        result["status"] = "error"
        result["detail"] = str(e)
    
    return result


# ── 主巡检入口 ──

def run_health_check() -> str:
    """执行全部健康检查，返回告警文本（无告警返回空字符串）"""
    _load_alert_state()
    
    all_checks = []
    all_checks.append(check_sina_daily())
    all_checks.extend(check_tushare_caches())
    all_checks.append(check_bot_process())
    all_checks.append(check_log_errors())
    
    problems = [c for c in all_checks if c["status"] != "ok"]
    
    if not problems:
        logger.info("数据源健康检查: 全部正常")
        _save_alert_state()
        return ""
    
    # 格式化告警消息
    lines = ["⚠️ **数据源健康巡检告警**\n"]
    
    for check in all_checks:
        icon = "✅"
        if check["status"] == "warn":
            icon = "🟡"
        elif check["status"] == "alert":
            icon = "🔴"
        elif check["status"] in ("missing", "error"):
            icon = "⚫"
        
        lines.append(f"{icon} {check['name']}: {check['detail']}")
    
    # 添加问题摘要和建议
    alert_items = [c for c in problems if c["status"] in ("alert", "missing")]
    warn_items = [c for c in problems if c["status"] == "warn"]
    
    if alert_items:
        lines.append(f"\n🔴 严重: {len(alert_items)}项需立即处理")
        for c in alert_items:
            lines.append(f"  - {c['name']}: {c['detail']}")
    
    if warn_items:
        lines.append(f"\n🟡 警告: {len(warn_items)}项需关注")
        for c in warn_items:
            lines.append(f"  - {c['name']}: {c['detail']}")
    
    # 常见问题处理建议
    if any("北向" in c["name"] and c["status"] != "ok" for c in problems):
        lines.append("\n💡 Tushare免费版1次/小时/API，限流正常。系统会自动fallback到最近缓存。")
    
    if any("新浪" in c["name"] and c["status"] != "ok" for c in problems):
        lines.append("\n💡 行情数据过期请检查: `python3 -c 'from src.data.sina_adapter import update_daily_from_sina; print(\"ok\")'`")
    
    message = "\n".join(lines)
    
    # 只在有新问题或升级时告警
    has_new_alert = any(c["status"] in ("alert", "missing") for c in problems)
    alert_key = f"health_{'_'.join(sorted(c['name'] for c in problems))}"
    
    if has_new_alert or _should_alert(alert_key):
        logger.warning(f"数据源健康检查发现 {len(problems)} 个问题")
    else:
        logger.info(f"数据源健康检查: {len(problems)}个问题(已告警，跳过重复)")
        message = ""  # 已告警过，不重复发送
    
    return message
