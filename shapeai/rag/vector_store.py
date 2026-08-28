"""向量存储 — Milvus + 内存 TF-IDF 双模式。

数据库可用时使用 Milvus 进行专业向量检索，
不可用时回退到内存 TF-IDF + 余弦相似度。

Milvus 集合 schema:
  id (INT64, auto_id)    — 主键
  title (VARCHAR 512)    — 文档标题
  content (VARCHAR 65k)  — 文档内容
  source (VARCHAR 256)   — 来源
  category (VARCHAR 64)  — 分类
  embedding (FLOAT_VECTOR 1536) — 向量

向量化方案:
  使用 TF-IDF + 特征哈希(Hashing Trick)将文本映射到 1536 维固定向量。
  不依赖外部 Embedding 模型/API，纯本地 numpy 实现。
  1. 中文+英文分词
  2. 统计 TF (词频)
  3. 用 IDF 加权 (从已有文档集合计算)
  4. 特征哈希映射到固定维度
  5. L2 归一化
"""

import math
import re
import hashlib
import logging
from collections import Counter
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ─── 分词 ───


def _tokenize(text: str) -> list[str]:
    """中文+英文分词。

    中文按单字分词，英文按单词分词。
    """
    tokens = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", str(text).lower())
    return tokens


# ─── 特征哈希向量 ───


def _hash_token(token: str, dim: int) -> int:
    """将 token 哈希到 [0, dim) 范围。"""
    h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
    return h % dim


def _build_tfidf_hash_vector(
    text: str,
    idf: dict[str, float],
    dim: int = 1536,
) -> np.ndarray:
    """用 TF-IDF + 特征哈希构建固定维度向量。

    1. 分词
    2. 统计 TF
    3. 用 IDF 加权
    4. 哈希到固定维度
    5. L2 归一化
    """
    tokens = _tokenize(text)
    if not tokens:
        return np.zeros(dim, dtype=np.float32)

    vector = np.zeros(dim, dtype=np.float32)
    tf = Counter(tokens)
    for token, count in tf.items():
        weight = count * idf.get(token, 1.0)
        idx = _hash_token(token, dim)
        vector[idx] += weight

    # L2 归一化
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector /= norm
    return vector


# ─── 内存模式 TF-IDF ───


def _build_tfidf_vector(text: str, vocab: dict[str, int]) -> np.ndarray:
    """构建TF-IDF向量（内存回退用，按词表维度）。"""
    tokens = _tokenize(text)
    if not tokens:
        return np.zeros(len(vocab))

    tf = Counter(tokens)
    vector = np.zeros(len(vocab))
    for token, count in tf.items():
        if token in vocab:
            vector[vocab[token]] = count
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector /= norm
    return vector


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算余弦相似度。"""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class VectorStore:
    """向量存储 — Milvus 优先，内存回退。

    管理文档向量，支持插入、检索和删除。
    Milvus 模式下使用 TF-IDF + 特征哈希生成 1536 维向量并存储到 Milvus，
    同时保留内存副本用于关键词检索和 TF-IDF 回退。
    """

    def __init__(self, dim: int = 1536):
        self._documents: list[dict] = []
        self._vectors: list[np.ndarray] = []
        self._vocab: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        self._is_indexed = False
        self._dim = dim

        self._db_mode = False
        self._collection = None
        try:
            from ..database import get_milvus
            from ..config import MILVUS_COLLECTION
            get_milvus()
            from pymilvus import utility
            if utility.has_collection(MILVUS_COLLECTION):
                from pymilvus import Collection
                self._collection = Collection(MILVUS_COLLECTION)
                self._collection.load()
                self._db_mode = True
                logger.info("VectorStore 使用 Milvus 模式: %s", MILVUS_COLLECTION)
            else:
                logger.warning("Milvus 连接成功但集合 '%s' 不存在，回退内存模式", MILVUS_COLLECTION)
        except Exception as exc:
            logger.warning("VectorStore 回退到内存模式: %s", exc)

    # ─── IDF 计算 ───

    def _compute_idf(self) -> dict[str, float]:
        """从当前文档集合计算 IDF。"""
        if not self._documents:
            return {}
        doc_count = len(self._documents)
        doc_freq: dict[str, int] = {}
        for doc in self._documents:
            tokens = set(_tokenize(doc.get("content", "")))
            for token in tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1
        idf = {}
        for token, df in doc_freq.items():
            idf[token] = math.log((doc_count + 1) / (df + 1)) + 1
        return idf

    # ─── 文档管理 ───

    def add_documents(self, documents: list[dict]) -> int:
        """添加文档到存储。"""
        if self._db_mode:
            return self._add_documents_milvus(documents)

        # 内存模式
        for doc in documents:
            self._documents.append(doc)
        self._is_indexed = False
        return len(documents)

    def _add_documents_milvus(self, documents: list[dict]) -> int:
        """Milvus 模式插入文档。

        使用 TF-IDF + 特征哈希生成真实向量，不再用零向量占位。
        """
        if not documents:
            return 0

        try:
            # 先将文档加入内存副本（用于 IDF 计算和关键词检索）
            for doc in documents:
                self._documents.append(doc)

            # 计算当前全部文档的 IDF
            idf = self._compute_idf()

            # 为新文档生成向量
            titles = []
            contents = []
            sources = []
            categories = []
            embeddings = []

            for doc in documents:
                title = doc.get("title", "")
                content = doc.get("content", "")
                source = doc.get("source", "")
                category = doc.get("category", "user")

                # 合并标题和内容作为向量化的文本
                vec_text = f"{title}\n{content}" if title else content
                vec = _build_tfidf_hash_vector(vec_text, idf, dim=self._dim)

                titles.append(title)
                contents.append(content)
                sources.append(source)
                categories.append(category)
                embeddings.append(vec.tolist())

            self._collection.insert([
                titles, contents, sources, categories, embeddings,
            ])
            self._collection.flush()

            self._is_indexed = False  # 触发内存索引重建

            logger.info("Milvus 插入 %d 篇文档 (真实 TF-IDF 向量)", len(documents))
            return len(documents)
        except Exception as exc:
            logger.error("Milvus 插入失败，回退内存: %s", exc)
            self._is_indexed = False
            return len(documents)

    def clear(self):
        """清空存储。"""
        if self._db_mode:
            try:
                from ..config import MILVUS_COLLECTION
                from pymilvus import utility
                utility.drop_collection(MILVUS_COLLECTION)
                # 重新创建
                from ..migrate import migrate_milvus
                migrate_milvus()
                from pymilvus import Collection
                self._collection = Collection(MILVUS_COLLECTION)
                self._collection.load()
            except Exception as exc:
                logger.error("Milvus 清空失败: %s", exc)

        self._documents = []
        self._vectors = []
        self._vocab = {}
        self._idf = {}
        self._is_indexed = False

    def _build_index(self):
        """构建TF-IDF索引（内存回退用）。"""
        if not self._documents:
            return

        all_tokens = set()
        doc_token_lists = []
        for doc in self._documents:
            tokens = _tokenize(doc.get("content", ""))
            doc_token_lists.append(tokens)
            all_tokens.update(tokens)

        self._vocab = {token: idx for idx, token in enumerate(sorted(all_tokens))}

        doc_count = len(self._documents)
        for token in all_tokens:
            df = sum(1 for tokens in doc_token_lists if token in tokens)
            self._idf[token] = math.log((doc_count + 1) / (df + 1)) + 1

        self._vectors = []
        for doc, tokens in zip(self._documents, doc_token_lists):
            vector = np.zeros(len(self._vocab))
            tf = Counter(tokens)
            for token, count in tf.items():
                if token in self._vocab:
                    vector[self._vocab[token]] = count * self._idf.get(token, 1.0)
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector /= norm
            self._vectors.append(vector)

        self._is_indexed = True

    # ─── 检索 ───

    def search(self, query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        """检索最相关的文档。

        Milvus 模式优先使用 Milvus 向量检索；
        如果 Milvus 检索失败或无结果，回退到内存 TF-IDF 检索。
        """
        # Milvus 模式：尝试向量检索
        if self._db_mode and self._collection is not None:
            try:
                results = self._search_milvus(query, top_k, category)
                if results:
                    return results
                logger.debug("Milvus 检索无结果，回退内存 TF-IDF")
            except Exception as exc:
                logger.warning("Milvus 检索失败，回退内存: %s", exc)

        # 内存 TF-IDF 检索
        return self._search_memory(query, top_k, category)

    def _search_milvus(self, query: str, top_k: int, category: str | None = None) -> list[dict]:
        """Milvus 向量检索。"""
        # 用当前 IDF 生成查询向量
        if not self._idf:
            self._idf = self._compute_idf()
        query_vector = _build_tfidf_hash_vector(query, self._idf, dim=self._dim)

        # 构建搜索参数
        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        # 构建过滤表达式
        expr = None
        if category:
            expr = f'category == "{category}"'

        results = self._collection.search(
            data=[query_vector.tolist()],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["title", "content", "source", "category"],
        )

        hits = []
        for hit in results[0]:
            entity = hit.entity
            # 兼容不同 pymilvus 版本的 entity 访问方式
            if hasattr(entity, 'to_dict'):
                ent_dict = entity.to_dict().get('fields', entity.to_dict())
            elif isinstance(entity, dict):
                ent_dict = entity
            else:
                ent_dict = {}
                for field in ['title', 'content', 'source', 'category']:
                    try:
                        ent_dict[field] = getattr(entity, field, '')
                    except Exception:
                        ent_dict[field] = ''
            hits.append({
                "id": str(hit.id),
                "title": ent_dict.get("title", ""),
                "content": ent_dict.get("content", ""),
                "source": ent_dict.get("source", ""),
                "category": ent_dict.get("category", ""),
                "score": round(hit.score, 4),
            })
        return hits

    def _search_memory(self, query: str, top_k: int, category: str | None = None) -> list[dict]:
        """内存 TF-IDF 检索。"""
        if not self._documents:
            return []

        if not self._is_indexed:
            self._build_index()

        query_vector = _build_tfidf_vector(query, self._vocab)

        results = []
        for idx, (doc, vec) in enumerate(zip(self._documents, self._vectors)):
            if category and doc.get("category") != category:
                continue
            score = _cosine_similarity(query_vector, vec)
            if score > 0:
                results.append({
                    "id": doc.get("id", str(idx)),
                    "title": doc.get("title", ""),
                    "content": doc.get("content", ""),
                    "source": doc.get("source", ""),
                    "category": doc.get("category", ""),
                    "score": round(score, 4),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def keyword_search(self, query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        """关键词检索（BM25风格简化版）。"""
        if not self._documents:
            return []

        query_tokens = set(_tokenize(query))
        if not query_tokens:
            return []

        results = []
        for idx, doc in enumerate(self._documents):
            if category and doc.get("category") != category:
                continue
            doc_tokens = set(_tokenize(doc.get("content", "")))
            overlap = len(query_tokens & doc_tokens)
            if overlap == 0:
                continue
            coverage = overlap / len(query_tokens)
            results.append({
                "id": doc.get("id", str(idx)),
                "content": doc.get("content", ""),
                "source": doc.get("source", ""),
                "category": doc.get("category", ""),
                "score": round(coverage, 4),
                "match_type": "keyword",
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    @property
    def document_count(self) -> int:
        """已存储的文档数量。"""
        return len(self._documents)

    def get_existing_titles(self, titles: list[str]) -> set[str]:
        """查询给定标题中已存在的集合(用于启动时去重,避免重复插入)。"""
        if not titles:
            return set()
        if not self._db_mode:
            existing = {d.get("title", "") for d in self._documents}
            return existing & set(titles)
        try:
            quoted = ", ".join(f'"{t}"' for t in titles)
            results = self._collection.query(
                expr=f"title in [{quoted}]",
                output_fields=["title"],
            )
            return {r.get("title", "") for r in (results or [])}
        except Exception as exc:
            logger.warning("查询已有文档标题失败(将全部跳过查重): %s", str(exc)[:200])
            return set(titles)  # 查询失败时保守跳过插入,防止无限膨胀

    def get_stats(self) -> dict:
        """获取存储统计信息。"""
        categories = {}
        for doc in self._documents:
            cat = doc.get("category", "uncategorized")
            categories[cat] = categories.get(cat, 0) + 1

        # Milvus 模式下统计集合中的行数
        milvus_count = None
        if self._db_mode and self._collection is not None:
            try:
                self._collection.flush()
                milvus_count = self._collection.num_entities
            except Exception:
                pass

        return {
            "total_documents": len(self._documents),
            "milvus_entities": milvus_count,
            "vocab_size": len(self._vocab),
            "is_indexed": self._is_indexed,
            "by_category": categories,
            "milvus_mode": self._db_mode,
            "vector_dim": self._dim,
            "vector_method": "tf-idf + hashing trick",
        }
