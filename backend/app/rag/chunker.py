"""把抽取出来的正文切成适合检索的片段。

## 三件必须做的事

1. **NFKC 归一化**：真实材料里大量用「康熙部首」和「兼容汉字」编码，
   比如 `阿⾥⽊江` 里的 `⾥` 是 U+2F50（部首），不是 `里` U+91CC。
   人眼看完全一样，但**向量化和检索对不上**——用户搜「阿里木江」永远命中不了。
   NFKC 会把它们统一成标准汉字。

2. **按标题维护章节路径**：检索结果要能告诉用户"这段来自第几章"，
   引用才有说服力；同时 `chapter` 也能当作检索时的元数据过滤条件。

3. **带重叠滑动**：相邻片段保留一小段重叠，避免答案正好被切断在边界上。

## 为什么按「段落聚合」而不是按固定字数硬切

硬切会把一句话劈成两半，检索出来读不通。先按空行/标题拆成自然段，
再把自然段往目标长度上拼，能最大程度保住语义完整。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.rag.loader import Page

# 目标片段长度（中文字符）。400~600 是中文 RAG 的常见区间：
# 太短上下文不足，太长向量会被稀释、检索精度下降。
DEFAULT_TARGET = 500
DEFAULT_OVERLAP = 80
MIN_CHUNK_CHARS = 80

_HEADING_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百]+[章节讲部分]"),
    re.compile(r"^[一二三四五六七八九十]+[、.．]"),
    re.compile(r"^[（(][一二三四五六七八九十]+[）)]"),
    re.compile(r"^\d+(\.\d+)*[、.．]\s*\S"),
    re.compile(r"^【[^】]{1,20}】"),
    re.compile(r"^[A-Za-z][、.．]\s*\S"),
]
_SENTENCE_END = "。！？；：.!?;:）)】"


@dataclass
class Chunk:
    text: str
    chapter: str
    page: int | None
    index: int

    @property
    def char_count(self) -> int:
        return len(self.text)


def normalize(text: str) -> str:
    """统一字符形态：NFKC + 去零宽字符 + 统一换行。"""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 全角空格 -> 半角，连续空格压成一个
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def is_heading(line: str) -> bool:
    """判断一行是不是小标题。

    除了正则匹配常见的编号形态，还要兜住「短行 + 不以句末标点结尾」这种
    笔记里很常见的手写标题（比如「中心理解题」「关联词的套用」）。
    """
    s = line.strip()
    if not s or len(s) > 40:
        return False
    if any(p.match(s) for p in _HEADING_PATTERNS):
        return True
    # 短行且没有句末标点 -> 大概率是标题
    return len(s) <= 20 and s[-1] not in _SENTENCE_END


def _split_paragraphs(page_text: str) -> list[str]:
    """把一页拆成自然段（空行分隔；没有空行就按行）。"""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", page_text) if b.strip()]
    if len(blocks) <= 1:
        # 没有空行的材料（很多笔记都是这样）按单行切开再聚合
        blocks = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
    return blocks


def chunk_pages(
    pages: list[Page],
    target: int = DEFAULT_TARGET,
    overlap: int = DEFAULT_OVERLAP,
    min_chars: int = MIN_CHUNK_CHARS,
) -> list[Chunk]:
    """把整篇文档切成片段。"""
    target = max(120, target)
    overlap = max(0, min(overlap, target // 2))

    chapters: list[str] = []
    chunks: list[Chunk] = []
    buf = ""
    buf_page: int | None = None
    buf_chapter = ""
    last_page: int | None = None

    def flush() -> None:
        nonlocal buf, buf_page, buf_chapter
        text = buf.strip()
        if text:
            # 重叠会把上一段的尾巴带进新一段，此时 buf_page 可能已经被重置成 None，
            # 所以退化到「上一个处理过的页码」，避免片段丢失页码信息。
            page_for_chunk = buf_page if buf_page is not None else last_page
            chunks.append(Chunk(text=text, chapter=buf_chapter,
                                page=page_for_chunk, index=len(chunks)))
            buf = text[-overlap:] if overlap else ""
        else:
            buf = ""
        buf_page = None

    for page in pages:
        text = normalize(page.text)
        if not text:
            continue
        if page.page_no is not None:
            last_page = page.page_no

        for block in _split_paragraphs(text):
            if is_heading(block):
                # 标题既更新章节路径，**也要保留在正文里**。
                #
                # 这一点踩过坑：最初标题只写进 chapter 元数据、不进 chunk 正文，
                # 结果像「十、细节判断题」这种只出现在标题里的说法，正文里
                # 一个字都没有，用户搜「细节判断题」永远命中不了。
                # 标题是最强的检索信号，必须让它进正文。
                if len(chapters) >= 3:
                    chapters.pop(0)
                chapters.append(block[:60])

            if not buf:
                buf_page = page.page_no
                buf_chapter = " > ".join(chapters)
            elif not buf_chapter:
                buf_chapter = " > ".join(chapters)

            buf = (buf + "\n" + block) if buf else block

            while len(buf) >= target * 1.8:
                # 单段太长：按句号粗略切开，避免一个 chunk 顶别人五个
                cut = buf.rfind("。", target, target * 2)
                if cut == -1:
                    cut = target
                else:
                    cut += 1
                head, tail = buf[:cut], buf[cut:]
                buf = head
                flush()
                buf = (buf + "\n" + tail).strip() if buf else tail
                buf_page = buf_page or page.page_no

            if len(buf) >= target:
                flush()

    if buf.strip():
        text = buf.strip()
        if text:
            chunks.append(Chunk(text=text, chapter=buf_chapter,
                                page=buf_page, index=len(chunks)))

    # 合并过短的尾片段，避免出现「半句话」的 chunk
    merged: list[Chunk] = []
    for c in chunks:
        if merged and c.char_count < min_chars:
            prev = merged[-1]
            prev.text = (prev.text + "\n" + c.text).strip()
        else:
            merged.append(c)

    for i, c in enumerate(merged):
        c.index = i
        if not c.chapter:
            c.chapter = "正文"

    return merged
