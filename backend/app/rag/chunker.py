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


def _heading_of(block: str) -> str | None:
    """从一段文本里找出标题行，找不到返回 None。

    为什么不能直接 `is_heading(block)`：

    讲义 / Word / Markdown 最常见的排法是**空行分段**，于是一个 block 往往是
    「一、中心理解题\\n总原则：先看问题……」这种"标题 + 整段正文"的多行文本。
    `is_heading` 看的是整段，多行必然判 False，结果 chapters 一直是空的，
    全文 chapter 都落到兜底的「正文」上——章节元数据整条链路形同没有。

    所以这里退一步看 block 的**首行**：首行像标题、且 block 确实不止一行时，
    就认它是标题（block 本身仍然整段进正文，标题不会丢）。
    """
    if is_heading(block):
        return block
    first_line, sep, _rest = block.partition("\n")
    if sep and is_heading(first_line.strip()):
        return first_line.strip()
    return None


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
            heading = _heading_of(block)
            if heading is not None:
                # 标题既更新章节，**也要保留在正文里**。
                #
                # 这一点踩过坑：最初标题只写进 chapter 元数据、不进 chunk 正文，
                # 结果像「十、细节判断题」这种只出现在标题里的说法，正文里
                # 一个字都没有，用户搜「细节判断题」永远命中不了。
                # 标题是最强的检索信号，必须让它进正文。
                #
                # 这里**只记当前所在小节**，不再拼多层路径（原来是"取最近 3 个
                # 标题 join"）。原因是块级标题分不出"父子"还是"兄弟"，拼出来
                # 的层级是编的：拿一份真实简历 PDF 实测，同级的
                # 「教育经历 / 专业技能 / 项目经历」被拼成了
                # 「专业技能 > 项目经历 > Compose」这种假层级，
                # 出处反而比只给一个准确的小节名更不可信。
                # 与其编一个推不出来的层级，不如老实给当前小节。
                chapters = [heading[:60]]

                # 换章节时先把累积的内容收尾。
                #
                # 原先只在「buf 为空」时才写 buf_chapter，而默认 overlap=80
                # 时 flush() 之后 buf 永远不空（:122 会把尾巴留下），于是
                # buf_chapter 在第一个标题之后就**再也不会更新**：整份讲义的
                # 每个片段都标着第一章的标题。表现为"引用出处张冠李戴"——
                # 用户看到的 chapter 和片段正文对不上，而这个字段正是
                # README 承诺的"保留章节/页码"。
                if buf.strip():
                    flush()

            if not buf:
                buf_page = page.page_no
                buf_chapter = " > ".join(chapters)
            else:
                # 走到这里说明还在同一章节内；若章节路径变了（上面刚 flush 过
                # 的情况除外），也要跟上，避免片段挂着过期章节。
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
            # 和 flush() 用同一套兜底：buf_page 可能因重叠被重置成 None，
            # 那样最后一个片段会丢页码（单页文档实测 page=None）。
            chunks.append(Chunk(text=text, chapter=buf_chapter,
                                page=buf_page if buf_page is not None else last_page,
                                index=len(chunks)))

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
