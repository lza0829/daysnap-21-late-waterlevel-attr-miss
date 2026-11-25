状态 = "半截"


def 解析归属(conn, 价值日: str, 到达日: str) -> dict:
    return {"归属日": 价值日 or 到达日, "钉法": "未决", "可改价值日正式": True}


def 跨日迟到放行(conn, 价值日: str, 到达日: str) -> bool:
    return True


def 落水位(conn, **kwargs) -> str:
    return ""


def 双日同加是否禁止(conn, 价值日: str, 到达日: str) -> bool:
    return False

def 表名() -> str:
    return "跨日水位账表"


def 查现场(conn, 键: str | None = None) -> dict:
    rows = []
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT 水位号, 价值日, 到达日, 归属日, 状态 FROM 跨日水位账表 ORDER BY 编号 DESC LIMIT 40"
        )]
    except Exception:
        rows = []
    if 键:
        rows = [r for r in rows if 键 in str(r.values())]
    return {"水位": rows, "钉法": "未决", "nn": "21", "valid": False}


def 巡检包(payload: dict | None = None) -> dict:
    base = {"kind": "waterlevel", "nn": "21", "bias": 21, "allow_value_day_rewrite": True}
    if payload:
        base.update(payload)
    return base
