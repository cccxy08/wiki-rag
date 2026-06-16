"""Wiki 路由"""
import re
from fastapi import APIRouter, HTTPException
from schemas.schemas import IndexResponse, IndexEntry, WikiPageResponse, LintRequest, LintResponse, LintIssue
from api.deps import _get_wiki_engine

router = APIRouter(prefix="/api", tags=["wiki"])


@router.get("/wiki/index", response_model=IndexResponse)
def wiki_index():
    wiki_engine = _get_wiki_engine()
    index_text = wiki_engine.get_index()
    entries = []
    for line in index_text.split("\n"):
        line = line.strip()
        if line.startswith("- ["):
            title_part = line[3:].split("](")[0] if "](" in line else line[3:].split("]")[0]
            entries.append(IndexEntry(title=title_part, file="", summary=title_part[:60], updated=""))

    return IndexResponse(categories={"全部": entries}, total_pages=len(entries))


@router.get("/wiki/page/{title:path}", response_model=WikiPageResponse)
def wiki_page(title: str):
    wiki_engine = _get_wiki_engine()
    content = wiki_engine.read_page(title)
    if content is None:
        raise HTTPException(404, f"Wiki 页面不存在: {title}")

    cross_refs = re.findall(r"\[\[(.+?)\]\]", content)
    return WikiPageResponse(title=title, content=content, cross_refs=list(set(cross_refs)))


@router.post("/wiki/lint", response_model=LintResponse)
def wiki_lint(req: LintRequest = LintRequest()):
    wiki_engine = _get_wiki_engine()
    issues_raw = wiki_engine.lint()

    issues = []
    for raw in issues_raw:
        issues.append(LintIssue(
            type=raw["type"], pages=raw["pages"],
            description=raw["description"], severity=raw.get("severity", "warning"),
        ))

    return LintResponse(status="completed", issues=issues, scanned_pages=wiki_engine.page_count())


@router.get("/wiki/page/{title:path}/versions")
def wiki_page_versions(title: str):
    wiki_engine = _get_wiki_engine()
    versions = wiki_engine.list_versions(title)
    return {"title": title, "versions": versions}


@router.get("/wiki/page/{title:path}/versions/{version_filename}")
def wiki_page_version_content(title: str, version_filename: str):
    wiki_engine = _get_wiki_engine()
    content = wiki_engine.get_version_content(title, version_filename)
    if content is None:
        raise HTTPException(404, f"Version not found: {version_filename}")
    return {"title": title, "version": version_filename, "content": content}


@router.post("/wiki/page/{title:path}/versions/{version_filename}/restore")
def wiki_page_restore_version(title: str, version_filename: str):
    wiki_engine = _get_wiki_engine()
    success = wiki_engine.restore_version(title, version_filename)
    if not success:
        raise HTTPException(400, f"Failed to restore version: {version_filename}")
    return {"title": title, "restored_from": version_filename, "status": "success"}