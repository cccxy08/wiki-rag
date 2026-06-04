#!/bin/bash
set -e

CHROMA_DIR="${CHROMA_PERSIST_DIR:-./chroma_db}"

if [ ! -d "$CHROMA_DIR" ] || [ -z "$(ls -A "$CHROMA_DIR" 2>/dev/null)" ]; then
    echo "ChromaDB 为空，自动重建索引..."
    python ingest_wiki_pages.py
    echo "索引重建完成"
else
    echo "ChromaDB 已有数据，跳过重建"
fi

echo "启动服务..."
exec python main.py
