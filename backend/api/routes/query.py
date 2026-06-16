"""查询路由"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from schemas.schemas import QueryRequest, QueryResponse, SourceInfo
from api.deps import _get_query_service

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    query_service = _get_query_service()
    mode = req.mode if hasattr(req, "mode") else "pipeline"
    if req.stream:
        raise HTTPException(400, "流式输出请使用 /api/query/stream")

    result = query_service.query_with_mode(req.question, mode, req.top_k)

    source_info = []
    for s in result.get("sources", []):
        source_info.append(SourceInfo(
            file=s.get("file", "unknown"),
            page=s.get("page"),
            chunk_id=s.get("chunk_id"),
        ))

    return QueryResponse(
        answer=result["answer"],
        source=result["source"],
        source_pages=result.get("source_pages", []),
        sources=source_info,
        confidence=result.get("confidence", "medium"),
        cached=result.get("cached", False),
        session_id=req.session_id,
        parsed_question=result.get("parsed_question") or "",
        pages_consulted=result.get("pages_consulted") or [],
        precipitation_record_id=result.get("precipitation_record_id"),
    )


@router.post("/query/stream")
def query_stream(req: QueryRequest):
    query_service = _get_query_service()
    mode = req.mode if hasattr(req, "mode") else "pipeline"
    result = query_service.query_with_mode(req.question, mode, req.top_k)
    answer = result["answer"]

    async def generate():
        for i in range(0, len(answer), 5):
            yield answer[i:i+5]
            import asyncio
            await asyncio.sleep(0.02)

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")