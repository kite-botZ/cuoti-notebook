"""题目批量导入接口。

## 为什么单独一个模块

前端 `Bank.vue` 的「批量导入」按钮调的是
`POST /api/banks/{bank_id}/questions/import`，但后端 v1 **没有这个路由**：
`app/importer.py` 写好了 JSON/Excel/Word/PDF 四种解析器，却没有任何地方 import 它，
用户点「开始导入」只会拿到 404。这个模块把这条链路补齐。

## 接口层的三个机制

1. **逐行容错 + 部分成功**：解析层（`app/importer.py`）已经改成行级隔离，
   这里负责把「好的题先入库，坏的行原样返回」；
2. **分块提交**：每 500 条一个事务，某一块写库失败只回滚这一块，
   不影响已经成功的部分，也不会因为一条脏数据把 3000 道题全回滚；
3. **落库前去重**：和库里已有题目按「题干 + 题型 + 选项」比对，
   分块查询（`stem IN (...)`）而不是把整库拉进内存，避免题库大了以后
   导入直接把内存打满。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.cache import cache
from app.db import get_db
from app.importer import ImportError as ParseError, content_signature, parse_file_report
from app.models import Question, QuestionBank
from app.routes.banks import current_user_id

router = APIRouter(prefix="/api", tags=["question-import"])

MAX_FILE_SIZE = int(os.getenv("IMPORT_MAX_SIZE", str(10 * 1024 * 1024)))  # 10MB，与前端一致
CHUNK_SIZE = int(os.getenv("IMPORT_CHUNK_SIZE", "500"))
ALLOWED_EXT = (".json", ".xlsx", ".xls", ".docx", ".pdf")


def _existing_signatures(bank_id: int, stems: list[str], db: Session) -> set[str]:
    """按题干分块查库里已有题目，返回签名集合。

    只查当前这一块用到的题干，不是整个题库，单次查询有界。
    """
    if not stems:
        return set()
    rows = (
        db.query(Question.stem, Question.question_type, Question.options)
        .filter(Question.bank_id == bank_id, Question.stem.in_(stems))
        .all()
    )
    return {
        content_signature({"stem": s, "question_type": t, "options": o or []})
        for s, t, o in rows
    }


@router.post("/banks/{bank_id}/questions/import")
async def import_questions(
    bank_id: int,
    file: UploadFile = File(...),
    dry_run: bool = False,
    user_id: int = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    """批量导入题目（JSON / Excel / Word / PDF）。

    - `dry_run=true`：只校验不落库，用来让用户先看一眼错误清单。
    - 返回里的 `issues` 是逐行错误，前端可以直接列出来让用户改。
    """
    bank = (
        db.query(QuestionBank)
        .filter(QuestionBank.id == bank_id, QuestionBank.user_id == user_id)
        .first()
    )
    if not bank:
        raise HTTPException(status_code=404, detail="题库不存在")

    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的格式 {ext or '(无扩展名)'}，请上传 {'/'.join(ALLOWED_EXT)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="文件是空的")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_FILE_SIZE // 1024 // 1024}MB",
        )

    # ---------- 1. 解析（行级容错，不因个别行失败而整体失败）----------
    try:
        report = parse_file_report(filename, content)
    except ParseError as e:
        # 文件级致命错误：格式不对、文档损坏、一条都识别不出来
        raise HTTPException(status_code=422, detail=str(e))

    parsed = report.questions

    # ---------- 2. 落库前去重 ----------
    duplicates: list[dict] = []
    to_insert: list[dict] = []
    for i in range(0, len(parsed), CHUNK_SIZE):
        chunk = parsed[i:i + CHUNK_SIZE]
        existing = _existing_signatures(bank_id, [q["stem"] for q in chunk], db)
        for q in chunk:
            sig = content_signature(q)
            if sig in existing:
                duplicates.append({"stem": q["stem"][:80], "reason": "题库中已存在"})
                continue
            existing.add(sig)  # 同一批文件里也不重复插
            to_insert.append(q)

    inserted = 0
    write_errors: list[dict] = []

    # ---------- 3. 分块提交，单块失败只回滚该块 ----------
    if not dry_run:
        for i in range(0, len(to_insert), CHUNK_SIZE):
            chunk = to_insert[i:i + CHUNK_SIZE]
            try:
                db.add_all([
                    Question(
                        bank_id=bank_id,
                        stem=q["stem"],
                        question_type=q["question_type"],
                        options=q["options"],
                        correct_answer=q["correct_answer"],
                        explanation=q["explanation"],
                    )
                    for q in chunk
                ])
                db.commit()
                inserted += len(chunk)
            except Exception as e:  # noqa: BLE001 - 单块失败不能影响整批
                db.rollback()
                write_errors.append({
                    "location": f"第 {i + 1}~{i + len(chunk)} 条",
                    "reason": f"写库失败，本块已回滚：{e}",
                    "severity": "error",
                    "raw": "",
                })

    # ---------- 4. 缓存一致性：题库版本号 +1，旧缓存立刻失效 ----------
    if inserted:
        cache.bump_bank_version(bank_id)

    result = report.to_dict()
    result["duplicates"] = duplicates[:50]
    result["duplicates_truncated"] = max(0, len(duplicates) - 50)
    # duplicate_count 统计「所有被跳过的重复题」：文件内重复（解析层去重）
    # + 与库里已有题目重复（落库前去重）。用户关心的是总数，不是分在哪一层。
    result["duplicate_count"] = len(duplicates) + report.deduped
    result["inserted"] = inserted
    result["dry_run"] = dry_run
    result["issues"] = result["issues"] + write_errors
    result["failed"] = report.failed + len(write_errors)

    if dry_run:
        result["message"] = (
            f"校验完成（未入库）：可导入 {len(to_insert)} 条，"
            f"重复 {len(duplicates)} 条，格式错误 {report.failed} 条"
        )
    else:
        result["message"] = (
            f"导入完成：成功 {inserted} 条，跳过重复 {len(duplicates)} 条，"
            f"失败 {result['failed']} 条"
        )
    return result
