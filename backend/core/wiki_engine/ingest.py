"""WikiEngine 摄入 Mixin — LLM 生成 Wiki 页面、清理、自动链接、去重合并、影响分析"""
from __future__ import annotations
import re
import time
from datetime import datetime
from typing import Optional

from core.prompts import load


class WikiIngestMixin:
    def ingest(self, content, source_name):
        from core.llm_provider import detect_model_tier

        schema = self._get_schema()
        tier = detect_model_tier(getattr(self.llm, 'model_name', ''))

        if tier == "small":
            wiki_pages = self._generate_wiki_page_small(content, source_name, schema)
        else:
            wiki_pages = self._generate_wiki_page(content, source_name, schema)

        if not wiki_pages:
            return {"wiki_pages": [], "log_entry": "", "error": "Generation failed"}

        all_fns = []
        all_modified = []
        log_entries = []

        for wiki_page in wiki_pages:
            if not wiki_page or not wiki_page.strip():
                continue

            wiki_page = self._clean_llm_output(wiki_page)
            wiki_page = self._auto_link(wiki_page)

            title = self._extract_title(wiki_page) or source_name.replace(".md", "")
            fn = self._safe_filename(title) + ".md"
            p = self.paths["pages"] / fn

            matched_title = self._dedup_detect(title)
            if matched_title and matched_title != title:
                existing_fn = self._safe_filename(matched_title) + ".md"
                existing_p = self.paths["pages"] / existing_fn
                if existing_p.exists():
                    old_content = existing_p.read_text(encoding="utf-8")
                    merged = self._merge_pages(matched_title, old_content, title, wiki_page, source_name)
                    if merged:
                        wiki_page = merged
                        title = matched_title
                        fn = existing_fn
                        p = existing_p
                        self._append_log("merge", f"Merged {title} with new content from {source_name}")
                        self._update_backlinks_for_page(title, wiki_page)
                        all_fns.append(fn)
                        log_entries.append(f"{title}(merged)")
                        p.write_text(wiki_page, encoding="utf-8")
                        self._page_cache[title] = wiki_page
                        self._sync_tags_from_page(wiki_page)
                        self._update_index(title, fn, source_name)
                        all_modified.append(fn)
                        continue

            p.write_text(wiki_page, encoding="utf-8")
            self._page_cache[title] = wiki_page
            self._sync_tags_from_page(wiki_page)

            modified = self._update_backlinks_for_page(title, wiki_page)
            all_modified.extend(modified)

            self._update_index(title, fn, source_name)
            all_fns.append(fn)
            log_entries.append(title)

        affected = self._analyze_impact(content, source_name)
        if affected:
            updated = self._update_pages(content, source_name, affected)
            if updated:
                all_modified = list(set(all_modified + updated))

        auto_created = self._autocreate_linked_pages(all_fns)
        if auto_created:
            all_fns.extend(auto_created)
            all_modified = list(set(all_modified + auto_created))

        extra = f" (updated {len(all_modified)})" if all_modified else ""
        titles_str = ", ".join(log_entries)
        log = self._append_log("ingest", f"Imported {source_name} -> {titles_str}{extra}")
        return {"wiki_pages": all_fns, "modified_pages": all_modified, "log_entry": log}

    def _generate_wiki_page(self, content: str, source_name: str, schema: str = "") -> list[str]:
        schema_context = f"""Wiki 格式规范：\n{schema[:2000]}\n""" if schema else ""

        index_context = ""
        try:
            index_text = self.paths["index"].read_text(encoding="utf-8")[:2000]
            if index_text.strip():
                index_context = f"\n已有 Wiki 页面列表（供交叉引用参考）：\n{index_text}\n"
        except Exception:
            pass

        tags_context = self._format_tags_context()

        prompt = load("wiki_ingest.txt",
            schema_context=schema_context,
            index_context=index_context,
            tags_context=tags_context,
            content=content[:5000],
            source_name=source_name,
        )

        try:
            raw_output = self.llm.chat([
                {"role": "system", "content": "你是 Wiki 编辑助手，输出结构化的 Markdown Wiki 页面。可能输出多个页面，用 ---NEWPAGE--- 分隔。"},
                {"role": "user", "content": prompt}
            ], label="ingest")
            if "---NEWPAGE---" in raw_output:
                pages = [p.strip() for p in raw_output.split("---NEWPAGE---")]
            else:
                pages = [raw_output.strip()]
            return [p for p in pages if p]
        except Exception:
            return [f"""---
title: {source_name.replace('.md', '')}
type: source-summary
created: {datetime.now().strftime('%Y-%m-%d')}
sources: [{source_name}]
---

# {source_name.replace('.md', '')}

{content}
"""]

    def _generate_wiki_page_small(self, content: str, source_name: str, schema: str = "") -> list[str]:
        schema_context = f"Wiki 格式规范：\n{schema[:1500]}\n" if schema else ""

        step1_prompt = load("wiki_small_step1.txt", schema_context=schema_context, content=content[:3000])
        try:
            frontmatter = self.llm.chat([
                {"role": "system", "content": "你只输出 YAML frontmatter，不要其他内容。"},
                {"role": "user", "content": step1_prompt}
            ], label="ingest")
        except Exception:
            frontmatter = f"---\ntitle: {source_name.replace('.md', '')}\ntype: source-summary\ncreated: {datetime.now().strftime('%Y-%m-%d')}\nsources: [{source_name}]\n---"

        frontmatter = self._clean_llm_output(frontmatter)
        if not frontmatter.startswith('---'):
            frontmatter = f"---\ntitle: {source_name.replace('.md', '')}\ntype: source-summary\ncreated: {datetime.now().strftime('%Y-%m-%d')}\nsources: [{source_name}]\n---"

        step2_prompt = load("wiki_small_step2.txt", content=content[:5000])
        try:
            body = self.llm.chat([
                {"role": "system", "content": "你是 Wiki 编辑助手，输出结构化的 Markdown 正文。"},
                {"role": "user", "content": step2_prompt}
            ], label="ingest")
        except Exception:
            body = f"# {source_name.replace('.md', '')}\n\n{content}"

        body = self._clean_llm_output(body)

        existing_titles = [fp.stem for fp in self._list_pages()]
        step3_prompt = load("wiki_small_step3.txt",
            existing_titles=', '.join(existing_titles[:30]),
            body_tail=body[-2000:],
        )
        try:
            see_also = self.llm.chat([
                {"role": "system", "content": "你只输出 ## 参见 章节内容，不要其他。"},
                {"role": "user", "content": step3_prompt}
            ], label="ingest")
        except Exception:
            see_also = ""

        see_also = self._clean_llm_output(see_also)
        if see_also and '## 参见' not in body:
            body = body.rstrip() + '\n\n' + see_also

        return [frontmatter + '\n\n' + body]

    def _extract_title(self, wiki_page: str) -> Optional[str]:
        m = re.search(r"^---\s*\ntitle:\s*(.+?)\s*\n", wiki_page, re.MULTILINE)
        if m:
            return m.group(1).strip()
        m = re.search(r"^#\s+(.+?)$", wiki_page, re.MULTILINE)
        if m:
            return m.group(1).strip()
        return None

    def _clean_llm_output(self, raw: str) -> str:
        if not raw:
            return raw

        prefixes = [
            r'^(好的|没问题|以下是|这是您需要的|根据您的要求|好的，以下是)[^。\n]*[。：:\n]',
            r'^(当然|可以的|明白了)[^。\n]*[。：:\n]',
            r'^(Sure|OK|Here is)[^.]*\.[ \n]',
        ]
        for pat in prefixes:
            raw = re.sub(pat, '', raw, flags=re.IGNORECASE)

        raw = re.sub(r'^```(?:markdown|md|wiki|yaml)?\s*\n', '', raw, flags=re.IGNORECASE)
        raw = re.sub(r'\n```\s*$', '', raw)

        raw = raw.strip()
        raw = re.sub(r'\n{3,}', '\n\n', raw)

        return raw

    def _auto_link(self, wiki_page: str) -> str:
        known_titles = [fp.stem for fp in self._list_pages()]
        if not known_titles:
            return wiki_page

        known_titles.sort(key=len, reverse=True)
        own_title = self._extract_title(wiki_page)

        parts = wiki_page.split('---', 2)
        if len(parts) >= 3:
            frontmatter = parts[0] + '---' + parts[1] + '---'
            body = parts[2]
        else:
            frontmatter = ''
            body = wiki_page

        protected = []

        def protect(m):
            protected.append(m.group(0))
            return f'\x00PROTECT{len(protected)-1}\x00'

        body = re.sub(r'```[\s\S]*?```', protect, body)
        body = re.sub(r'`[^`]+`', protect, body)
        body = re.sub(r'\[\[.+?\]\]', protect, body)
        body = re.sub(r'\[([^\]]+)\]\([^\)]+\)', protect, body)

        for title in known_titles:
            if title == own_title:
                continue
            if len(title) < 2:
                continue
            escaped = re.escape(title)
            has_cjk = bool(re.search(r'[\u4e00-\u9fff]', title))
            if has_cjk:
                boundary_l = r'(?<![\u4e00-\u9fffA-Za-z0-9])'
                boundary_r = r'(?![\u4e00-\u9fffA-Za-z0-9])'
            else:
                boundary_l = r'(?<![A-Za-z0-9_])'
                boundary_r = r'(?![A-Za-z0-9_])'
            replacement = f'[[{title}]]'
            body = re.sub(boundary_l + escaped + boundary_r, replacement, body)

        for i, block in enumerate(protected):
            body = body.replace(f'\x00PROTECT{i}\x00', block)

        return frontmatter + body

    def _dedup_detect(self, title: str) -> Optional[str]:
        if not title:
            return None

        norm = title.lower().strip()
        norm = re.sub(r"[（(].*?[）)]", "", norm)
        norm = norm.replace('有限公司', '').replace('公司', '')
        norm = norm.replace('v', '').replace('version', '')
        norm = norm.replace(' ', '').replace('-', '').replace('_', '')
        norm = norm.replace('[', '').replace(']', '').lstrip('[')

        if not norm:
            return None

        existing_pages = [fp.stem for fp in self._list_pages()]
        best_match = None
        best_score = 0.0

        for stem in existing_pages:
            stem_norm = stem.lower().strip()
            stem_norm = re.sub(r"[（(].*?[）)]", "", stem_norm)
            stem_norm = stem_norm.replace('有限公司', '').replace('公司', '')
            stem_norm = stem_norm.replace('v', '').replace('version', '')
            stem_norm = stem_norm.replace(' ', '').replace('-', '').replace('_', '')
            stem_norm = stem_norm.replace('[', '').replace(']', '').lstrip('[')

            if not stem_norm:
                continue

            set1 = set(norm)
            set2 = set(stem_norm)
            intersection = len(set1 & set2)
            union = len(set1 | set2)
            score = intersection / union if union > 0 else 0

            if norm in stem_norm or stem_norm in norm:
                score = max(score, 0.8)

            if len(norm) >= 4 and len(stem_norm) >= 4:
                if norm[:4] in stem_norm or stem_norm[:4] in norm:
                    score = max(score, 0.75)

            if score > best_score:
                best_score = score
                best_match = stem

        if best_score >= 0.6:
            return best_match
        return None

    def _merge_pages(self, old_title, old_content, new_title, new_content, source_name):
        old_sources = source_name
        m = __import__("re").search(r"sources:\s*\[(.+?)\]", old_content)
        if m:
            old_sources = m.group(1)

        prompt = load("wiki_merge.txt",
            old_sources=old_sources,
            old_page=old_content,
            new_source=source_name,
            new_page=new_content,
        )

        try:
            merged = self.llm.chat([
                {"role": "system", "content": "你是 Wiki 编辑助手。合并两个同主题的页面，保留所有信息。"},
                {"role": "user", "content": prompt}
            ], label="ingest")

            if not merged or not merged.strip():
                return None

            merged = self._clean_llm_output(merged)

            if not merged.startswith('---'):
                merged = f"---\ntitle: {old_title}\ntype: merged\nsources: [{old_sources}, {source_name}]\n---\n\n{merged}"

            return merged
        except Exception:
            return None

    def _analyze_impact(self, content, source_name):
        if not content:
            return []

        affected = []
        existing_titles = set()
        for fp in self._list_pages():
            existing_titles.add(fp.stem)

        for stem in existing_titles:
            if len(stem) >= 2 and stem in content:
                affected.append(stem)

        return affected

    def _update_pages(self, content, source_name, affected):
        if not affected:
            return []

        modified = []

        for page_title in affected:
            fn = self._safe_filename(page_title) + ".md"
            p = self.paths["pages"] / fn

            if not p.exists():
                continue

            old_content = p.read_text(encoding="utf-8")

            update_prompt = (
                f"现有 Wiki 页面标题：{page_title}\n\n"
                f"现有页面内容：\n{old_content[:3000]}\n\n"
                f"新来源 ({source_name}) 的内容：\n{content[:3000]}\n\n"
                "请判断新内容是否包含现有页面中不存在的重要信息，或与现有页面矛盾。\n"
                "如果有，请输出**完整的更新后的 Wiki 页面**（必须包含 frontmatter，以 --- 开头）。\n"
                "如果没有，请只输出：NO_UPDATE"
            )

            try:
                result = self.llm.chat([
                    {"role": "system", "content": "你是 Wiki 编辑助手。判断是否需要更新现有页面。如果更新，输出完整的 Wiki 页面内容，以 --- 开头。"},
                    {"role": "user", "content": update_prompt}
                ], label="ingest")

                if result and "NO_UPDATE" not in result:
                    result = self._clean_llm_output(result)

                    result_lines = result.split("\n")
                    fm_start = -1
                    for j, rl in enumerate(result_lines):
                        if rl.strip() == "---":
                            fm_start = j
                            break

                    if fm_start >= 0:
                        result = "\n".join(result_lines[fm_start:])
                    else:
                        continue

                    result = result.strip()
                    title_ok = False
                    for rl in result.split("\n"):
                        if rl.strip().startswith("title:"):
                            title_ok = True
                            break
                    if not title_ok:
                        continue

                    p.write_text(result, encoding="utf-8")
                    self._page_cache[page_title] = result
                    self._update_backlinks_for_page(page_title, result)
                    modified.append(fn)
                    self._append_log("update", f"Updated {page_title} from {source_name}")
            except Exception:
                continue

        return modified

    def _autocreate_linked_pages(self, source_pages: list[str]) -> list[str]:
        new_pages = []
        links_to_check = []
        for fn in source_pages:
            p = self.paths["pages"] / fn
            if not p.exists():
                continue
            try:
                clean = p.read_text(encoding="utf-8")
            except Exception:
                continue
            clean = re.sub(r"```[\s\S]*?```", "", clean)
            clean = re.sub(r"`[^`]+`", "", clean)
            found = re.findall(r"\[\[(.+?)\]\]", clean)
            for link in found:
                safe = self._safe_filename(link)
                target = self.paths["pages"] / f"{safe}.md"
                if not target.exists() and link not in links_to_check:
                    links_to_check.append(link)

        if not links_to_check:
            return []

        for link_title in links_to_check:
            safe = self._safe_filename(link_title)
            target = self.paths["pages"] / f"{safe}.md"

            context_parts = []
            for fn in source_pages:
                p = self.paths["pages"] / fn
                if p.exists():
                    try:
                        text = p.read_text(encoding="utf-8")
                        context_parts.append(f"## {fn}\n{text[:2000]}")
                    except Exception:
                        pass

            if not context_parts:
                continue

            context_str = "\n\n---\n\n".join(context_parts)

            prompt = load("wiki_autocreate.txt",
                link_title=link_title,
                created_date=datetime.now().strftime('%Y-%m-%d'),
                context_str=context_str,
            )
            try:
                raw = self.llm.chat([
                    {"role": "system", "content": "你是 Wiki 编辑助手，只基于提供的引用内容生成页面。如果引用中没有实质性信息，回复 EMPTY_PAGE。"},
                    {"role": "user", "content": prompt}
                ], label="ingest")
                raw = raw.strip()
                if raw.upper().startswith("EMPTY_PAGE") or len(raw) < 20:
                    continue

                page_content = self._clean_llm_output(raw)
                target.write_text(page_content, encoding="utf-8")
                self._page_cache[link_title] = page_content

                self._update_backlinks_for_page(link_title, page_content)

                fn = f"{safe}.md"
                self._update_index(link_title, fn, "auto-created")
                new_pages.append(fn)
                self._append_log("autocreate", f"Created page {link_title} from [[link]] in {', '.join(source_pages)}")
            except Exception:
                continue

        return new_pages