"""Pydantic 数据模型"""
from pydantic import BaseModel, Field
from typing import Optional, Literal


# ===== 请求模型 =====

class QueryRequest(BaseModel):
    question: str = Field(..., description="用户问题")
    session_id: Optional[str] = Field(None, description="会话 ID，用于多轮对话")
    top_k: int = Field(5, description="检索返回条数", ge=1, le=20)
    stream: bool = Field(False, description="是否流式输出")
    mode: Literal["auto", "pipeline", "wiki", "rag"] = Field(
        "auto",
        description="查询模式: auto=自动, pipeline=流水线, wiki=Wiki直查, rag=RAG直搜"
    )


class IngestRequest(BaseModel):
    source_name: Optional[str] = Field(None, description="自定义文档名称")
    auto_score: bool = Field(True, description="是否自动评估质量")


class LintRequest(BaseModel):
    full_scan: bool = Field(False, description="是否全量扫描(否则只检最近变更)")


# ===== 响应模型 =====

class SourceInfo(BaseModel):
    file: str = Field(..., description="来源文件名")
    page: Optional[int] = Field(None, description="页码")
    chunk_id: Optional[str] = Field(None, description="切片 ID")


class QueryResponse(BaseModel):
    answer: str = Field(..., description="回答内容")
    source: str = Field(..., description="答案来源: wiki / rag / agent")
    source_pages: list[str] = Field(default_factory=list, description="引用的 Wiki 页面")
    sources: list[SourceInfo] = Field(default_factory=list, description="RAG 来源详情")
    confidence: str = Field("medium", description="置信度: high / medium / low")
    cached: bool = Field(False, description="是否来自缓存")
    ingested_to_wiki: bool = Field(False, description="是否已自动沉淀到 Wiki")
    session_id: Optional[str] = Field(None)
    parsed_question: str = Field("", description="预处理后的查询（清洗/精简）")
    pages_consulted: list[str] = Field(default_factory=list, description="本次查询实际读取的页面名列表")
    precipitation_record_id: Optional[str] = Field(None, description="沉淀记录 ID（如触发知识复利）")


class IngestResponse(BaseModel):
    status: str = Field(..., description="success / partial / failed")
    wiki_pages: list[str] = Field(default_factory=list, description="??? Wiki ??")
    modified_pages: list[str] = Field(default_factory=list, description="?????? Wiki ??")
    log_entry: str = Field("", description="操作日志条目")
    error: Optional[str] = Field(None, description="错误信息")


class IndexEntry(BaseModel):
    title: str
    file: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    updated: str


class IndexResponse(BaseModel):
    categories: dict[str, list[IndexEntry]] = Field(default_factory=dict)
    total_pages: int = 0


class WikiPageResponse(BaseModel):
    title: str
    content: str
    metadata: dict = Field(default_factory=dict)
    cross_refs: list[str] = Field(default_factory=list)


class LintIssue(BaseModel):
    type: Literal["orphan", "contradiction", "stale", "missing_crossref", "expired", "deprecated_stale", "contradiction_marker"]
    pages: list[str]
    description: str
    severity: Literal["warning", "error"] = "warning"


class LintResponse(BaseModel):
    status: str
    issues: list[LintIssue] = Field(default_factory=list)
    scanned_pages: int = 0


class HealthResponse(BaseModel):
    status: str
    llm_provider: str
    llm_model: str
    wiki_pages: int
    vector_count: int
    uptime_seconds: float


# ===== 安全相关模型 =====

class ApiKeyEntry(BaseModel):
    key: str = Field(..., description="API Key 值")
    role: Literal["admin", "user"] = Field("user", description="角色: admin / user")
    description: str = Field("", description="Key 用途说明")


class ErrorResponse(BaseModel):
    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误描述")
    request_id: Optional[str] = Field(None, description="请求 ID")


class CacheStats(BaseModel):
    hits: int = Field(0, description="缓存命中次数")
    misses: int = Field(0, description="缓存未命中次数")
    hit_rate: float = Field(0.0, description="命中率")
    provider: str = Field("memory", description="缓存提供者")
    size: int = Field(0, description="当前缓存条目数")


# ===== 批量导入相关模型 =====

class TaskItemResponse(BaseModel):
    itemId: str = Field(..., description="任务项 ID")
    fileName: str = Field(..., description="文件名")
    fileSize: int = Field(0, description="文件大小(字节)")
    status: str = Field("pending", description="状态: pending/processing/success/partial/failed/skipped")
    retryCount: int = Field(0, description="重试次数")
    durationMs: Optional[int] = Field(None, description="处理耗时(ms)")
    errorMessage: Optional[str] = Field(None, description="错误信息")
    wikiPages: list[str] = Field(default_factory=list, description="生成的 Wiki 页面")
    ragChunks: int = Field(0, description="RAG 切片数")


class TaskStatusResponse(BaseModel):
    taskId: str = Field(..., description="任务 ID")
    sourceType: str = Field("batch_upload", description="来源类型")
    status: str = Field("pending", description="任务状态")
    totalFiles: int = Field(0, description="总文件数")
    successCount: int = Field(0, description="成功数")
    partialCount: int = Field(0, description="部分成功数")
    failedCount: int = Field(0, description="失败数")
    skippedCount: int = Field(0, description="跳过数")
    createdAt: str = Field("", description="创建时间")
    completedAt: Optional[str] = Field(None, description="完成时间")
    items: list[TaskItemResponse] = Field(default_factory=list, description="任务项列表")


class BatchIngestResponse(BaseModel):
    taskId: str = Field(..., description="任务 ID")
    totalFiles: int = Field(0, description="总文件数")
    skippedFiles: int = Field(0, description="跳过文件数")


class TaskSummaryResponse(BaseModel):
    taskId: str = Field(..., description="任务 ID")
    sourceType: str = Field("batch_upload", description="来源类型")
    status: str = Field("pending", description="任务状态")
    totalFiles: int = Field(0, description="总文件数")
    successCount: int = Field(0, description="成功数")
    failedCount: int = Field(0, description="失败数")
    createdAt: str = Field("", description="创建时间")
    completedAt: Optional[str] = Field(None, description="完成时间")


class ImportHistoryResponse(BaseModel):
    tasks: list[TaskSummaryResponse] = Field(default_factory=list, description="任务列表")
    total: int = Field(0, description="总数")
    page: int = Field(1, description="当前页")
    pageSize: int = Field(20, description="每页大小")


# ===== 沉淀审核相关模型 =====

class PrecipitationConfirmRequest(BaseModel):
    action: Literal["confirm", "ignore"] = Field(..., description="确认或忽略")
    question: str = Field("", description="原始问题")
    answer: str = Field("", description="答案内容")
    llmScore: int = Field(0, description="LLM 评分")
    source: str = Field("", description="答案来源")


class PrecipitationReviewRequest(BaseModel):
    action: Literal["approve", "reject", "modify_approve"] = Field(..., description="审核操作")
    reason: Optional[str] = Field(None, description="拒绝原因或修改说明")
    modifiedContent: Optional[str] = Field(None, description="修改后的内容(modify_approve时)")


class PrecipitationRecordResponse(BaseModel):
    recordId: str = Field(..., description="沉淀记录 ID")
    questionHash: str = Field("", description="问题哈希")
    answerSummary: str = Field("", description="答案摘要")
    llmScore: int = Field(0, description="LLM 评分")
    source: str = Field("", description="来源")
    status: str = Field("pending_confirm", description="状态")
    confirmedBy: Optional[str] = Field(None, description="确认人")
    reviewedBy: Optional[str] = Field(None, description="审核人")
    createdAt: str = Field("", description="创建时间")
    wikiPageTitle: Optional[str] = Field(None, description="写入的 Wiki 页面标题")
