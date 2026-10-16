"""批量导入题目的解析器。

支持格式：JSON / Excel(.xlsx) / Word(.docx) / PDF
最终统一成 list[dict]：
    {
      "stem": str,
      "question_type": str,         # single / multiple / judge / blank / short / calc
      "options": list[str],         # blank / short / calc 为空数组
      "correct_answer": str,        # single/judge 是 "A"；multiple 是 "AB"；blank/short/calc 是文本
      "explanation": str
    }

## 容错设计（v2）

v1 的问题是「全有或全无」：任何一行不合格就 `raise ImportError`，
整个文件 422 失败，用户只知道"导入失败"，不知道是哪一行错了，
只能把几百道题的文件重新改一遍再传。

v2 改成「逐行校验 + 部分成功」：

1. **行级隔离**：单行解析失败只记一条 issue，其余行照常入库；
2. **结构化错误清单**：每条 issue 带 `location`（第几行/第几题）和 `reason`，
   接口可以原样回给前端，让用户只改坏行；
3. **整文件级重试 + 退避**：PDF/Word 抽取偶发失败时重试，避免一次抖动全盘失败；
4. **PDF 逐页降级**：整篇抽取失败时按页重试，坏页跳过并记录，不拖垮整个文件；
5. **文件内去重**：同题干+同选项的重复题只保留第一条，记为 warning。

`parse_file()` 保留 v1 的「遇错即抛」语义，`parse_file_report()` 返回完整报告，
接口层用后者。
"""

from __future__ import annotations

import io
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from docx import Document
from openpyxl import load_workbook
import pdfplumber


class ImportError(Exception):
    """文件级致命错误（格式不支持、文件损坏、一条都没解析出来）。"""


LETTERS = "ABCDEFGH"
VALID_TYPES = {"single", "multiple", "judge", "blank", "short", "calc"}


# ============================================================
# 解析报告
# ============================================================

@dataclass
class ParseIssue:
    """一条行级问题。"""
    location: str          # "第 12 行" / "第 3 题" / "第 2 条"
    reason: str
    severity: str = "error"  # error：该行被跳过；warning：已自动修正/去重
    raw: str = ""            # 原始内容片段，方便用户定位

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "reason": self.reason,
            "severity": self.severity,
            "raw": self.raw[:120],
        }


@dataclass
class ParseReport:
    """一次解析的完整结果。"""
    questions: list[dict] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)
    total_rows: int = 0
    deduped: int = 0
    retries: int = 0

    @property
    def failed(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def success(self) -> int:
        return len(self.questions)

    @property
    def success_rate(self) -> float:
        base = self.total_rows or (self.success + self.failed)
        return round(self.success / base, 4) if base else 0.0

    def summary(self) -> str:
        parts = [f"共 {self.total_rows} 条，成功 {self.success} 条"]
        if self.failed:
            parts.append(f"失败 {self.failed} 条")
        if self.deduped:
            parts.append(f"去重 {self.deduped} 条")
        if self.retries:
            parts.append(f"重试 {self.retries} 次")
        return "，".join(parts)

    def to_dict(self, max_issues: int = 100) -> dict:
        return {
            "total_rows": self.total_rows,
            "imported": self.success,
            "failed": self.failed,
            "deduped": self.deduped,
            "retries": self.retries,
            "success_rate": self.success_rate,
            "summary": self.summary(),
            "issues": [i.to_dict() for i in self.issues[:max_issues]],
            "issues_truncated": max(0, len(self.issues) - max_issues),
        }


# ============================================================
# 重试
# ============================================================

def _with_retry(fn: Callable[[], Any], report: ParseReport, attempts: int = 3,
                base_delay: float = 0.05) -> Any:
    """整文件级操作的重试（退避 50ms / 100ms）。

    只用于「可能因为瞬时抖动失败」的抽取类操作（PDF 解析、文件读取），
    不用于业务校验——校验失败重试多少次都是失败。
    """
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - 抽取层异常类型不可控
            last = e
            report.retries += 1
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last  # type: ignore[misc]


# ============================================================
# 统一化
# ============================================================

def _normalize(item: dict) -> dict:
    """把各种来源的 dict 转成内部标准结构。"""
    stem = str(item.get("stem") or item.get("题干") or "").strip()
    if not stem:
        raise ImportError("题干不能为空")

    qtype = str(
        item.get("question_type") or item.get("题型") or "single"
    ).strip().lower() or "single"
    if qtype not in VALID_TYPES:
        qtype = "single"

    options_raw = item.get("options") or item.get("选项") or []
    if not isinstance(options_raw, list):
        raise ImportError("options 必须是数组")

    # 无选项题型
    if qtype in ("blank", "short", "calc"):
        options: list[str] = []
    elif qtype == "judge":
        options = ["正确", "错误"]
    else:
        options = [str(o).strip() for o in options_raw if str(o).strip()]
        if len(options) < 2:
            raise ImportError("至少需要 2 个选项")

    correct_raw = item.get("correct_answer")
    if correct_raw is None:
        correct_raw = item.get("正确答案") or item.get("答案")
    if correct_raw is None:
        raise ImportError("缺少正确答案")

    correct_answer = _parse_answer(correct_raw, qtype, len(options))

    explanation = str(
        item.get("explanation") or item.get("解析") or ""
    ).strip()

    return {
        "stem": stem,
        "question_type": qtype,
        "options": options,
        "correct_answer": correct_answer,
        "explanation": explanation,
    }


def _parse_answer(raw, question_type: str, options_count: int) -> str:
    """把答案字段规范化。"""
    # 填空 / 简答 / 计算：保留原文（去首尾空白）
    if question_type in ("blank", "short", "calc"):
        s = str(raw).strip()
        if not s:
            raise ImportError("答案不能为空")
        return s

    s = str(raw).strip().upper()
    if not s:
        raise ImportError("答案不能为空")

    # 多选：收集所有字母，去重排序
    if question_type == "multiple":
        letters = [ch for ch in s if ch in LETTERS]
        if len(set(letters)) < 2:
            raise ImportError(f"多选题答案至少 2 个字母，当前：{raw}")
        return "".join(sorted(set(letters)))

    # 单选 / 判断：单个字母
    if len(s) == 1 and s in LETTERS:
        idx = LETTERS.index(s)
        if idx < options_count:
            return s
        raise ImportError(f"答案 {s} 超出选项范围")

    # 中文答案：判断 / 选择题用「正确/错误」「对/错」也接受
    if question_type == "judge":
        if s in ("正确", "对", "是", "T", "TRUE", "Y"):
            return "A"
        if s in ("错误", "错", "否", "F", "FALSE", "N"):
            return "B"

    # 数字：1=A、0=A 兜底
    if s.isdigit():
        idx = int(s)
        if 1 <= idx <= options_count:
            return LETTERS[idx - 1]
        if 0 <= idx < options_count:
            return LETTERS[idx]
        raise ImportError(f"答案 {s} 超出选项范围")

    raise ImportError(f"无法识别的答案：{raw}")


def _dedupe(report: ParseReport) -> None:
    """文件内去重：题干 + 选项完全相同视为重复，保留第一条。"""
    seen: set[str] = set()
    kept: list[dict] = []
    for i, q in enumerate(report.questions, 1):
        sig = content_signature(q)
        if sig in seen:
            report.deduped += 1
            report.issues.append(ParseIssue(
                location=f"第 {i} 条",
                reason="与文件中前面的题目重复，已跳过",
                severity="warning",
                raw=q.get("stem", ""),
            ))
            continue
        seen.add(sig)
        kept.append(q)
    report.questions = kept


def content_signature(q: dict) -> str:
    """题目去重签名（题干 + 题型 + 选项）。"""
    return "|".join([
        re.sub(r"\s+", "", str(q.get("stem", ""))),
        str(q.get("question_type", "")),
        ",".join(str(o) for o in q.get("options") or []),
    ])


# ============================================================
# JSON
# ============================================================

def parse_json_report(content: bytes) -> ParseReport:
    report = ParseReport()
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except Exception as e:
        raise ImportError(f"JSON 解析失败：{e}")

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ImportError("JSON 顶层必须是数组")

    report.total_rows = len(data)
    for i, item in enumerate(data, 1):
        try:
            report.questions.append(_normalize(item))
        except ImportError as e:
            report.issues.append(ParseIssue(
                location=f"第 {i} 条",
                reason=str(e),
                raw=json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item),
            ))
    _dedupe(report)
    return report


def parse_json(content: bytes) -> list[dict]:
    report = parse_json_report(content)
    if report.failed:
        first = next(i for i in report.issues if i.severity == "error")
        raise ImportError(f"{first.location}：{first.reason}")
    return report.questions


# ============================================================
# Excel
# ============================================================

def parse_excel_report(content: bytes) -> ParseReport:
    report = ParseReport()
    try:
        wb = load_workbook(io.BytesIO(content), data_only=True)
    except Exception as e:
        raise ImportError(f"Excel 解析失败：{e}")

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ImportError("Excel 是空的")

    header = [str(h).strip() if h is not None else "" for h in rows[0]]

    def find_col(*names: str) -> int:
        for i, h in enumerate(header):
            if h in names:
                return i
        return -1

    col_stem = find_col("题干", "题目", "stem")
    if col_stem == -1:
        raise ImportError("Excel 缺少「题干」列")

    col_answer = find_col("正确答案", "答案", "correct_answer")
    if col_answer == -1:
        raise ImportError("Excel 缺少「正确答案」列")

    col_explanation = find_col("解析", "分析", "explanation")
    col_type = find_col("题型", "类型", "question_type", "type")

    # v1 是遇到第一个缺失的选项列就 break，导致「选项A/选项B/选项D」这种
    # 跳列的表头会少解析一列；v2 改成扫完所有列，谁存在收谁。
    option_cols: dict[str, int] = {}
    for i, h in enumerate(header):
        m = re.fullmatch(r"(?:选项|option)\s*([A-Ha-h])", h)
        if m:
            option_cols[m.group(1).upper()] = i
    ordered_letters = sorted(option_cols, key=LETTERS.index)

    if not ordered_letters:
        report.issues.append(ParseIssue(
            location="表头",
            reason="没有找到「选项A」这类选项列，选择题会被判为缺少选项",
            severity="warning",
        ))

    body = rows[1:]
    report.total_rows = len(body)
    remapped_rows = 0

    for row_num, row in enumerate(body, start=2):
        def cell(idx: int) -> Any:
            return row[idx] if 0 <= idx < len(row) else None

        stem_raw = cell(col_stem)
        stem = str(stem_raw).strip() if stem_raw is not None else ""
        if not stem:
            continue  # 空行不算失败，也不计入总行数

        # 题型
        qtype = ""
        if col_type != -1 and cell(col_type) is not None:
            qtype = str(cell(col_type)).strip().lower()

        # 选项：按字母收集，丢掉空值后**重新编号**，
        # 同时把答案里的字母按同一张映射表翻译过去。
        #
        # 为什么必须重编号：表头是「选项A/选项B/选项D」时（手工整理跳过 C 很常见），
        # 如果只按列顺序压紧成 [甲, 乙, 丁]，答案 "D" 会被判「超出选项范围」。
        # 正确做法是 A→A、B→B、D→C，答案 D 跟着变成 C。
        letter_values: list[tuple[str, str]] = []
        for letter in ordered_letters:
            v = cell(option_cols[letter])
            text = "" if v is None else str(v).strip()
            if text:
                letter_values.append((letter, text))

        options = [text for _, text in letter_values]
        letter_map = {old: LETTERS[i] for i, (old, _) in enumerate(letter_values)}

        answer_raw = cell(col_answer) if col_answer != -1 else None
        if isinstance(answer_raw, str) and letter_map:
            mapped = "".join(letter_map.get(ch.upper(), ch) for ch in answer_raw)
            if mapped != answer_raw.strip().upper():
                remapped_rows += 1
            answer_raw = mapped

        explanation = ""
        if col_explanation != -1 and cell(col_explanation) is not None:
            explanation = str(cell(col_explanation)).strip()

        try:
            report.questions.append(_normalize({
                "stem": stem,
                "question_type": qtype or "single",
                "options": options,
                "correct_answer": answer_raw,
                "explanation": explanation,
            }))
        except ImportError as e:
            report.issues.append(ParseIssue(
                location=f"第 {row_num} 行",
                reason=str(e),
                raw=stem,
            ))

    if remapped_rows:
        report.issues.append(ParseIssue(
            location="表头",
            reason=f"选项列不连续，已按字母顺序重新编号并同步修正了 "
                   f"{remapped_rows} 行的答案字母",
            severity="warning",
        ))

    _dedupe(report)

    if not report.questions and report.failed:
        # 全错也算是"文件级失败"，但要把错误清单带出去
        return report
    if not report.questions and not report.failed:
        raise ImportError("Excel 里没有解析到任何题目")

    return report


def parse_excel(content: bytes) -> list[dict]:
    report = parse_excel_report(content)
    if report.failed:
        first = next(i for i in report.issues if i.severity == "error")
        raise ImportError(f"{first.location}：{first.reason}")
    if not report.questions:
        raise ImportError("Excel 里没有解析到任何题目")
    return report.questions


# ============================================================
# Word / PDF 共用的纯文本解析
# ============================================================

_STEM_RE = re.compile(r"^\s*(\d+)\s*[\.、．]\s*(.+)$")
_OPTION_RE = re.compile(r"^\s*([A-Ha-h])\s*[\.、．\)）]\s*(.+)$")
_ANSWER_RE = re.compile(r"^\s*(?:正确答案|答案|answer)\s*[:：]\s*(.+)$")
_EXPLANATION_RE = re.compile(r"^\s*(?:解析|分析|explanation)\s*[:：]\s*(.*)$", re.IGNORECASE)


def _split_text_questions(text: str) -> list[dict]:
    """把纯文本切成题目块（不做校验，校验在 _parse_text_report 里做）。"""
    lines = [l.rstrip() for l in text.splitlines()]
    lines = [l for l in lines if l.strip()]

    questions: list[dict] = []
    current: dict | None = None
    mode: str | None = None

    for line in lines:
        m_stem = _STEM_RE.match(line)
        if m_stem:
            if current:
                questions.append(current)
            current = {
                "stem": m_stem.group(2).strip(),
                "options": [],
                "correct_answer": None,
                "explanation": "",
            }
            mode = "stem"
            continue

        if current is None:
            continue

        m_ans = _ANSWER_RE.match(line)
        if m_ans:
            current["correct_answer"] = m_ans.group(1).strip()
            mode = "answer"
            continue

        m_exp = _EXPLANATION_RE.match(line)
        if m_exp:
            current["explanation"] = m_exp.group(1).strip()
            mode = "explanation"
            continue

        m_opt = _OPTION_RE.match(line)
        if m_opt:
            current["options"].append(m_opt.group(2).strip())
            mode = "options"
            continue

        if mode == "stem":
            current["stem"] += "\n" + line.strip()
        elif mode == "explanation":
            current["explanation"] += "\n" + line.strip()

    if current:
        questions.append(current)

    return questions


def _parse_text_report(text: str) -> ParseReport:
    """把 Word / PDF 抽出的纯文本转成结构化题目，逐题容错。

    乱序判定：没有数字编号开头的行（比如跨页的表头、页码、"第2页"）
    会被忽略并记一条 warning，不影响后面的题目。
    """
    report = ParseReport()
    blocks = _split_text_questions(text)
    report.total_rows = len(blocks)

    if not blocks:
        raise ImportError("没有识别到任何题号，请检查文档是否为「1. 题目」这种编号格式")

    for i, q in enumerate(blocks, 1):
        if q.get("correct_answer") is None:
            report.issues.append(ParseIssue(
                location=f"第 {i} 题",
                reason="缺少「答案：」行",
                raw=q.get("stem", ""),
            ))
            continue

        ans = str(q.get("correct_answer") or "")
        opts = q.get("options") or []
        qtype = q.get("question_type") or ""

        if not qtype:
            if len(opts) == 0:
                # 没有选项：长答案是简答，短答案是填空
                qtype = "short" if len(ans) > 20 else "blank"
            elif (
                len(opts) == 2
                and opts[0] in ("正确", "错误")
                and opts[1] in ("正确", "错误")
            ):
                qtype = "judge"
            elif len(ans) > 1 and all(ch in LETTERS for ch in ans.upper()):
                qtype = "multiple"
            else:
                qtype = "single"
        q["question_type"] = qtype

        try:
            report.questions.append(_normalize(q))
        except ImportError as e:
            report.issues.append(ParseIssue(
                location=f"第 {i} 题",
                reason=str(e),
                raw=q.get("stem", ""),
            ))

    _dedupe(report)
    return report


def _parse_text(text: str) -> list[dict]:
    report = _parse_text_report(text)
    if report.failed:
        first = next(i for i in report.issues if i.severity == "error")
        raise ImportError(f"{first.location}：{first.reason}")
    if not report.questions:
        raise ImportError("没有解析到任何题目，请检查文本格式")
    return report.questions


def parse_word_report(content: bytes) -> ParseReport:
    text = _load_word_text(content)
    if not text.strip():
        raise ImportError("Word 里没有可读文本（可能是扫描件或纯图片）")
    return _parse_text_report(text)


def _load_word_text(content: bytes) -> str:
    try:
        doc = Document(io.BytesIO(content))
    except Exception as e:
        raise ImportError(f"Word 解析失败：{e}")
    return "\n".join(p.text for p in doc.paragraphs)


def parse_word(content: bytes) -> list[dict]:
    return _parse_text(_load_word_text(content))


def _extract_pdf_text(content: bytes, report: ParseReport) -> str:
    """PDF 文本抽取：整篇重试 → 逐页降级。

    PDF 抽取是整条链路里最不稳定的一步（扫描页、加密页、字体缺 ToUnicode
    都会让 pdfplumber 抛异常）。v1 里任何一页出错整个文件就废了，
    v2 先对整篇做 3 次重试，仍然失败就退化成逐页抽取，
    坏页只记一条 issue，好页照常参与解析。
    """
    def whole() -> str:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)

    try:
        return _with_retry(whole, report, attempts=3)
    except Exception:
        pass  # 退化到逐页

    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page_no, page in enumerate(pdf.pages, 1):
                try:
                    parts.append(page.extract_text() or "")
                except Exception as e:  # noqa: BLE001
                    report.issues.append(ParseIssue(
                        location=f"第 {page_no} 页",
                        reason=f"该页文本抽取失败，已跳过：{e}",
                        severity="error",
                    ))
    except Exception as e:
        raise ImportError(f"PDF 解析失败：{e}")

    text = "\n".join(parts)
    if not text.strip():
        raise ImportError("PDF 里没有可读文本（可能是扫描件，需要 OCR）")
    return text


def parse_pdf_report(content: bytes) -> ParseReport:
    report = ParseReport()
    text = _extract_pdf_text(content, report)
    inner = _parse_text_report(text)
    # 合并：页码级 issue + 题目级 issue
    report.issues.extend(inner.issues)
    report.questions = inner.questions
    report.total_rows = inner.total_rows
    report.deduped = inner.deduped
    return report


def parse_pdf(content: bytes) -> list[dict]:
    report = parse_pdf_report(content)
    if report.failed:
        first = next(i for i in report.issues if i.severity == "error")
        raise ImportError(f"{first.location}：{first.reason}")
    if not report.questions:
        raise ImportError("没有解析到任何题目，请检查文本格式")
    return report.questions


# ============================================================
# 分发
# ============================================================

SUPPORTED_EXT = (".json", ".xlsx", ".xls", ".docx", ".pdf")


def detect_format(filename: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".json"):
        return "json"
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return "excel"
    if name.endswith(".docx"):
        return "word"
    if name.endswith(".pdf"):
        return "pdf"
    raise ImportError(f"不支持的文件格式：{filename or '(空文件名)'}，"
                      f"目前支持 {', '.join(SUPPORTED_EXT)}")


def parse_file_report(filename: str, content: bytes) -> ParseReport:
    """带容错的解析入口：永远返回报告，不因个别行失败而整体失败。"""
    if not content:
        raise ImportError("文件是空的")

    fmt = detect_format(filename)
    if fmt == "json":
        return parse_json_report(content)
    if fmt == "excel":
        return parse_excel_report(content)
    if fmt == "word":
        return parse_word_report(content)
    return parse_pdf_report(content)


def parse_file(filename: str, content: bytes) -> list[dict]:
    """v1 语义：遇到第一条错误就抛。保留给不需要容错的调用方。"""
    name = (filename or "").lower()
    if name.endswith(".json"):
        return parse_json(content)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return parse_excel(content)
    if name.endswith(".docx"):
        return parse_word(content)
    if name.endswith(".pdf"):
        return parse_pdf(content)
    raise ImportError(f"不支持的文件格式：{filename}")
