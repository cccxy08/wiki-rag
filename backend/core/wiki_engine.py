"""Wiki engine - structured knowledge management (LLM Wiki pattern)
Based on IMPACT-MAP design spec and Karpathy LLM Wiki pattern.
"""
import os
import re
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List

from core.config import settings
from core.llm_provider import get_llm, LLMProvider


class WikiEngine:
    """Wiki engine core"""

    def __init__(self):
        self.paths = settings.get_wiki_paths()
        self.llm = get_llm()
        self._ensure_dirs()
        self._ensure_base_files()
        self._page_cache = {}

    # ==================== Dirs & Files ====================

    def _ensure_dirs(self):
        for key in ["raw", "pages"]:
            self.paths[key].mkdir(parents=True, exist_ok=True)
        (self.paths["raw"] / "assets").mkdir(exist_ok=True)

    def _ensure_base_files(self):
        if not self.paths["index"].exists():
            self.paths["index"].write_text("# Wiki index\n\n> Auto-maintained\n\n", encoding="utf-8")
        if not self.paths["log"].exists():
            self.paths["log"].write_text("# Operation log\n\n> Chronological\n\n", encoding="utf-8")
        # backlinks.json
        bl_path = self.paths["data"] / "backlinks.json"
        if not bl_path.exists():
            bl_path.write_text("{}", encoding="utf-8")

    @property
    def _backlinks_path(self) -> Path:
        return self.paths["data"] / "backlinks.json"

    def _get_schema(self) -> str:
        sp = self.paths["data"] / "WIKI-SCHEMA.md"
        return sp.read_text(encoding="utf-8") if sp.exists() else ""

    # ==================== Core: Query (LLM-driven page selection) ====================

    def query(self, question: str, top_k: int = 5) -> dict:
        """
        Karpathy LLM Wiki query pattern per IMPACT-MAP:
        1. Read index.md to find relevant pages (_find_related_pages via LLM)
        2. Read those pages
        3. LLM synthesizes answer (_answer_from_wiki)

        Returns: {"hit": bool, "answer": str, "sources": [str]}
        """
        all_pages = self._list_pages()
        if not all_pages:
            return {"hit": False, "answer": "", "sources": []}

        # Step 1: LLM selects relevant pages from index
        selected = self._find_related_pages(question, top_k)
        if not selected:
            return {"hit": False, "answer": "", "sources": []}

        # Step 2: Read selected pages
        pages_content = {}
        sources = []
        for title in selected:
            content = self.read_page(title)
            if content:
                pages_content[title] = content
                sources.append(title)

        if not pages_content:
            return {"hit": False, "answer": "", "sources": sources}

        # Step 3: LLM synthesizes answer
        answer = self._answer_from_wiki(question, pages_content)
        return {"hit": True, "answer": answer, "sources": sources}

    def _find_related_pages(self, question: str, top_k: int = 5) -> list[str]:
        """LLM reads the index and selects relevant page titles."""
        index_content = self.get_index()

        # Build a compact page list with first-line summaries
        page_list_lines = []
        for fp in sorted(self._list_pages(), key=lambda f: f.stem):
            try:
                first_line = fp.read_text(encoding="utf-8").split("\n", 1)[0].lstrip("# ")[:100]
            except Exception:
                first_line = ""
            page_list_lines.append(f"- {fp.stem}: {first_line}")
        page_list = "\n".join(page_list_lines)

        prompt = f"""你是一个知识库导航助手。根据用户问题，从以下 Wiki 页面列表中选择最相关的页面。
只返回页面名称，每行一个，最多{top_k}个。不要返回其他内容。

Wiki 页面列表：
{page_list}

用户问题：{question}

相关页面："""

        try:
            raw = self.llm.chat([
                {"role": "system", "content": "你只返回相关页面名称，每行一个，不要其他内容。"},
                {"role": "user", "content": prompt}
            ])
            titles = []
            for line in raw.strip().split("\n"):
                t = line.strip().lstrip("- *0123456789. #（）()")
                if t:
                    titles.append(t)
            return titles[:top_k]
        except Exception:
            # Fallback: return all page names
            return [fp.stem for fp in self._list_pages()[:top_k]]

    def _answer_from_wiki(self, question: str, pages: dict[str, str]) -> str:
        """LLM synthesizes an answer from wiki page contents."""
        context_parts = []
        for title, content in pages.items():
            if len(content) > 3000:
                content = content[:3000] + "\n...(内容过长已截断)"
            context_parts.append(f"## {title}\n{content}")

        prompt = f"""根据以下 Wiki 页面内容回答用户问题。

规则：
1. 只依据提供的 Wiki 内容回答
2. 如果信息不完整，如实说明
3. 标注引用的页面名称

Wiki 内容：
{"\n\n---\n\n".join(context_parts)}

用户问题：{question}

请用中文回答："""

        try:
            return self.llm.chat([
                {"role": "system", "content": "你是企业知识库助手，只依据提供的 Wiki 内容回答。不确定就说不知道。"},
                {"role": "user", "content": prompt}
            ])
        except Exception:
            return "系统繁忙，请稍后重试。"

    # ==================== Core: Ingest (LLM generates wiki pages) ====================

    def ingest(self, content, source_name):
        """Ingest raw content into wiki. Per IMPACT-MAP:
        1. LLM generates wiki page (_generate_wiki_page or _generate_wiki_page_small)
        2. Clean LLM output (_clean_llm_output)
        3. Auto-link cross-references (_auto_link)
        4. Write page
        5. Update backlinks
        6. Update index
        7. Append log
        """
        from core.llm_provider import detect_model_tier

        schema = self._get_schema()
        tier = detect_model_tier(getattr(self.llm, 'model_name', ''))

        # Step 1: Generate wiki page (small model uses step-by-step fallback)
        if tier == "small":
            wiki_page = self._generate_wiki_page_small(content, source_name, schema)
        else:
            wiki_page = self._generate_wiki_page(content, source_name, schema)

        if not wiki_page or not wiki_page.strip():
            return {"wiki_pages": [], "log_entry": "", "error": "Generation failed"}

        # Step 2: Clean LLM output
        wiki_page = self._clean_llm_output(wiki_page)

        # Step 3: Auto-link cross-references
        wiki_page = self._auto_link(wiki_page)

        title = self._extract_title(wiki_page) or source_name.replace(".md", "")
        fn = self._safe_filename(title) + ".md"
        p = self.paths["pages"] / fn
        p.write_text(wiki_page, encoding="utf-8")
        self._page_cache[title] = wiki_page

        # Update backlinks
        modified = self._update_backlinks_for_page(title, wiki_page)

        # Update index
        self._update_index(title, fn, source_name)

        # Log
        extra = f" (updated {len(modified)})" if modified else ""
        log = self._append_log("ingest", f"Imported {source_name} -> {title}{extra}")
        return {"wiki_pages": [fn], "modified_pages": modified, "log_entry": log}

    def _generate_wiki_page(self, content: str, source_name: str, schema: str = "") -> str:
        """LLM generates a structured wiki page from raw content."""
        schema_context = f"""Wiki 格式规范：
{schema[:2000]}
""" if schema else ""

        prompt = f"""{schema_context}请将以下原始内容整理为一篇结构化的 Wiki 页面。

要求：
1. 使用 frontmatter（--- 包裹的 YAML）标注 title、type、created、updated、sources、tags
2. 标题使用 H1（#），章节使用 H2（##）
3. 使用 [[页面名]] 格式做交叉引用
4. 保留所有关键信息，不要编造
5. 末尾添加 ## 参见 章节列出相关页面

原始内容：
{content[:5000]}

来源：{source_name}

请输出完整的 Wiki 页面："""

        try:
            return self.llm.chat([
                {"role": "system", "content": "你是 Wiki 编辑助手，输出结构化的 Markdown Wiki 页面。"},
                {"role": "user", "content": prompt}
            ])
        except Exception:
            # Fallback: simple markdown conversion
            return f"""---
title: {source_name.replace('.md', '')}
type: source-summary
created: {datetime.now().strftime('%Y-%m-%d')}
sources: [{source_name}]
---

# {source_name.replace('.md', '')}

{content}
"""

    def _extract_title(self, wiki_page: str) -> Optional[str]:
        """Extract title from frontmatter or H1 heading."""
        # Try frontmatter
        m = re.search(r"^---\s*\ntitle:\s*(.+?)\s*\n", wiki_page, re.MULTILINE)
        if m:
            return m.group(1).strip()
        # Try H1
        m = re.search(r"^#\s+(.+?)$", wiki_page, re.MULTILINE)
        if m:
            return m.group(1).strip()
        return None

    # ==================== Auto-link & Clean ====================

    def _clean_llm_output(self, raw: str) -> str:
        """Filter LLM verbose prefixes/suffixes, code-block wrappers, and whitespace.

        Called after _generate_wiki_page / _generate_wiki_page_small to ensure
        clean Markdown enters the wiki store.
        """
        if not raw:
            return raw

        # 1. Remove common Chinese LLM prefixes
        prefixes = [
            r'^(好的|没问题|以下是|这是您需要的|根据您的要求|好的，以下是)[^。\n]*[。：:\n]',
            r'^(当然|可以的|明白了)[^。\n]*[。：:\n]',
            r'^(Sure|OK|Here is)[^.]*\.[ \n]',
        ]
        for pat in prefixes:
            raw = re.sub(pat, '', raw, flags=re.IGNORECASE)

        # 2. Remove markdown code block wrappers (```markdown ... ```)
        raw = re.sub(r'^```(?:markdown|md|wiki)?\s*\n', '', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\n```\s*$', '', raw)

        # 3. Strip leading/trailing whitespace and blank lines
        raw = raw.strip()
        raw = re.sub(r'\n{3,}', '\n\n', raw)

        return raw

    def _auto_link(self, wiki_page: str) -> str:
        """Auto-add [[...]] cross-references to known page titles in content.

        Per IMPACT-MAP: called after _generate_wiki_page() return to
        automatically complete cross-references.

        Strategy:
        - Get all known page titles, sorted by length desc (longest first)
        - For each title found in body text (outside code blocks / existing links):
          wrap it as [[title]]
        - Skip titles already inside [[...]] or markdown links [text](url)
        - Skip the page's own title (don't self-link)
        """
        known_titles = [fp.stem for fp in self._list_pages()]
        if not known_titles:
            return wiki_page

        # Sort by length descending so longer titles match first
        known_titles.sort(key=len, reverse=True)

        # Extract this page's own title to avoid self-linking
        own_title = self._extract_title(wiki_page)

        # Split into frontmatter + body (only auto-link body)
        parts = wiki_page.split('---', 2)
        if len(parts) >= 3:
            frontmatter = parts[0] + '---' + parts[1] + '---'
            body = parts[2]
        else:
            frontmatter = ''
            body = wiki_page

        # Find code blocks and existing links — protect them
        protected = []

        def protect(m):
            protected.append(m.group(0))
            return f'\x00PROTECT{len(protected)-1}\x00'

        body = re.sub(r'```[\s\S]*?```', protect, body)           # code blocks
        body = re.sub(r'`[^`]+`', protect, body)                  # inline code
        body = re.sub(r'\[\[.+?\]\]', protect, body)              # existing [[...]]
        body = re.sub(r'\[([^\]]+)\]\([^\)]+\)', protect, body)   # markdown links [text](url)

        for title in known_titles:
            if title == own_title:
                continue
            if len(title) < 2:  # skip single-char titles
                continue
            # Only replace if title appears as a standalone word/phrase
            # Use word boundary matching but handle Chinese (no word boundaries in regex)
            pattern = re.escape(title)
            # For Chinese+ASCII mixed titles, use lookahead/lookbehind for boundaries
            replacement = f'[[{title}]]'
            # Replace only if NOT already inside a [[...]] (handled by protect above)
            # Use negative lookbehind for '[' and negative lookahead for ']' to avoid
            # matching substrings of longer titles already wrapped
            body = re.sub(
                rf'(?<!\[\[)(?<!\[){pattern}(?!\]\])(?!\])',
                replacement,
                body
            )

        # Restore protected blocks
        for i, block in enumerate(protected):
            body = body.replace(f'\x00PROTECT{i}\x00', block)

        return frontmatter + body

    def _generate_wiki_page_small(self, content: str, source_name: str, schema: str = "") -> str:
        """Multi-step wiki page generation for small models (fallback).

        When the LLM is too small to generate a full wiki page in one pass,
        this method breaks it into three steps:
        1. Extract title + frontmatter
        2. Generate body sections
        3. Add cross-references + 参见
        """
        schema_context = f"Wiki 格式规范：\n{schema[:1500]}\n" if schema else ""

        # Step 1: Title + frontmatter
        step1_prompt = f"""{schema_context}从以下内容中提取标题，生成 frontmatter。

原始内容：
{content[:3000]}

请输出 frontmatter（--- 包裹的 YAML），包含 title、type、created、sources、tags。
不要输出其他内容。"""
        try:
            frontmatter = self.llm.chat([
                {"role": "system", "content": "你只输出 YAML frontmatter，不要其他内容。"},
                {"role": "user", "content": step1_prompt}
            ])
        except Exception:
            frontmatter = f"---\ntitle: {source_name.replace('.md', '')}\ntype: source-summary\ncreated: {datetime.now().strftime('%Y-%m-%d')}\nsources: [{source_name}]\n---"

        frontmatter = self._clean_llm_output(frontmatter)
        if not frontmatter.startswith('---'):
            frontmatter = f"---\ntitle: {source_name.replace('.md', '')}\ntype: source-summary\ncreated: {datetime.now().strftime('%Y-%m-%d')}\nsources: [{source_name}]\n---"

        # Step 2: Body sections
        step2_prompt = f"""将以下内容整理为结构化的 Wiki 正文。使用 ## 章节标题分节，保留所有关键信息。

规则：
1. 开头用 # 标题（一级标题）
2. 章节用 ## 标题
3. 使用 [[页面名]] 格式做交叉引用
4. 不要编造信息

原始内容：
{content[:5000]}

请输出正文（Markdown）："""
        try:
            body = self.llm.chat([
                {"role": "system", "content": "你是 Wiki 编辑助手，输出结构化的 Markdown 正文。"},
                {"role": "user", "content": step2_prompt}
            ])
        except Exception:
            body = f"# {source_name.replace('.md', '')}\n\n{content}"

        body = self._clean_llm_output(body)

        # Step 3: Cross-references + 参见
        existing_titles = [fp.stem for fp in self._list_pages()]
        step3_prompt = f"""为以下 Wiki 页面末尾添加「参见」章节，列出相关的交叉引用页面。

已知 Wiki 页面：{', '.join(existing_titles[:30])}

页面正文（末尾部分）：
{body[-2000:]}

请在末尾添加 ## 参见 章节（如果还不存在），列出最多 5 个相关页面，使用 [[页面名]] 格式。"""
        try:
            see_also = self.llm.chat([
                {"role": "system", "content": "你只输出 ## 参见 章节内容，不要其他。"},
                {"role": "user", "content": step3_prompt}
            ])
        except Exception:
            see_also = ""

        see_also = self._clean_llm_output(see_also)
        if see_also and '## 参见' not in body:
            body = body.rstrip() + '\n\n' + see_also

        return frontmatter + '\n\n' + body

    # ==================== Backlinks ====================

    def _get_backlinks_data(self) -> dict:
        """Read backlinks.json, return {page: {incoming: [...], outgoing: [...]}}."""
        try:
            return json.loads(self._backlinks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_backlinks_data(self, data: dict):
        """Write backlinks.json."""
        self._backlinks_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def get_backlinks(self, page_name: str) -> dict:
        """Get incoming/outgoing backlinks for a page.
        Returns: {"incoming": [str], "outgoing": [str]}
        """
        data = self._get_backlinks_data()
        return data.get(page_name, {"incoming": [], "outgoing": []})

    def _update_backlinks_for_page(self, title: str, content: str) -> list[str]:
        """Scan [[...]] refs in content, update backlinks.json.
        Returns: list of page names that were modified.
        """
        # Find all [[...]] refs in content
        refs = re.findall(r"\[\[(.+?)\]\]", content)
        refs = list(set(refs))  # deduplicate

        data = self._get_backlinks_data()
        modified = []

        # Ensure this page entry exists
        if title not in data:
            data[title] = {"incoming": [], "outgoing": []}

        # Update outgoing for this page
        old_outgoing = set(data[title].get("outgoing", []))
        new_outgoing = set(refs)
        if old_outgoing != new_outgoing:
            data[title]["outgoing"] = sorted(new_outgoing)
            modified.append(title)

        # Update incoming for referenced pages
        for ref in refs:
            if ref not in data:
                data[ref] = {"incoming": [], "outgoing": []}
            incoming = set(data[ref].get("incoming", []))
            incoming.add(title)
            data[ref]["incoming"] = sorted(incoming)

        # Remove stale incoming links (pages this page no longer references)
        removed = old_outgoing - new_outgoing
        for ref in removed:
            if ref in data:
                incoming = set(data[ref].get("incoming", []))
                incoming.discard(title)
                data[ref]["incoming"] = sorted(incoming)

        self._save_backlinks_data(data)
        return modified

    # ==================== Read / List ====================

    def _list_pages(self) -> list[Path]:
        """List all wiki page files (excluding index.md and log.md)."""
        return [f for f in self.paths["pages"].glob("*.md")
                if f.name not in ("index.md", "log.md")]

    def page_count(self) -> int:
        return len(self._list_pages())

    def get_index(self) -> str:
        """Return wiki index.md content."""
        p = self.paths["index"]
        if p.exists():
            return p.read_text(encoding="utf-8")
        # Fallback: auto-generate
        pages = sorted(self._list_pages())
        lines = ["# Wiki index\n", "> Auto-generated\n"]
        for fp in pages:
            title = fp.stem
            lines.append(f"- [{title}](./{fp.name}) | {title} | | {title}")
        return "\n".join(lines)

    def read_page(self, title: str) -> Optional[str]:
        """Read wiki page by title, returns Markdown or None."""
        if title in self._page_cache:
            return self._page_cache[title]
        # Exact filename match
        safe = self._safe_filename(title)
        p = self.paths["pages"] / f"{safe}.md"
        if p.exists():
            content = p.read_text(encoding="utf-8")
            self._page_cache[title] = content
            return content
        # Fuzzy match
        for f in self.paths["pages"].glob("*.md"):
            if f.stem == safe or f.stem.lower() == title.lower():
                content = f.read_text(encoding="utf-8")
                self._page_cache[title] = content
                return content
        return None

    # ==================== Lint (Health Check) ====================

    def lint(self) -> list:
        """Wiki health check. Returns [{type, pages, description, severity}]."""
        issues = []
        all_pages = {f.stem: f for f in self._list_pages()}

        # Read index.md references
        index_path = self.paths["index"]
        index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        indexed = set()
        for line in index_text.split("\n"):
            if "](" in line:
                m = re.search(r"\(\.?/?(.+?\.md)\)", line)
                if m:
                    indexed.add(m.group(1).replace(".md", ""))

        # Orphan pages
        for name in all_pages:
            if name not in indexed and len(all_pages) > 1:
                issues.append({
                    "type": "orphan",
                    "pages": [name],
                    "description": f"页面「{name}」未被索引",
                    "severity": "warning"
                })

        # Broken cross-references
        for name, fp in all_pages.items():
            content = fp.read_text(encoding="utf-8")
            content_clean = re.sub(r"```[\s\S]*?```", "", content)
            content_clean = re.sub(r"`[^`]+`", "", content_clean)
            refs = re.findall(r"\[\[(.+?)\]\]", content_clean)
            for ref in refs:
                if ref not in all_pages:
                    issues.append({
                        "type": "missing_crossref",
                        "pages": [name, ref],
                        "description": f"「{name}」引用了不存在的页面「{ref}」",
                        "severity": "error"
                    })

        # Expired pages (frontmatter valid_until)
        for name, fp in all_pages.items():
            content = fp.read_text(encoding="utf-8")
            m = re.search(r"valid_until:\s*(\d{4}-\d{2}-\d{2})", content)
            if m:
                try:
                    deadline = datetime.strptime(m.group(1), "%Y-%m-%d")
                    if deadline < datetime.now():
                        issues.append({
                            "type": "expired",
                            "pages": [name],
                            "description": f"页面「{name}」有效期已过 ({m.group(1)})",
                            "severity": "warning"
                        })
                except ValueError:
                    pass

        return issues

    # ==================== Helpers ====================

    def _safe_filename(self, name: str) -> str:
        return re.sub(r'[\\/*?:"<>|]', "_", name).strip()

    def _update_index(self, title, fn, source_name):
        """Update index.md with new page entry."""
        p = self.paths["index"]
        current = p.read_text(encoding="utf-8") if p.exists() else ""
        entry = f"- [{title}](./{fn}) | {title} | | {source_name}"
        if entry not in current:
            p.write_text(current.rstrip() + "\n" + entry + "\n", encoding="utf-8")

    def _append_log(self, action, detail):
        """Append operation to log.md."""
        p = self.paths["log"]
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"## [{ts}] {action}\n{detail}\n\n"
        current = p.read_text(encoding="utf-8") if p.exists() else ""
        p.write_text(current + entry, encoding="utf-8")
        return f"[{ts}] {action}: {detail}"

    # Backward compat alias
    _log = _append_log

    # Stub placeholders (to be implemented per IMPACT-MAP)
    def _analyze_impact(self, content, source_name):
        """TODO: Analyze which existing pages are affected by new content."""
        return []

    def _update_pages(self, content, source_name, affected):
        """TODO: Update affected pages when new content contradicts or extends them."""
        return []
