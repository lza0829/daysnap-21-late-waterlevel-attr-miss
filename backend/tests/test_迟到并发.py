"""装载（迟到入账）与抽取并发：失败闭夹具。

硬约束：交叉并发时要么串行成功（流水与处置单同事务可见），
要么锁冲突整体回滚；禁止“流水已入而处置双无”的半写状态。
"""

import sqlite3
import threading

import pytest

from app.db import 连接
from app.services import 迟到补抽, 抽取, 装载
from app.services.迟到补抽 import 并发冲突

日 = "2026-11-20"


def _先抽基线():
    装载.装载流水(
        [{"流水号": "基-甲", "账户键": "户甲", "营业日": 日, "变动额": 4000}],
        "批-基",
    )
    抽取.日终抽取(日, "抽-基")


def test_锁等待超时_装载失败闭_无半写(库):
    """持写锁的抽取未释放时，装载必须超时回滚，不留流水也不留孤证。"""
    _先抽基线()
    事件 = [{"流水号": "锁-甲-迟", "账户键": "户甲", "营业日": 日, "变动额": 900}]
    持锁 = 连接()
    持锁.execute("BEGIN IMMEDIATE")  
    try:
        with pytest.raises(并发冲突):
            装载.装载流水(事件, "批-撞锁")
    finally:
        持锁.rollback()
        持锁.close()

    conn = 连接()
    try:
        assert conn.execute(
            "SELECT COUNT(*) c FROM 变动流水 WHERE 流水号='锁-甲-迟'"
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM 迟到处置单 WHERE 流水号='锁-甲-迟'"
        ).fetchone()["c"] == 0
        
        assert conn.execute(
            "SELECT COUNT(*) c FROM 装载批次 WHERE 编号='批-撞锁'"
        ).fetchone()["c"] == 0
    finally:
        conn.close()


def test_真实并发_不变量_流水与处置永不离(库):
    """多线程同时装载迟到与抽取：任何结局下，已入流水必有处置证据或整批不在。"""
    _先抽基线()
    屏障 = threading.Barrier(2)
    结局: dict = {}

    def 装():
        屏障.wait()
        try:
            结局["装"] = 装载.装载流水(
                [{"流水号": "并发-甲-迟", "账户键": "户甲", "营业日": 日, "变动额": 1700}],
                "批-并发装",
            )
        except (并发冲突, sqlite3.OperationalError) as e:
            结局["装"] = f"冲突:{type(e).__name__}"

    def 抽():
        屏障.wait()
        try:
            结局["抽"] = 抽取.日终抽取(日, "抽-并发")
        except sqlite3.OperationalError as e:
            结局["抽"] = f"冲突:{type(e).__name__}"

    t1 = threading.Thread(target=装)
    t2 = threading.Thread(target=抽)
    t1.start(); t2.start()
    t1.join(); t2.join()

    conn = 连接()
    try:
        流水在 = conn.execute(
            "SELECT COUNT(*) c FROM 变动流水 WHERE 流水号='并发-甲-迟'"
        ).fetchone()["c"]
        处置 = conn.execute(
            "SELECT * FROM 迟到处置单 WHERE 流水号='并发-甲-迟'"
        ).fetchall()
        if 流水在:
            
            assert len(处置) == 1, "流水已入却无迟到处置证据，违反失败闭"
            assert 处置[0]["valid"] == 1
            assert 处置[0]["状态"] in {"待处置", "已纠偏"}
            
        else:
            assert len(处置) == 0, "处置单不得孤悬于回滚流水之外"
    finally:
        conn.close()


def test_并发夹具文件_双账户同批原子(库):
    """走夹具载荷：整批两账户流水同事务，冲突时双账户都不得半写。"""
    _先抽基线()
    import json
    from pathlib import Path

    夹具 = Path(__file__).resolve().parent.parent.parent / "fixtures" / "迟到装载抽取并发.json"
    数据 = json.loads(夹具.read_text(encoding="utf-8"))
    持锁 = 连接()
    持锁.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(并发冲突):
            装载.装载流水(数据["流水"], 数据["批次编号"])
    finally:
        持锁.rollback()
        持锁.close()

    conn = 连接()
    try:
        for 号 in ("并发-甲-迟", "并发-乙-迟"):
            assert conn.execute(
                "SELECT COUNT(*) c FROM 变动流水 WHERE 流水号=?", (号,)
            ).fetchone()["c"] == 0
            assert conn.execute(
                "SELECT COUNT(*) c FROM 迟到处置单 WHERE 流水号=?", (号,)
            ).fetchone()["c"] == 0
    finally:
        conn.close()


def test_抽取撞装载锁_同样失败闭(库):
    """反向交叉：装载持锁时抽取须等待后串行或冲突，绝不允许无处置的盖写。"""
    _先抽基线()
    屏障 = threading.Barrier(2)
    结局: dict = {}

    def 装():
        conn = 连接()
        try:
            from app.db import 立即事务
            立即事务(conn)
            屏障.wait()  
            conn.execute(
                "INSERT INTO 变动流水(流水号, 账户键, 营业日, 发生时, 变动额, 摘要, 批次编号, 命运) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("反向-迟", "户甲", 日, f"{日}T20:00:00Z", 600, "反向并发", "批-反", "已入账"),
            )
            迟到补抽.登记迟到处置(conn, "反向-迟", "户甲", 日, "批-反")
            conn.commit()
            结局["装"] = "ok"
        except Exception as e:  
            conn.rollback()
            结局["装"] = f"冲突:{type(e).__name__}"
        finally:
            conn.close()

    def 抽():
        屏障.wait()
        try:
            结局["抽"] = 抽取.日终抽取(日, "抽-反向")
        except sqlite3.OperationalError as e:
            结局["抽"] = f"冲突:{type(e).__name__}"

    t1 = threading.Thread(target=装)
    t2 = threading.Thread(target=抽)
    t1.start(); t2.start()
    t1.join(); t2.join()

    conn = 连接()
    try:
        流水在 = conn.execute(
            "SELECT COUNT(*) c FROM 变动流水 WHERE 流水号='反向-迟'"
        ).fetchone()["c"]
        处置 = conn.execute(
            "SELECT COUNT(*) c FROM 迟到处置单 WHERE 流水号='反向-迟'"
        ).fetchone()["c"]
        assert 流水在 == 处置, "装载/抽取任一方向交叉，流水与处置都必须同生共死"
    finally:
        conn.close()
