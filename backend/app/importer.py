"""批量导入题目的解析器。

支持格式：JSON / Excel(.xlsx) / Word(.docx) / PDF
最终统一成 list[dict]：
    {
      "stem": str,
      "question_type": str,         # single / multiple / judge / blank / short
      "options": list[str],         # blank / short 为空数组
      "correct_answer": str,        # single/judge 是 "A"；multiple 是 "AB"；blank/short 是文本
      "explanation": str
    }
"""

import io
import json
import re

from docx import Document
from openpyxl import load_workbook
import pdfplumber


class ImportError(Exception):
    """自定义异常，接口层捕获后转 422。"""
    pass


LETTERS = "ABCDEFGH"
VALID_TYPES = {"single", "multiple", "judge", "blank", "short"}


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
    if qtype in ("blank", "short"):
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
    # 填空 / 简答：保留原文（去首尾空白）
    if question_type in ("blank", "short"):
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

    # 数字：1=A、0=A 兜底
    if s.isdigit():
        idx = int(s)
        if 1 <= idx <= options_count:
            return LETTERS[idx - 1]
        if 0 <= idx < options_count:
            return LETTERS[idx]
        raise ImportError(f"答案 {s} 超出选项范围")

    raise ImportError(f"无法识别的答案：{raw}")


# ============================================================
# JSON
# ============================================================

def parse_json(content: bytes) -> list[dict]:
    try:
        data = json.loads(content.decode("utf-8-sig"))
    except Exception as e:
        raise ImportError(f"JSON 解析失败：{e}")

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ImportError("JSON 顶层必须是数组")

    result = []
    for i, item in enumerate(data, 1):
        try:
            result.append(_normalize(item))
        except ImportError as e:
            raise ImportError(f"第 {i} 条：{e}")
    return result


# ============================================================
# Excel
# ============================================================

def parse_excel(content: bytes) -> list[dict]:
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

    # 找选项列
    option_cols: list[int] = []
    for letter in LETTERS:
        idx = find_col(
            f"选项{letter}",
            f"选项{letter.lower()}",
            f"option{letter}",
            f"option{letter.lower()}",
        )
        if idx == -1:
            break
        option_cols.append(idx)

    result: list[dict] = []

    for row_num, row in enumerate(rows[1:], start=2):
        stem_raw = row[col_stem] if col_stem < len(row) else None
        stem = str(stem_raw).strip() if stem_raw is not None else ""
        if not stem:
            continue  # 跳过空行

        # 题型
        qtype = ""
        if col_type != -1 and col_type < len(row) and row[col_type] is not None:
            qtype = str(row[col_type]).strip().lower()

        # 选项
        options: list[str] = []
        for idx in option_cols:
            v = row[idx] if idx < len(row) else None
            options.append("" if v is None else str(v).strip())
        while options and not options[-1]:
            options.pop()

        # 答案
        answer_raw = row[col_answer] if col_answer < len(row) else None

        # 解析
        explanation = ""
        if (
            col_explanation != -1
            and col_explanation < len(row)
            and row[col_explanation] is not None
        ):
            explanation = str(row[col_explanation]).strip()

        try:
            result.append(_normalize({
                "stem": stem,
                "question_type": qtype or "single",
                "options": options,
                "correct_answer": answer_raw,
                "explanation": explanation,
            }))
        except ImportError as e:
            raise ImportError(f"第 {row_num} 行：{e}")

    if not result:
        raise ImportError("Excel 里没有解析到任何题目")

    return result


# ============================================================
# Word / PDF 共用的纯文本解析
# ============================================================

_STEM_RE = re.compile(r"^\s*\d+\s*[\.、．]\s*(.+)$")
_OPTION_RE = re.compile(r"^\s*([A-Ha-h])\s*[\.、．\)）]\s*(.+)$")
_ANSWER_RE = re.compile(r"^\s*(?:正确答案|答案|answer)\s*[:：]\s*(.+)$")
_EXPLANATION_RE = re.compile(r"^\s*(?:解析|分析|explanation)\s*[:：]\s*(.*)$", re.IGNORECASE)


def _parse_text(text: str) -> list[dict]:
    """把 Word / PDF 抽出的纯文本转成结构化题目。"""
    lines = [l.rstrip() for l in text.splitlines()]
    lines = [l for l in lines if l.strip()]

    questions: list[dict] = []
    current: dict | None = None
    mode: str | None = None

    for line in lines:
        # 题干行：数字开头
        m_stem = _STEM_RE.match(line)
        if m_stem:
            if current:
                questions.append(current)
            current = {
                "stem": m_stem.group(1).strip(),
                "options": [],
                "correct_answer": None,
                "explanation": "",
            }
            mode = "stem"
            continue

        if current is None:
            continue

        # 答案行
        m_ans = _ANSWER_RE.match(line)
        if m_ans:
            current["correct_answer"] = m_ans.group(1).strip()
            mode = "answer"
            continue

        # 解析行
        m_exp = _EXPLANATION_RE.match(line)
        if m_exp:
            current["explanation"] = m_exp.group(1).strip()
            mode = "explanation"
            continue

        # 选项行
        m_opt = _OPTION_RE.match(line)
        if m_opt:
            current["options"].append(m_opt.group(2).strip())
            mode = "options"
            continue

        # 续行
        if mode == "stem":
            current["stem"] += "\n" + line.strip()
        elif mode == "explanation":
            current["explanation"] += "\n" + line.strip()

    if current:
        questions.append(current)

    result: list[dict] = []

    for i, q in enumerate(questions, 1):
        if q.get("correct_answer") is None:
            raise ImportError(f"第 {i} 题缺少「答案」")

        # 自动推断题型
        ans = str(q.get("correct_answer") or "")
        opts = q.get("options") or []
        qtype = q.get("question_type") or ""

        if not qtype:
            if len(opts) == 0:
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
            result.append(_normalize(q))
        except ImportError as e:
            raise ImportError(f"第 {i} 题：{e}")

    if not result:
        raise ImportError("没有解析到任何题目，请检查文本格式")

    return result


def parse_word(content: bytes) -> list[dict]:
    try:
        doc = Document(io.BytesIO(content))
    except Exception as e:
        raise ImportError(f"Word 解析失败：{e}")
    text = "\n".join(p.text for p in doc.paragraphs)
    return _parse_text(text)


def parse_pdf(content: bytes) -> list[dict]:
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as e:
        raise ImportError(f"PDF 解析失败：{e}")
    return _parse_text(text)


# ============================================================
# 分发
# ============================================================

def parse_file(filename: str, content: bytes) -> list[dict]:
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