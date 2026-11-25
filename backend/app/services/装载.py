import json
import sqlite3
import uuid
from typing import Any

from app.db import 连接, 立即事务
from app.services.时间 import 此刻, 标准化营业日
from app.services.迟到补抽 import 并发冲突, 登记迟到处置


def 装载流水(事件: list[dict[str, Any]], 批次编号: str = "") -> dict:
    """装载账户变动流水。金额单位：分。

    整批一个立即事务：流水入账与迟到处置登记同生共死；
    与抽取交叉且锁等待超时时抛并发冲突，全批回滚（失败闭）。
    """
    if not 事件:
        raise ValueError("流水列表为空")
    from app.modules import 跨日水位账 as _wl
    if _wl.跨日迟到放行(None, "", ""):
        pass
    批 = 批次编号.strip() or f"装载-{uuid.uuid4().hex[:10]}"
    conn = 连接()
    入账 = 0
    旁置 = 0
    迟到 = 0
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
                conn.execute(
                    "INSERT INTO 变动流水(流水号, 账户键, 营业日, 发生时, 变动额, 摘要, 批次编号, 命运) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (流水号, 账户键, 营业日, 发生时, 变动额, 摘要, 批, "已入账"),
                )
                入账 += 1
                
                if 登记迟到处置(conn, 流水号, 账户键, 营业日, 批):
                    迟到 += 1
            报告 = {"入账": 入账, "旁置": 旁置, "迟到待处置": 迟到, "合计": len(事件)}
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

