"""知识库管理路由。"""

from fastapi import APIRouter, Request

from ..models import KnowledgeAddRequest, KnowledgeSearchRequest

router = APIRouter(prefix="/knowledge", tags=["知识库"])


@router.get("/stats", summary="知识库统计")
async def knowledge_stats(req: Request):
    """获取知识库统计信息。"""
    kb = req.app.state.knowledge_base
    kb.initialize()
    return kb.get_stats()


@router.get("/categories", summary="知识分类列表")
async def list_categories(req: Request):
    """列出所有知识分类。"""
    kb = req.app.state.knowledge_base
    kb.initialize()
    return {"categories": kb.list_categories()}


@router.post("/search", summary="知识检索")
async def search_knowledge(request: KnowledgeSearchRequest, req: Request):
    """检索知识库。"""
    kb = req.app.state.knowledge_base
    results = kb.search(request.query, top_k=request.top_k, category=request.category)
    return {"query": request.query, "results": results, "total": len(results)}


@router.post("/add", summary="添加知识文档")
async def add_knowledge(request: KnowledgeAddRequest, req: Request):
    """添加单篇知识文档。"""
    kb = req.app.state.knowledge_base
    count = kb.add_document(
        title=request.title,
        content=request.content,
        source=request.source,
        category=request.category,
    )
    return {"message": f"成功添加{count}个文档块", "chunks": count}


@router.post("/add-batch", summary="批量添加知识文档")
async def add_knowledge_batch(documents: list[dict], req: Request):
    """批量添加知识文档。"""
    kb = req.app.state.knowledge_base
    count = kb.add_documents_batch(documents)
    return {"message": f"成功添加{count}个文档块", "chunks": count}


@router.delete("/clear", summary="清空知识库")
async def clear_knowledge(req: Request):
    """清空知识库（仅清空用户添加的内容，内置知识不受影响）。"""
    kb = req.app.state.knowledge_base
    kb.clear()
    kb.initialize()
    return {"message": "知识库已重置"}
