"""流水迟到补抽 · 基镜+纠偏版本链架构（全局唯一口径）。

纪律：
- 基线有效行（版本号=1）永不改；迟到只追加纠偏版本并翻转是否当前。
- 每笔迟到流水必有一条迟到处置单贯穿 待处置→已纠偏，禁止只触发重算无证据。
- 装载在同一事务内登记处置单：流水已入则处置必在，失败整体回滚（失败闭）。
"""

from typing import Any

from app.services.时间 import 此刻


class 并发冲突(RuntimeError):
    """装载/抽取交叉且锁等待超时：调用方须整体回滚，禁止半写。"""


def 取当前快照(conn, 账户键: str, 营业日: str):
    return conn.execute(
        "SELECT * FROM 周期快照 "
        "WHERE 账户键=? AND 营业日=? AND 状态='有效' AND 是否当前=1",
        (账户键, 营业日),
    ).fetchone()


def 取基线快照(conn, 账户键: str, 营业日: str):
    return conn.execute(
        "SELECT * FROM 周期快照 "
        "WHERE 账户键=? AND 营业日=? AND 状态='有效' AND 版本号=1",
        (账户键, 营业日),
    ).fetchone()


def 登记迟到处置(conn, 流水号: str, 账户键: str, 营业日: str, 装载批次编号: str) -> bool:
    """在装载事务内调用。账日已有当前快照即判定迟到，落待处置单。

    与流水插入同事务：要么双写可见，要么整体回滚，不存在“流水已入而处置双无”。
    幂等：同一流水号重复进入不重复登记。
    """
    当前 = 取当前快照(conn, 账户键, 营业日)
    if 当前 is None:
        return False
    已 = conn.execute("SELECT 编号 FROM 迟到处置单 WHERE 流水号=?", (流水号,)).fetchone()
    if 已 is not None:
        return False
    基线 = 取基线快照(conn, 账户键, 营业日)
    conn.execute(
        "INSERT INTO 迟到处置单(流水号, 账户键, 营业日, 装载批次编号, 状态, "
        "基线快照键, 基线余额, 前余额, 时刻, valid) "
        "VALUES (?,?,?,?,'待处置',?,?,?,?,1)",
        (
            流水号,
            账户键,
            营业日,
            装载批次编号,
            基线["快照键"] if 基线 else "",
            int(基线["余额"]) if 基线 else None,
            int(当前["余额"]),
            此刻(),
        ),
    )
    return True


def 结算待处置(conn, 抽取批次编号: str, 营业日: str) -> int:
    """抽取事务末尾调用：把本批重抽覆盖到的待处置单结算为已纠偏。

    账日未被本批重抽的单子保持待处置，留在只读接口里可观测，不静默吞。
    """
    单们 = conn.execute(
        "SELECT * FROM 迟到处置单 WHERE 状态='待处置' AND 营业日=? ORDER BY 编号",
        (营业日,),
    ).fetchall()
    结算 = 0
    for 单 in 单们:
        新镜 = conn.execute(
            "SELECT * FROM 周期快照 "
            "WHERE 账户键=? AND 营业日=? AND 状态='有效' AND 是否当前=1 "
            "AND 抽取批次编号=?",
            (单["账户键"], 营业日, 抽取批次编号),
        ).fetchone()
        if 新镜 is None:
            continue
        版本号 = int(新镜["版本号"])
        conn.execute(
            "UPDATE 迟到处置单 SET 状态='已纠偏', 后余额=?, 纠偏快照键=?, "
            "纠偏批次编号=?, 版本号=?, 级联=?, 处置时刻=? WHERE 编号=?",
            (
                int(新镜["余额"]),
                新镜["快照键"],
                抽取批次编号,
                版本号,
                1 if 版本号 >= 3 else 0,
                此刻(),
                单["编号"],
            ),
        )
        结算 += 1
    return 结算


def 列处置单(conn, 营业日: str = "", 账户键: str = "", 状态: str = "") -> list[dict[str, Any]]:
    sql = "SELECT * FROM 迟到处置单 WHERE 1=1"
    args: list = []
    if 营业日:
        sql += " AND 营业日=?"
        args.append(营业日)
    if 账户键:
        sql += " AND 账户键=?"
        args.append(账户键)
    if 状态:
        sql += " AND 状态=?"
        args.append(状态)
    sql += " ORDER BY 编号 DESC LIMIT 300"
    return [dict(r) for r in conn.execute(sql, args)]


def 读镜(conn, 账户键: str, 营业日: str, 视角: str) -> dict[str, Any]:
    """迟到处置只读接口的取数实现：基线 / 当前 / 纠偏链。"""
    if 视角 == "基线":
        行 = 取基线快照(conn, 账户键, 营业日)
        return {"视角": "基线", "存在": 行 is not None, "镜": dict(行) if 行 else None}
    if 视角 == "当前":
        行 = 取当前快照(conn, 账户键, 营业日)
        return {"视角": "当前", "存在": 行 is not None, "镜": dict(行) if 行 else None}
    if 视角 == "链":
        行们 = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效' "
                "ORDER BY 版本号",
                (账户键, 营业日),
            )
        ]
        return {"视角": "纠偏链", "存在": bool(行们), "链长": len(行们), "链": 行们}
    raise ValueError("视角须为 基线/当前/链 之一")
