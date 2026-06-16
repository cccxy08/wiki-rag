"""切片策略 — 标准切片与 Parent-Child 双层级切片"""
from __future__ import annotations
from langchain_text_splitters import RecursiveCharacterTextSplitter
from core.config import settings


class ChunkerMixin:
    def chunk_texts(self, texts: list[str], ext: str = "") -> list[str]:
        strategy = settings.chunk_strategy.get(ext.lstrip("."), {})
        cs = strategy.get("chunk_size", settings.chunk_size)
        co = strategy.get("chunk_overlap", settings.chunk_overlap)
        seps = strategy.get("separators", ["\n\n", "\n", ".", " ", ""])
        splitter = RecursiveCharacterTextSplitter(chunk_size=cs, chunk_overlap=co, separators=seps)
        full_text = "\n\n".join(texts)
        return splitter.split_text(full_text)

    def chunk_texts_parent_child(self, texts: list[str]) -> tuple[list[str], list[str], list[int]]:
        full_text = "\n\n".join(texts)

        parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.parent_chunk_size,
            chunk_overlap=settings.parent_chunk_overlap,
            separators=["\n\n", "\n", ".", " ", ""],
        )
        parent_chunks = parent_splitter.split_text(full_text)
        if not parent_chunks:
            return [], [], []

        child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.child_chunk_size,
            chunk_overlap=settings.child_chunk_overlap,
            separators=["\n\n", "\n", ".", " ", ""],
        )

        child_chunks = []
        child_to_parent = []
        for p_idx, parent in enumerate(parent_chunks):
            children = child_splitter.split_text(parent)
            child_chunks.extend(children)
            child_to_parent.extend([p_idx] * len(children))

        return child_chunks, parent_chunks, child_to_parent