"""向量检索服务 — 语义检索 + 关键词混合检索 + 重排序。"""

from typing import Optional

from .vector_store import VectorStore


class KnowledgeRetriever:
    """知识检索器。

    提供混合检索策略：语义检索 + 关键词检索，结果重排序。
    """

    def __init__(self, store: VectorStore):
        self.store = store

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        min_score: float = 0.01,
    ) -> list[dict]:
        """混合检索相关知识。

        Args:
            query: 查询文本
            top_k: 返回前K条
            category: 按分类过滤
            min_score: 最低相似度阈值
        Returns:
            检索结果列表
        """
        # 语义检索（TF-IDF余弦相似度）
        semantic_results = self.store.search(query, top_k=top_k * 2, category=category)

        # 关键词检索
        keyword_results = self.store.keyword_search(query, top_k=top_k * 2, category=category)

        # 合并去重 + 重排序
        merged = self._merge_and_rerank(semantic_results, keyword_results, top_k)

        # 过滤低分结果
        return [r for r in merged if r["score"] >= min_score]

    @staticmethod
    def _merge_and_rerank(semantic: list[dict], keyword: list[dict], top_k: int) -> list[dict]:
        """合并两路检索结果并重排序。"""
        merged: dict[str, dict] = {}

        # 语义检索结果权重 0.6
        for r in semantic:
            doc_id = r["id"]
            if doc_id not in merged:
                merged[doc_id] = dict(r)
                merged[doc_id]["score"] = r["score"] * 0.6
                merged[doc_id]["match_types"] = ["semantic"]
            else:
                merged[doc_id]["score"] += r["score"] * 0.6
                merged[doc_id]["match_types"].append("semantic")

        # 关键词检索结果权重 0.4
        for r in keyword:
            doc_id = r["id"]
            if doc_id not in merged:
                merged[doc_id] = dict(r)
                merged[doc_id]["score"] = r["score"] * 0.4
                merged[doc_id]["match_types"] = ["keyword"]
            else:
                merged[doc_id]["score"] += r["score"] * 0.4
                merged[doc_id]["match_types"].append("keyword")

        # 排序
        results = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def retrieve_with_context(self, query: str, top_k: int = 3, category: str | None = None) -> str:
        """检索并格式化为可注入 prompt 的上下文文本。"""
        results = self.retrieve(query, top_k=top_k, category=category)
        if not results:
            return ""

        lines = ["Knowledge (from RAG):"]
        for r in results:
            source = r.get("source", "")
            content = r.get("content", "")[:300]
            score = r.get("score", 0)
            lines.append(f"- [{source}] (score: {score:.2f}) {content}")
        return "\n".join(lines)
