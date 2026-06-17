#!/bin/bash

CHROMA_DIR="${CHROMA_PERSIST_DIR:-./chroma_db}"

if [ ! -d "$CHROMA_DIR" ] || [ -z "$(ls -A "$CHROMA_DIR" 2>/dev/null)" ]; then
    echo "ChromaDB 为空，尝试重建索引..."
    python ingest_wiki_pages.py || echo "⚠️ 索引重建跳过（API Key未配置或无数据），服务仍可启动"
else
    echo "ChromaDB 已有数据，跳过重建"
fi

echo "启动服务..."
exec python main.py
