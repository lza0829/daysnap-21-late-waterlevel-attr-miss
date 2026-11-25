"""跨日水位账 · 已落地（甲口径：**水位钉价值日**）。

口径（全局唯一，禁止与「钉到达日」混用）：

- 每一笔「到达营业日 > 价值日」的跨日迟到，必须与流水在同一事务里落一行水位账，
  记录 水位号 / 流水号 / 价值日 / 到达营业日 / 归属日 / valid / 装载批次。
- **归属日 = 价值日**：净额计入价值日正式镜，到达日**永不**因该笔新增净额。
- 价值日已封印：必须持解封手续才可动其正式镜，否则**整笔拒绝**（装载整体回滚），
  价值日与到达日正式镜皆不变。
- 失败闭：装载/封印/抽取/回放皆 `BEGIN IMMEDIATE`；迟到与封印抢锁时要么串行成功，
  要么冲突整体回滚，禁止双日正式同加（无水位双改失败闭）。
- 装载、封印、抽取、回放同票：水位账同时挂着装载批次与结算抽取批次，可追溯。

与 hourspan SCD2 无关：水位账是「跨日归属凭证」，不是维表。
"""

import uuid
from typing import Any

from app.services.时间 import 此刻

状态 = "已落地"
架构 = "甲：水位钉价值日"
钉法 = "价值日"


class 跨日拒绝(RuntimeError):
    """跨日迟到/双改被拒：调用方须整体回滚，禁止半写或静默改写正式镜。"""


def 表名() -> str:
    return "跨日水位账表"


# ---------------------------------------------------------------- 归属判定


def 是跨日(价值日: str, 到达日: str) -> bool:
    return bool(价值日) and bool(到达日) and 价值日 != 到达日


def 是跨日迟到(价值日: str, 到达日: str) -> bool:
    """到达晚于价值日即为跨日迟到（需水位账 + 封印闸）。"""
    return 是跨日(价值日, 到达日) and 到达日 > 价值日


def 解析归属(conn, 价值日: str, 到达日: str) -> dict:
    """甲口径：归属日恒为价值日；是否可动价值日正式镜取决于封印。"""
    跨日 = 是跨日(价值日, 到达日)
    封印 = bool(价值日) and 是否封印(conn, 价值日)
    return {
        "归属日": 价值日 or 到达日,
        "钉法": 钉法,
        "跨日": 跨日,
        "价值日封印": 封印,
        "可改价值日正式": not 封印,
        "需解封": 封印,
        "可改到达日正式": False if 跨日 else True,
    }


# ---------------------------------------------------------------- 封印 / 解封


def 取封印(conn, 营业日: str):
    return conn.execute("SELECT * FROM 营业日封印 WHERE 营业日=?", (营业日,)).fetchone()


def 是否封印(conn, 营业日: str) -> bool:
    if not 营业日:
        return False
    row = 取封印(conn, 营业日)
    return bool(row) and row["状态"] == "已封印"


def 封印(conn, 营业日: str, 批次编号: str = "", 手续编号: str = "") -> dict:
    """封印营业日：此后该日正式镜冻结，装载/抽取须先解封。调用方须在事务内。"""
    营业日 = (营业日 or "").strip()
    if not 营业日:
        raise 跨日拒绝("封印须指定营业日")
    已 = 取封印(conn, 营业日)
    if 已 and 已["状态"] == "已封印":
        return dict(已)
    时 = 此刻()
    if 已 is None:
        conn.execute(
            "INSERT INTO 营业日封印(营业日, 状态, 封印批次编号, 封印时刻, valid) "
            "VALUES (?, '已封印', ?, ?, 1)",
            (营业日, 批次编号, 时),
        )
    else:
        conn.execute(
            "UPDATE 营业日封印 SET 状态='已封印', 封印批次编号=?, 封印时刻=?, "
            "解封批次编号='', 解封时刻='', 解封手续='', valid=1 WHERE 营业日=?",
            (批次编号, 时, 营业日),
        )
    conn.execute(
        "INSERT INTO 封印手续(营业日, 动作, 手续编号, 理由, 批次编号, 时刻) "
        "VALUES (?, '封印', ?, '', ?, ?)",
        (营业日, 手续编号, 批次编号, 时),
    )
    return {"营业日": 营业日, "状态": "已封印", "批次编号": 批次编号, "时刻": 时}


def 解封(conn, 营业日: str, 批次编号: str = "", 手续编号: str = "", 理由: str = "") -> dict:
    """解封营业日：必须持解封手续（手续编号非空），否则拒绝。调用方须在事务内。"""
    营业日 = (营业日 or "").strip()
    手续编号 = (手续编号 or "").strip()
    if not 营业日:
        raise 跨日拒绝("解封须指定营业日")
    if not 手续编号:
        raise 跨日拒绝("解封须持解封手续（手续编号），否则禁止动已封印正式镜")
    已 = 取封印(conn, 营业日)
    if 已 is None or 已["状态"] != "已封印":
        # 未封印：幂等视为可动，但留手续痕迹
        conn.execute(
            "INSERT INTO 封印手续(营业日, 动作, 手续编号, 理由, 批次编号, 时刻) "
            "VALUES (?, '解封(未封印)', ?, ?, ?, ?)",
            (营业日, 手续编号, 理由, 批次编号, 此刻()),
        )
        return {"营业日": 营业日, "状态": "未封印", "手续编号": 手续编号}
    时 = 此刻()
    conn.execute(
        "UPDATE 营业日封印 SET 状态='已解封', 解封批次编号=?, 解封时刻=?, "
        "解封手续=? WHERE 营业日=?",
        (批次编号, 时, 手续编号, 营业日),
    )
    conn.execute(
        "INSERT INTO 封印手续(营业日, 动作, 手续编号, 理由, 批次编号, 时刻) "
        "VALUES (?, '解封', ?, ?, ?, ?)",
        (营业日, 手续编号, 理由, 批次编号, 时),
    )
    return {"营业日": 营业日, "状态": "已解封", "手续编号": 手续编号, "时刻": 时}


def 校验价值日可动(conn, 价值日: str, 解封手续: str = "", 批次编号: str = "") -> None:
    """装载/抽取动价值日正式镜前的闸：已封印且无解封手续 → 整笔拒绝。

    若带了解封手续，则先落解封，再放行（同票：手续、批次、时刻一并留痕）。
    """
    if not 是否封印(conn, 价值日):
        return
    if (解封手续 or "").strip():
        解封(conn, 价值日, 批次编号, 解封手续, "迟到装载持解封手续动价值日正式镜")
        return
    raise 跨日拒绝(
        f"价值日 {价值日} 已封印：跨日迟到须持解封手续方可动该日正式镜，否则整笔拒绝"
    )


def 列封印(conn) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM 营业日封印 ORDER BY 营业日 DESC LIMIT 200"
    )]


def 列封印手续(conn, 营业日: str = "") -> list[dict[str, Any]]:
    if 营业日:
        rows = conn.execute(
            "SELECT * FROM 封印手续 WHERE 营业日=? ORDER BY 编号 DESC LIMIT 200", (营业日,)
        )
    else:
        rows = conn.execute("SELECT * FROM 封印手续 ORDER BY 编号 DESC LIMIT 200")
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- 水位账落/结算


def 落水位(
    conn,
    流水号: str,
    账户键: str,
    价值日: str,
    到达日: str,
    归属日: str,
    装载批次编号: str = "",
    水位号: str = "",
    载荷: str = "{}",
) -> str:
    """在装载事务内调用：跨日迟到与流水同票落水位账（待归位）。"""
    号 = 水位号.strip() or f"水位-{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO 跨日水位账表(水位号, 流水号, 账户键, 价值日, 到达日, 归属日, "
        "装载批次编号, 状态, valid, 时刻, 载荷) "
        "VALUES (?,?,?,?,?,?,?, '待归位', 1, ?, ?)",
        (号, 流水号, 账户键, 价值日, 到达日, 归属日, 装载批次编号, 此刻(), 载荷),
    )
    return 号


def 结算水位(conn, 归属日: str, 抽取批次编号: str) -> int:
    """抽取价值日事务末尾调用：把归属该日的待归位水位结算为已归位。"""
    行们 = conn.execute(
        "SELECT 编号 FROM 跨日水位账表 WHERE 归属日=? AND 状态='待归位' AND valid=1",
        (归属日,),
    ).fetchall()
    for r in 行们:
        conn.execute(
            "UPDATE 跨日水位账表 SET 状态='已归位', 结算批次编号=?, 处置时刻=? WHERE 编号=?",
            (抽取批次编号, 此刻(), r["编号"]),
        )
    return len(行们)


def 校验跨日水位(conn, 营业日: str) -> None:
    """抽取前的失败闭闸：凡与本日相关的跨日流水必须有合法水位账，否则拒绝。

    同时检查「价值日=本日」与「到达日=本日」两侧：
    抽取任一日都不得在缺水位账的情况下改写正式净额（禁止无水位双改）。
    """
    行们 = conn.execute(
        "SELECT 流水号, 营业日, 到达日, 水位号 FROM 变动流水 "
        "WHERE 命运='已入账' AND 到达日<>'' AND 到达日<>营业日 "
        "AND (营业日=? OR 到达日=?)",
        (营业日, 营业日),
    ).fetchall()
    for r in 行们:
        if not (r["水位号"] or "").strip():
            raise 跨日拒绝(
                f"流水 {r['流水号']} 跨日（价值日 {r['营业日']}≠到达日 {r['到达日']}）却无水位号："
                "禁止无水位双改，抽取失败闭"
            )
        水 = conn.execute(
            "SELECT 编号, valid FROM 跨日水位账表 WHERE 水位号=? AND 流水号=?",
            (r["水位号"], r["流水号"]),
        ).fetchone()
        if 水 is None or int(水["valid"]) != 1:
            raise 跨日拒绝(
                f"流水 {r['流水号']} 的水位账 {r['水位号']} 缺失或已失效：禁止无水位双改，抽取失败闭"
            )


def 双日同加是否禁止(conn, 价值日: str, 到达日: str) -> bool:
    """甲口径恒为 True：同一笔跨日迟到绝不同时计入价值日与到达日两个正式净额。"""
    return True


def 跨日迟到放行(conn, 价值日: str, 到达日: str) -> bool:
    """跨日迟到放行判定：价值日未封印即可放行；已封印须走 校验价值日可动 的解封路径。"""
    if not 是跨日迟到(价值日, 到达日):
        return True
    return not 是否封印(conn, 价值日)


# ---------------------------------------------------------------- 只读核证


def 列水位(conn, 水位号: str = "", 流水号: str = "", 账户键: str = "", 归属日: str = "") -> list[dict]:
    sql = "SELECT * FROM 跨日水位账表 WHERE 1=1"
    args: list = []
    if 水位号:
        sql += " AND 水位号=?"
        args.append(水位号)
    if 流水号:
        sql += " AND 流水号=?"
        args.append(流水号)
    if 账户键:
        sql += " AND 账户键=?"
        args.append(账户键)
    if 归属日:
        sql += " AND 归属日=?"
        args.append(归属日)
    sql += " ORDER BY 编号 DESC LIMIT 300"
    return [dict(r) for r in conn.execute(sql, args)]


def 核证行(行: dict) -> dict:
    """核证只读口径：水位号、归属日、valid、钉法显式给出。"""
    return {
        "水位号": 行.get("水位号", ""),
        "流水号": 行.get("流水号", ""),
        "账户键": 行.get("账户键", ""),
        "价值日": 行.get("价值日", ""),
        "到达营业日": 行.get("到达日", ""),
        "归属日": 行.get("归属日", ""),
        "钉法": 钉法,
        "状态": 行.get("状态", ""),
        "valid": bool(行.get("valid", 0)),
        "装载批次编号": 行.get("装载批次编号", ""),
        "结算批次编号": 行.get("结算批次编号", ""),
        "时刻": 行.get("时刻", ""),
        "处置时刻": 行.get("处置时刻", ""),
    }


def 查现场(conn, 键: str | None = None) -> dict:
    """只读核证接口取数：水位账全量 + 钉法 + 封印现场，键可匹配任意字段。"""
    rows = [核证行(dict(r)) for r in conn.execute(
        "SELECT * FROM 跨日水位账表 ORDER BY 编号 DESC LIMIT 200"
    )]
    if 键:
        rows = [r for r in rows if 键 in [str(v) for v in r.values()]]
    封印 = [dict(r) for r in conn.execute(
        "SELECT 营业日, 状态, 封印批次编号, 解封批次编号, 解封手续 FROM 营业日封印 "
        "ORDER BY 营业日 DESC LIMIT 100"
    )]
    return {
        "水位": rows,
        "封印": 封印,
        "钉法": 钉法,
        "架构": 架构,
        "nn": "21",
        "valid": True,
    }


def 巡检包(payload: dict | None = None) -> dict:
    base = {
        "kind": "waterlevel",
        "nn": "21",
        "bias": 21,
        "钉法": 钉法,
        "allow_value_day_rewrite": False,  # 甲口径：价值日正式镜不可无手续改写
        "need_water_row": True,
        "forbid_double_day_add": True,
    }
    if payload:
        base.update(payload)
    return base
