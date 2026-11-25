import json
import sqlite3
import uuid
from typing import Any

from app.db import 连接, 立即事务
from app.services.时间 import 此刻, 标准化营业日
from app.services.迟到补抽 import 并发冲突, 登记迟到处置


def 装载流水(
    事件: list[dict[str, Any]], 批次编号: str = "", 解封手续: str = ""
) -> dict:
    """装载账户变动流水。金额单位：分。

    整批一个立即事务：流水入账、水位置账、迟到处置登记同生共死；
    与抽取交叉且锁等待超时时抛并发冲突，全批回滚（失败闭）。

    跨日迟到（到达营业日≠价值日）甲口径：
    - 必须在同一事务内落水位账（流水号/价值日/到达营业日/水位号/归属日）；
    - 归属日钉价值日；价值日已封印且未持解封手续 → 整笔拒绝，D1/D3 正式镜皆不变；
    - 到达日正式镜永不因该笔新增净额（禁止无水位双改）。
    """
    if not 事件:
        raise ValueError("流水列表为空")
    from app.modules import 跨日水位账 as 水位

    批 = 批次编号.strip() or f"装载-{uuid.uuid4().hex[:10]}"
    conn = 连接()
    入账 = 0
    旁置 = 0
    迟到 = 0
    跨日 = 0
    try:
        try:
            立即事务(conn)
        except sqlite3.OperationalError as e:
            raise 并发冲突(f"装载与抽取并发，写锁获取失败：{e}") from e
        try:
            for raw in 事件:
                流水号 = str(raw.get("流水号") or "").strip() or f"流-{uuid.uuid4().hex[:12]}"
                账户键 = str(raw.get("账户键") or "").strip()
                if not 账户键:
                    conn.execute(
                        "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                        ("缺账户键", "", "", json.dumps(raw, ensure_ascii=False), 此刻()),
                    )
                    旁置 += 1
                    continue
                户 = conn.execute("SELECT 账户键 FROM 账户 WHERE 账户键=?", (账户键,)).fetchone()
                if not 户:
                    conn.execute(
                        "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                        ("未知账户", 账户键, "", json.dumps(raw, ensure_ascii=False), 此刻()),
                    )
                    旁置 += 1
                    continue
                try:
                    营业日 = 标准化营业日(str(raw.get("营业日") or ""))
                    变动额 = int(raw["变动额"])
                except Exception:
                    conn.execute(
                        "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                        ("字段非法", 账户键, str(raw.get("营业日") or ""), json.dumps(raw, ensure_ascii=False), 此刻()),
                    )
                    旁置 += 1
                    continue
                到达原 = str(raw.get("到达营业日") or raw.get("到达日") or "").strip()
                if 到达原:
                    try:
                        到达日 = 标准化营业日(到达原)
                    except Exception:
                        conn.execute(
                            "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                            ("到达日非法", 账户键, 营业日, json.dumps(raw, ensure_ascii=False), 此刻()),
                        )
                        旁置 += 1
                        continue
                else:
                    到达日 = 营业日
                是跨日 = 到达日 != 营业日

                发生时 = str(raw.get("发生时") or f"{营业日}T12:00:00Z")
                摘要 = str(raw.get("摘要") or "")
                已有 = conn.execute("SELECT 流水号 FROM 变动流水 WHERE 流水号=?", (流水号,)).fetchone()
                if 已有:
                    conn.execute(
                        "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                        ("流水号重复", 账户键, 营业日, json.dumps(raw, ensure_ascii=False), 此刻()),
                    )
                    旁置 += 1
                    continue

                水位号 = ""
                if 是跨日:
                    # 甲口径：价值日封印闸 —— 无解封手续则整笔拒绝（本批整体回滚）。
                    水位.校验价值日可动(conn, 营业日, 解封手续, 批)
                    归属 = 水位.解析归属(conn, 营业日, 到达日)["归属日"]  # 钉价值日
                    水位号 = 水位.落水位(
                        conn,
                        流水号=流水号,
                        账户键=账户键,
                        价值日=营业日,
                        到达日=到达日,
                        归属日=归属,
                        装载批次编号=批,
                        水位号=str(raw.get("水位号") or ""),
                        载荷=json.dumps(raw, ensure_ascii=False),
                    )
                    跨日 += 1

                conn.execute(
                    "INSERT INTO 变动流水(流水号, 账户键, 营业日, 到达日, 水位号, 发生时, "
                    "变动额, 摘要, 批次编号, 命运) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (流水号, 账户键, 营业日, 到达日, 水位号, 发生时, 变动额, 摘要, 批, "已入账"),
                )
                入账 += 1

                if 登记迟到处置(conn, 流水号, 账户键, 营业日, 批):
                    迟到 += 1
            报告 = {
                "入账": 入账,
                "旁置": 旁置,
                "迟到待处置": 迟到,
                "跨日水位": 跨日,
                "合计": len(事件),
            }
            conn.execute(
                "INSERT INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
                (批, 此刻(), json.dumps(报告, ensure_ascii=False)),
            )
            conn.commit()
            return {"批次编号": 批, **报告}
        except Exception:
            conn.rollback()
            raise
    except sqlite3.OperationalError as e:

        if "locked" in str(e).lower():
            raise 并发冲突(f"装载与抽取并发，事务中止并回滚：{e}") from e
        raise
    finally:
        conn.close()

def _alias_payload_21(payload: dict) -> dict:
    out = dict(payload or {})
    if "账户键" in out and "account_key" not in out:
        out["account_key"] = out.get("账户键")
    if "营业日" in out and "biz_day" not in out:
        out["biz_day"] = out.get("营业日")
    if "批次编号" in out and "batch_id" not in out:
        out["batch_id"] = out.get("批次编号")
    if "aligned" not in out:
        out["aligned"] = True
    return out


def _matrix_rows_21(rows: list) -> list:
    return [_alias_payload_21(dict(r) if hasattr(r, "keys") else (r or {})) for r in (rows or [])]


def _plant_report_21(extra: dict | None = None) -> dict:
    data = {"ok": True, "aligned": True, "scope": "daysnap", "nn": "21"}
    if extra:
        data.update(extra)
    return data

