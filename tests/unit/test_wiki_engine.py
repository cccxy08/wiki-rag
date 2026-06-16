"""WikiEngine 单元测试"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).parent.parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestWikiEngineCleanOutput:
    def test_removes_chinese_prefixes(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                result = engine._clean_llm_output("好的，以下是生成的内容\n---\ntitle: 测试")
                assert not result.startswith("好的")
                assert "---" in result

    def test_removes_code_block_wrappers(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                result = engine._clean_llm_output("```markdown\n# Title\n```")
                assert not result.startswith("```")
                assert "# Title" in result

    def test_empty_input(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                assert engine._clean_llm_output("") == ""
                assert engine._clean_llm_output(None) is None


class TestWikiEngineExtractTitle:
    def test_from_frontmatter(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                page = "---\ntitle: 测试页面\n---\n# 内容"
                assert engine._extract_title(page) == "测试页面"

    def test_from_h1(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                page = "# 标题页面\n内容"
                assert engine._extract_title(page) == "标题页面"

    def test_no_title(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                assert engine._extract_title("普通文本") is None


class TestWikiEngineAutoLink:
    def test_auto_links_known_title(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                # 创建一个已知页面
                (tmp_wiki / "wiki" / "测试页面.md").write_text("# 测试页面\n内容", encoding="utf-8")

                page = "---\ntitle: 另一页面\n---\n这里提到测试页面相关内容"
                result = engine._auto_link(page)
                assert "[[测试页面]]" in result

    def test_preserves_code_blocks(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                (tmp_wiki / "wiki" / "测试页面.md").write_text("# 测试页面\n内容", encoding="utf-8")

                page = "---\ntitle: 另一页面\n---\n```\n测试页面\n```\n正文"
                result = engine._auto_link(page)
                # 代码块内的不应被链接
                assert "```" in result


class TestWikiEngineLint:
    def test_detects_orphan_page(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                # 创建一个不在 index 中的页面
                (tmp_wiki / "wiki" / "孤立页面.md").write_text("# 孤立页面\n内容", encoding="utf-8")
                # index 中不引用它

                issues = engine.lint()
                orphan_types = [i["type"] for i in issues]
                assert "orphan" in orphan_types


class TestWikiEngineDedup:
    def test_detects_similar_title(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                (tmp_wiki / "wiki" / "星辰科技.md").write_text("# 星辰科技\n内容", encoding="utf-8")

                result = engine._dedup_detect("星辰科技有限公司")
                assert result is not None

    def test_no_match_returns_none(self, mock_settings, mock_llm, tmp_wiki):
        with patch("core.wiki_engine.get_llm", return_value=mock_llm):
            with patch("core.config.settings", mock_settings):
                from core.wiki_engine import WikiEngine
                WikiEngine._instance = None
                engine = WikiEngine()

                result = engine._dedup_detect("完全不相关的内容")
                assert result is None