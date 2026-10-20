"""从 PDF / DOCX / Markdown / TXT 抽出文本，并在入库前做「可读性闸门」。

## 为什么要有这道闸门

实测过三份真实材料：一份是扫描件（0 字符）、一份字体子集没有 ToUnicode
（抽出来是 `(cid:23680)` 或「岀㚚瘃痱」这种生僻字乱码）、一份正常。
**后者的字符数看着很正常，但对 RAG 来说完全是垃圾**——它会污染向量库，
让检索永远召回一堆看不懂的段落，而且很难排查。

所以入库前必须回答一个问题：**这段文本是人话吗？**

## 怎么判断（不依赖大词典）

真实中文文本里「高频字」的占比很高：的、是、在、有、了、不、和、这、就……
乱码文本几乎一个都没有。用一张两百来字的高频字表算占比，比引入几万字的
常用字表轻得多，而且效果够用：

- 真实教材/笔记：高频字占比通常 35% 以上
- 生僻字乱码：不到 10%
- `(cid:xxx)` 编码：直接看出现次数

阈值定得比较保守（宁可放过也别误杀），误杀一份好材料比放过一份坏材料更麻烦。
"""

from __future__ import annotations

import io
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path


class LoadError(Exception):
    """文档加载失败（格式不支持、抽不出文字、文本是乱码）。"""


# 中文里出现频率最高的一批字，用来估计「这段文本像不像人话」
_COMMON_CHARS = set(
    "的一是在不了有和人这中大为上个国我以要他时来用们生到作地于出就分对成会"
    "可主发年动同工也能下过子说产种面而方后多定行学法所民得经十三之进着等部"
    "度家电力里如水化高自二理起小物现实加量都两体制机当使点从业本去把性好应"
    "开它合还因由其些然前外天政四日那社义事平形相全表间样与关各重新线内数正"
    "心反你明看原又么利比或但质气第向道命此变条只没结解问意建月公无系军很情"
    "者最立代想已通并提直题党程展五果料象员革位入常文总次品式活设及管特件长"
    "求老头基资边流路级少图山统接知较将组见计别她手角期根论运农指几九区强放"
    "决西被干做必战先回则任取据处队南给色光门即保治北造百规热领七海口东导器"
    "压志世金增争济阶油思术极交受联什认六共权收证改清己美再采转更单风切打白"
    "教速花带安场身车例真务具万每目至达走积示议声报斗完类八离华名确才科张信"
    "马节话米整空元况今集温传土许步群广石记需段研界拉林律叫且究观越织装影算"
    "低持音众书布复容儿须际商非验连断深难近矿千周委素技备半办青省列习响约支"
    "般史感劳便团往酸历市克何除消构府称太准精值号率族维划选标写存候毛亲快效"
    "斯院查江型眼王按格养易置派层片始却专状育厂京识适属圆包火住调满县局照参"
    "红细引听该铁价严首底液官德随病苏失尔死讲配女黄推显谈罪神艺呢席含企望密"
    "批营项防举球英氧势告李台落木帮轮破亚师围注远字材排供河态封另施减树溶怎"
    "止案言士均武固叶鱼波视仅费紧爱左章早朝害续轻服试食充兵源判护司足某练差"
    "致板田降黑犯负击范继兴似余坚曲输修故城夫够送笔船占右财吃富春职觉汉画功"
    "巴跟虽杂飞检吸助升阳互初创抗考投坏策古径换未跑留钢曾端责站简述钱副尽帝"
    "射草冲承独令限阿宣环双请超微让控州良轴找否纪益依优顶础载倒房突坐粉敌略"
    "客袁冷胜绝析块剂测丝协诉念陈仍罗盐友洋错苦夜刑移频逐靠混母短皮终聚汽村"
    "云哪既距卫停烈央察烧调础"
)

_CID_RE = re.compile(r"\(cid:\d+\)")
# 页眉页脚常见形态：「第 3/23 页」「- 12 -」「公众号：xxx 资料」
_NOISE_LINE_RE = re.compile(
    r"^\s*(?:第\s*\d+\s*/\s*\d+\s*页|第\s*\d+\s*页|-?\s*\d+\s*-?|"
    r".{0,12}(?:公众号|小红书|抖音|微信)\s*[:：].{0,30})\s*$"
)


@dataclass
class Page:
    page_no: int | None
    text: str


@dataclass
class LoadedDoc:
    pages: list[Page] = field(default_factory=list)
    file_type: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages if p.text)

    @property
    def char_count(self) -> int:
        return len(self.text)


# ============================================================
# 可读性
# ============================================================

def readability(text: str) -> dict:
    """评估文本是否适合入向量库。

    返回 common_ratio（高频字占比）、cid_ratio、以及 ok / suspect / garbage。
    """
    total = len(text)
    if total < 30:
        return {"chars": total, "common_ratio": 0.0, "cid_ratio": 0.0,
                "verdict": "too_short"}

    cid_hits = len(_CID_RE.findall(text))
    cid_ratio = cid_hits * 10 / total

    # 只统计中文字符里的高频字占比——英文文档不该被中文字表误杀
    cjk_chars = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    if len(cjk_chars) < 20:
        return {"chars": total, "common_ratio": 0.0, "cid_ratio": round(cid_ratio, 4),
                "verdict": "no_cjk"}

    common_ratio = sum(1 for ch in cjk_chars if ch in _COMMON_CHARS) / len(cjk_chars)

    if cid_ratio > 0.02 or common_ratio < 0.15:
        verdict = "garbage"
    elif common_ratio < 0.30:
        verdict = "suspect"
    else:
        verdict = "ok"

    return {
        "chars": total,
        "cjk_chars": len(cjk_chars),
        "common_ratio": round(common_ratio, 4),
        "cid_ratio": round(cid_ratio, 4),
        "verdict": verdict,
    }


# ============================================================
# 各格式抽取
# ============================================================

def _load_pdf(content: bytes) -> LoadedDoc:
    """PDF 抽文本：先用 PDFium，抽不出来再退回 pdfminer（pdfplumber）。

    两个引擎对不同字体子集的处理不一样，实测过同样的文件一个能抽一个不能，
    所以两个都试一遍，取抽得多的那个。
    """
    doc = LoadedDoc(file_type="pdf")
    best: list[Page] = []

    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(content)
        try:
            pages = []
            for i in range(len(pdf)):
                page = pdf[i]
                tp = page.get_textpage()
                text = tp.get_text_bounded() or ""
                tp.close()
                page.close()
                pages.append(Page(page_no=i + 1, text=text))
            if sum(len(p.text) for p in pages) > sum(len(p.text) for p in best):
                best = pages
        finally:
            pdf.close()
    except Exception as e:  # noqa: BLE001
        doc.warnings.append(f"PDFium 抽取失败：{e}")

    if not best or sum(len(p.text) for p in best) < 50:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = []
                for i, page in enumerate(pdf.pages):
                    try:
                        text = page.extract_text() or ""
                    except Exception:  # noqa: BLE001
                        text = ""
                    pages.append(Page(page_no=i + 1, text=text))
                if sum(len(p.text) for p in pages) > sum(len(p.text) for p in best):
                    best = pages
        except Exception as e:  # noqa: BLE001
            doc.warnings.append(f"pdfminer 抽取失败：{e}")

    doc.pages = best
    if doc.char_count < 50:
        raise LoadError(
            "这份 PDF 抽不出文字，应该是扫描件（整页是图片）。"
            "需要先做 OCR 才能进知识库。"
        )
    return doc


def _load_docx(content: bytes) -> LoadedDoc:
    doc = LoadedDoc(file_type="docx")
    try:
        from docx import Document
        d = Document(io.BytesIO(content))
    except Exception as e:  # noqa: BLE001
        raise LoadError(f"Word 解析失败：{e}")
    parts = [p.text for p in d.paragraphs]
    doc.pages = [Page(page_no=None, text="\n".join(parts))]
    if doc.char_count < 20:
        raise LoadError("Word 里没有可读文本")
    return doc


def _load_text(content: bytes, file_type: str) -> LoadedDoc:
    doc = LoadedDoc(file_type=file_type)
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise LoadError("文本编码无法识别（试过 utf-8 / gb18030）")
    doc.pages = [Page(page_no=None, text=text)]
    if doc.char_count < 20:
        raise LoadError("文件内容太少")
    return doc


SUPPORTED_EXT = {".pdf": "pdf", ".docx": "docx", ".md": "md",
                 ".markdown": "md", ".txt": "txt"}


def load_document(filename: str, content: bytes) -> LoadedDoc:
    """按扩展名分发解析，并在返回前跑一遍可读性闸门。"""
    if not content:
        raise LoadError("文件是空的")

    ext = Path(filename or "").suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise LoadError(
            f"不支持的文件类型 {ext or '(无扩展名)'}，"
            f"目前支持 {', '.join(sorted(SUPPORTED_EXT))}"
        )

    file_type = SUPPORTED_EXT[ext]
    if file_type == "pdf":
        doc = _load_pdf(content)
    elif file_type == "docx":
        doc = _load_docx(content)
    else:
        doc = _load_text(content, file_type)

    doc.file_type = file_type

    # 逐页过滤页眉页脚这类噪音
    clean_pages = []
    for page in doc.pages:
        lines = [ln for ln in page.text.splitlines() if not _NOISE_LINE_RE.match(ln)]
        clean_pages.append(Page(page_no=page.page_no, text="\n".join(lines)))
    doc.pages = clean_pages

    stat = readability(doc.text)
    if stat["verdict"] == "garbage":
        raise LoadError(
            f"抽出来的文本不像正常中文，已拦截（高频字占比 "
            f"{stat['common_ratio']:.0%}，cid 编码占比 {stat['cid_ratio']:.1%}）。"
            f"这种 PDF 通常是字体子集缺 ToUnicode 映射，需要 OCR 或换文字版材料。"
        )
    if stat["verdict"] == "suspect":
        doc.warnings.append(
            f"文本可读性偏低（高频字占比 {stat['common_ratio']:.0%}），"
            f"入库后检索效果可能不好"
        )

    return doc
