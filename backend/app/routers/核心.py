import json
import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接, 立即事务
from app.services import 回放, 抽取, 目录, 装载, 迟到补抽
from app.modules import 跨日水位账

路由 = APIRouter(prefix="/api")


def _并发转409(e: sqlite3.OperationalError) -> HTTPException:
    return HTTPException(409, f"装载/抽取交叉冲突，事务已回滚（失败闭）：{e}")


class 装载请求(BaseModel):
    批次编号: str = ""
    解封手续: str = ""
    流水: list = Field(default_factory=list)


class 营业日请求(BaseModel):
    营业日: str
    批次编号: str = ""
    解封手续: str = ""


class 封印请求(BaseModel):
    营业日: str
    批次编号: str = ""
    手续编号: str = ""
    理由: str = ""


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "日镜账",
        "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/台参")
def 取台参():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
    finally:
        conn.close()


@路由.get("/账户")
def 列账户():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 账户 ORDER BY 账户键")]
    finally:
        conn.close()


@路由.get("/流水")
def 列流水(营业日: str = "", 账户键: str = ""):
    conn = 连接()
    try:
        sql = (
            "SELECT 流.*, 迟.状态 AS 迟到状态, 迟.编号 AS 迟到处置编号, 迟.valid AS 迟到valid, "
            "水.水位号 AS 水位账号, 水.归属日 AS 水位归属日, 水.状态 AS 水位状态, 水.valid AS 水位valid "
            "FROM 变动流水 流 "
            "LEFT JOIN 迟到处置单 迟 ON 迟.流水号 = 流.流水号 "
            "LEFT JOIN 跨日水位账表 水 ON 水.流水号 = 流.流水号 WHERE 1=1"
        )
        args: list = []
        if 营业日:
            sql += " AND 流.营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 流.账户键=?"
            args.append(账户键)
        sql += " ORDER BY 流.营业日 DESC, 流.发生时 DESC LIMIT 300"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/快照")
def 列快照(营业日: str = "", 账户键: str = "", 含历史: bool = False):
    """默认只列当前版本镜；含历史=true 返回完整纠偏版本链。"""
    conn = 连接()
    try:
        sql = "SELECT * FROM 周期快照 WHERE 状态='有效'"
        args: list = []
        if not 含历史:
            sql += " AND 是否当前=1"
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 账户键, 版本号 LIMIT 500"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/迟到处置")
def 列迟到处置(营业日: str = "", 账户键: str = "", 状态: str = ""):
    """迟到处置实体只读接口：每笔迟到一条，含 valid 与处置状态证据。"""
    conn = 连接()
    try:
        return 迟到补抽.列处置单(conn, 营业日, 账户键, 状态)
    finally:
        conn.close()


@路由.get("/迟到处置/镜")
def 读迟到镜(账户键: str, 营业日: str, 视角: str = "当前"):
    """迟到处置只读接口：视角=基线（基镜旧余额）/当前（现行余额）/链（纠偏版本链）。"""
    conn = 连接()
    try:
        try:
            return 迟到补抽.读镜(conn, 账户键, 营业日, 视角)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    finally:
        conn.close()


@路由.get("/差额")
def 列差额(回放批次编号: str = ""):
    conn = 连接()
    try:
        if 回放批次编号:
            rows = conn.execute(
                "SELECT * FROM 差额行 WHERE 回放批次编号=? ORDER BY 编号 DESC",
                (回放批次编号,),
            )
        else:
            rows = conn.execute("SELECT * FROM 差额行 ORDER BY 编号 DESC LIMIT 200")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/断档")
def 列断档():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 断档记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/跳变")
def 列跳变():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 跳变记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/旁置")
def 列旁置():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁置簿 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


def _列批(表: str):
    conn = 连接()
    try:
        out = []
        for r in conn.execute(f"SELECT * FROM {表} ORDER BY 时刻 DESC LIMIT 40"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d.get("报告") or "{}")
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/装载批次")
def 列装载批():
    return _列批("装载批次")


@路由.get("/抽取批次")
def 列抽取批():
    return _列批("抽取批次")


@路由.get("/回放批次")
def 列回放批():
    return _列批("回放批次")


@路由.get("/夹具")
def 列夹具():
    if not 夹具目录.exists():
        return []
    return sorted(p.name for p in 夹具目录.glob("*.json"))


@路由.post("/装载")
def 执行装载(体: 装载请求):
    try:
        return 装载.装载流水(体.流水, 体.批次编号, 体.解封手续)
    except 迟到补抽.并发冲突 as e:
        raise HTTPException(409, str(e)) from e
    except 跨日水位账.跨日拒绝 as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class 夹具请求(BaseModel):
    名: str


@路由.post("/装载夹具/{名}")
def 装载夹具路径(名: str):
    return _装载夹具文件(名)


@路由.post("/装载夹具")
def 装载夹具体(体: 夹具请求):
    return _装载夹具文件(体.名)


def _装载夹具文件(名: str):
    path = 夹具目录 / 名
    if not path.exists():
        raise HTTPException(404, f"夹具不存在: {名}")
    data = json.loads(path.read_text(encoding="utf-8"))
    流水 = data.get("流水") or data.get("事件") or []
    try:
        return 装载.装载流水(
            流水, str(data.get("批次编号") or ""), str(data.get("解封手续") or "")
        )
    except 迟到补抽.并发冲突 as e:
        raise HTTPException(409, str(e)) from e
    except 跨日水位账.跨日拒绝 as e:
        raise HTTPException(409, str(e)) from e


@路由.post("/抽取")
def 执行抽取(体: 营业日请求):
    try:
        return 抽取.日终抽取(体.营业日, 体.批次编号, 体.解封手续)
    except 跨日水位账.跨日拒绝 as e:
        raise HTTPException(409, str(e)) from e
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            raise _并发转409(e) from e
        raise
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/回放")
def 执行回放(体: 营业日请求):
    try:
        return 回放.回放核对(体.营业日, 体.批次编号)
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            raise _并发转409(e) from e
        raise
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/重置业务库")
def 重置():
    """开发冒烟用：清业务表并保留账户与台参。"""
    conn = 连接()
    try:
        for t in (
            "变动流水",
            "抽取批次",
            "周期快照",
            "回放批次",
            "差额行",
            "断档记录",
            "跳变记录",
            "旁置簿",
            "装载批次",
            "迟到处置单",
            "跨日水位账表",
            "营业日封印",
            "封印手续",
        ):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        return {"完成": True, **目录.总览()}
    finally:
        conn.close()


@路由.get("/核证/跨日水位")
def 取核证_21(键: str | None = None):
    """跨日水位账只读核证：水位号、归属日、valid、钉法、封印现场。"""
    conn = 连接()
    try:
        return 跨日水位账.查现场(conn, 键)
    finally:
        conn.close()


@路由.get("/跨日水位")
def 列跨日水位(水位号: str = "", 流水号: str = "", 账户键: str = "", 归属日: str = ""):
    """跨日水位账只读查询（水位号/流水号/账户/归属日筛选），供流水页与台面联动。"""
    conn = 连接()
    try:
        return [跨日水位账.核证行(r) for r in 跨日水位账.列水位(conn, 水位号, 流水号, 账户键, 归属日)]
    finally:
        conn.close()


@路由.post("/核证/跨日水位/巡检")
def 巡检核证_21(payload: dict | None = None):
    return 跨日水位账.巡检包(payload or {})


@路由.get("/封印")
def 列封印():
    conn = 连接()
    try:
        return 跨日水位账.列封印(conn)
    finally:
        conn.close()


@路由.get("/封印/手续")
def 列封印手续(营业日: str = ""):
    conn = 连接()
    try:
        return 跨日水位账.列封印手续(conn, 营业日)
    finally:
        conn.close()


@路由.post("/封印")
def 执行封印(体: 封印请求):
    conn = 连接()
    try:
        立即事务(conn)
        try:
            报 = 跨日水位账.封印(conn, 体.营业日, 体.批次编号, 体.手续编号)
            conn.commit()
            return 报
        except Exception:
            conn.rollback()
            raise
    except 跨日水位账.跨日拒绝 as e:
        raise HTTPException(409, str(e)) from e
    finally:
        conn.close()


@路由.post("/解封")
def 执行解封(体: 封印请求):
    conn = 连接()
    try:
        立即事务(conn)
        try:
            报 = 跨日水位账.解封(conn, 体.营业日, 体.批次编号, 体.手续编号, 体.理由)
            conn.commit()
            return 报
        except Exception:
            conn.rollback()
            raise
    except 跨日水位账.跨日拒绝 as e:
        raise HTTPException(409, str(e)) from e
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

