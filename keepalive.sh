#!/bin/bash
# StockRadar Bot keepalive — 每分钟检查，挂了就重启
# 用法: nohup ./keepalive.sh &

PROJECT="/home/node/.openclaw/workspace/research/stockradar"
LOG="$PROJECT/logs/bot.log"
PID_FILE="$PROJECT/logs/bot.pid"

mkdir -p "$PROJECT/logs"

while true; do
    # 检查进程是否活着
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ! kill -0 "$PID" 2>/dev/null; then
            echo "$(date) Bot进程$PID已死，30秒后重启..." >> "$LOG"
            rm -f "$PID_FILE"
            sleep 30  # 给Telegram API缓冲，避免Conflict
        fi
    fi

    # 没有pid文件就启动
    if [ ! -f "$PID_FILE" ]; then
        echo "$(date) 启动Bot..." >> "$LOG"
        cd "$PROJECT"
        python3 scripts/run_bot.py >> "$LOG" 2>&1 &
        echo $! > "$PID_FILE"
        sleep 10
        # 启动失败检查
        if ! kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            echo "$(date) 启动失败，60秒后重试" >> "$LOG"
            rm -f "$PID_FILE"
            sleep 60
        fi
    fi

    sleep 60
done
