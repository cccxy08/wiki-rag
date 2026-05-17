"""RAG 引擎 - 文档加载、切片、向量化、检索"""
import hashlib
from pathlib import Path
from typing import Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings as ChromaSettings

from core.config import settings
from core.llm_provider import get_llm


class RAGEngine:
    """RAG 引擎 - 文档检索与问答"""

    def __init__(self):
        self.llm = get_llm()
        self.embeddings = SentenceTransformer("D:/CodeXFiles/backend/models", device="cpu")
        self.chroma_client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name=settings.chroma_collection_name,
        )
        self._loader_map = {
            ".pdf": self._load_pdf,
            ".txt": self._load_text,
            ".md": self._load_markdown,
            ".docx": self._load_docx,
        }

    # ========== 文档加载 ==========

    def load_file(self, file_path: Path) -> list[str]:
        """加载单个文件，返回文本段落列表"""
        ext = file_path.suffix.lower()
        loader = self._loader_map.get(ext)
        if loader is None:
            raise ValueError(f"不支持的文件格式: {ext}（支持: {list(self._loader_map.keys())}")
        return loader(file_path)

    def _load_pdf(self, path: Path) -> list[str]:
        try:
            import fitz  # pymupdf
            doc = fitz.open(str(path))
            texts = []
            for page in doc:
                t = page.get_text()
                if t.strip():
                    texts.append(t)
            return texts
        except ImportError:
            raise ImportError("请安装 pymupdf: pip install pymupdf")

    def _load_text(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [text] if text.strip() else []

    def _load_markdown(self, path: Path) -> list[str]:
        text = path.read_text(encoding="utf-8")
        return [text] if text.strip() else []

    def _load_docx(self, path: Path) -> list[str]:
        try:
            from docx import Document
            doc = Document(str(path))
            return [p.text for p in doc.paragraphs if p.text.strip()]
        except ImportError:
            raise ImportError("请安装 python-docx: pip install python-docx")

    # ========== 切片 & 向量化 ==========

    def chunk_texts(self, texts: list[str], ext: str = "") -> list[str]:
        strategy = settings.chunk_strategy.get(ext.lstrip("."), {})
        cs = strategy.get("chunk_size", settings.chunk_size)
        co = strategy.get("chunk_overlap", settings.chunk_overlap)
        seps = strategy.get("separators", ["\n\n", "\n", ".", " ", ""])
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=cs,
            chunk_overlap=co,
            separators=seps,
        )
        full_text = "\n\n".join(texts)
        return splitter.split_text(full_text)

    def index_document(self, file_path: Path) -> int:
        """索引一个文档：加载 → 切片 → 向量化 → 存入 Chroma"""
        try:
            texts = self.load_file(file_path)
        except Exception as e:
            raise RuntimeError(f"文档加载失败 [{file_path.name}]: {e}")

        if not texts:
            raise ValueError(f"文档内容为空: {file_path.name}")

        chunks = self.chunk_texts(texts, file_path.suffix)
        if not chunks:
            raise ValueError(f"切片后无内容: {file_path.name}")

        # 为每个 chunk 生成 ID
        ids = []
        for i, chunk in enumerate(chunks):
            chunk_hash = hashlib.md5(chunk.encode()).hexdigest()[:12]
            ids.append(f"{file_path.stem}_{i}_{chunk_hash}")

        # 向量化 + 存入
        embeddings = self.embeddings.encode(chunks, show_progress_bar=False).tolist()
        metadatas = [
            {"source": file_path.name, "chunk_index": i, "path": str(file_path)}
            for i in range(len(chunks))
        ]

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=chunks,
            metadatas=metadatas,
        )

        return len(chunks)

    # ========== 检索 ==========

    def retrieve(self, query: str, top_k: int = None) -> list[dict]:
        """向量检索"""
        if top_k is None:
            top_k = settings.retrieval_top_k

        query_embedding = self.embeddings.encode(query, show_progress_bar=False).tolist()

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        documents = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                score = results["distances"][0][i] if results.get("distances") else 0
                # 相似度阈值过滤
                if score < settings.similarity_threshold:
                    continue
                documents.append({
                    "id": doc_id,
                    "content": results["documents"][0][i] if results.get("documents") else "",
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "score": score,
                })

        return documents

    def retrieve_with_bm25(self, query: str, top_k: int = None) -> list[dict]:
        """混合检索：向量 + BM25 加权"""
        vector_results = self.retrieve(query, top_k)
        # BM25 暂用简单实现（后续可用 rank-bm25 替换）
        # 目前先返回向量检索结果
        return vector_results

    # ========== 问答 ==========

    def answer(self, question: str, context_docs: list[dict]) -> str:
        """基于检索结果生成回答"""
        if not context_docs:
            return "未找到相关文档，无法回答此问题。"

        context_text = "\n\n---\n\n".join([
            f"[来源: {doc['metadata'].get('source', 'unknown')}]\n{doc['content']}"
            for doc in context_docs[:settings.rerank_top_k]
        ])

        prompt = f"""你是一个企业知识库助手。请根据以下检索到的文档内容回答用户问题。

规则：
1. 只依据提供的文档内容回答
2. 如果找不到相关信息，明确说"未在文档中找到相关信息"
3. 不要编造或推测
4. 答案末尾标注引用的来源文件

检索到的文档：
{context_text}

用户问题：{question}

请用中文回答：
"""
        return self.llm.chat([
            {"role": "system", "content": "你是企业知识库助手，只依据检索到的文档回答。不确定就说不知道。"},
            {"role": "user", "content": prompt}
        ])

    # ========== 工具方法 ==========

    def collection_count(self) -> int:
        """向量库中的文档数量"""
        return self.collection.count()

    def clear_collection(self):
        """清空向量库"""
        self.chroma_client.delete_collection(settings.chroma_collection_name)
        self.collection = self.chroma_client.get_or_create_collection(
            name=settings.chroma_collection_name,
        )
