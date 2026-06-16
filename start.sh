#!/bin/bash
set -e

DATA_DIR="${HF_HOME:-/data}"

mkdir -p "$DATA_DIR/wiki-data/wiki" "$DATA_DIR/wiki-data/raw" "$DATA_DIR/chroma_db" "$DATA_DIR/logs"

if [ ! -f "$DATA_DIR/wiki-data/.initialized" ]; then
    echo "首次启动，复制 wiki 初始数据到持久存储..."
    if [ -d "/app/wiki-data" ]; then
        cp -r /app/wiki-data/* "$DATA_DIR/wiki-data/" 2>/dev/null || true
    fi
    touch "$DATA_DIR/wiki-data/.initialized"
    echo "初始数据复制完成"
fi

echo "启动服务..."
exec python main.py
