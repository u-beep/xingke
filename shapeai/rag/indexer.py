"""文档处理流水线 — 清洗、去重、语义分块、入库。"""

import hashlib
import re
import uuid
from typing import Optional

from .vector_store import VectorStore


def _clean_text(text: str) -> str:
    """清洗文本：去除多余空白、HTML标签等。"""
    text = str(text)
    # 去除HTML标签
    text = re.sub(r"<[^>]+>", "", text)
    # 去除多余空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _split_into_chunks(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """将文本按语义分块。

    优先按段落分割，段落过长时按句子分割。
    每块约 chunk_size 字符，相邻块有 overlap 字符重叠。

    Args:
        text: 原始文本
        chunk_size: 目标块大小（字符）
        overlap: 块间重叠（字符）
    Returns:
        文本块列表
    """
    text = text.strip()
    if not text:
        return []

    # 先按段落分割
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return []

    chunks = []
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) <= chunk_size:
            current_chunk += ("\n" if current_chunk else "") + para
        else:
            if current_chunk:
                chunks.append(current_chunk)
            # 段落本身超过chunk_size，按句子分割
            if len(para) > chunk_size:
                sentences = re.split(r"[。！？.!?\n]+", para)
                sentences = [s.strip() for s in sentences if s.strip()]
                for sent in sentences:
                    if len(current_chunk) + len(sent) <= chunk_size:
                        current_chunk += ("\n" if current_chunk else "") + sent
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = sent
            else:
                current_chunk = para

    if current_chunk:
        chunks.append(current_chunk)

    # 添加重叠
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:] if len(chunks[i - 1]) > overlap else chunks[i - 1]
            overlapped.append(prev_tail + " " + chunks[i])
        chunks = overlapped

    return chunks


class DocumentIndexer:
    """文档索引器。

    负责文档的清洗、去重、分块和向量化入库。
    """

    def __init__(self, store: VectorStore):
        self.store = store
        self._hashes: set[str] = set()  # 用于去重

    def index_text(
        self,
        text: str,
        source: str = "",
        category: str = "general",
        chunk_size: int = 500,
        title: str = "",
    ) -> int:
        """索引一段文本。

        Args:
            text: 原始文本
            source: 来源标识（文件名/URL等）
            category: 知识分类
            chunk_size: 分块大小
            title: 文档标题（Milvus 存储用）
        Returns:
            新增的文档块数量
        """
        cleaned = _clean_text(text)
        if not cleaned:
            return 0

        # 内容去重
        content_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
        if content_hash in self._hashes:
            return 0
        self._hashes.add(content_hash)

        # 分块
        chunks = _split_into_chunks(cleaned, chunk_size=chunk_size)
        if not chunks:
            return 0

        # 构建文档并入库
        documents = []
        for i, chunk in enumerate(chunks):
            documents.append({
                "id": str(uuid.uuid4()),
                "title": title,
                "content": chunk,
                "source": source,
                "category": category,
                "chunk_index": i,
                "hash": hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
            })

        self.store.add_documents(documents)
        return len(documents)

    def index_document(
        self,
        title: str,
        content: str,
        source: str = "",
        category: str = "general",
    ) -> int:
        """索引一篇完整文档（带标题）。"""
        full_text = f"{title}\n{content}" if title else content
        return self.index_text(full_text, source=source or title, category=category, title=title)

    def index_batch(self, documents: list[dict]) -> int:
        """批量索引文档。

        Args:
            documents: [{"title", "content", "source", "category"}]
        Returns:
            总新增块数
        """
        total = 0
        for doc in documents:
            total += self.index_document(
                title=doc.get("title", ""),
                content=doc.get("content", ""),
                source=doc.get("source", ""),
                category=doc.get("category", "general"),
            )
        return total

    def clear(self):
        """清空索引。"""
        self.store.clear()
        self._hashes.clear()
