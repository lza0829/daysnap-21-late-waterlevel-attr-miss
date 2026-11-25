"""跨日水位账 · 甲口径（水位钉价值日）端到端夹具。

口径硬约束（本文件显式断言）：
- 每笔跨日迟到必须与流水同票落水位账（水位号/价值日/到达营业日/归属日/valid）；
- 归属日=价值日：净额只进价值日正式镜，到达日正式镜永不含该笔净额；
- 价值日已封印：无解封手续 → 整笔拒绝，价值日与到达日正式镜皆不变；
- 伪造无水位跨日流水 → 抽取失败闭（禁止无水位双改）；
- 迟到装载与封印抢锁 → 不得双日正式同加。
"""

import sqlite3
import threading

import pytest

from app.db import 连接, 立即事务
from app.modules import 跨日水位账 as 水位
from app.modules.跨日水位账 import 跨日拒绝
from app.services import 抽取, 装载

D1 = "2026-11-01"
D3 = "2026-11-03"


def _当前余额(账户键: str, 日: str):
    conn = 连接()
    try:
        r = conn.execute(
            "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效' AND 是否当前=1",
            (账户键, 日),
        ).fetchone()
        return None if r is None else int(r["余额"])
    finally:
        conn.close()


def _当前版本(账户键: str, 日: str):
    conn = 连接()
    try:
        r = conn.execute(
            "SELECT 版本号 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态='有效' AND 是否当前=1",
            (账户键, 日),
        ).fetchone()
        return None if r is None else int(r["版本号"])
    finally:
        conn.close()


def _造_D1_D3_并封印_D1():
    """D1、D3 各抽一版，再封印 D1。返回基线余额。"""
    装载.装载流水(
        [
            {"流水号": "基-D1", "账户键": "户甲", "营业日": D1, "变动额": 10000},
            {"流水号": "基-D3", "账户键": "户甲", "营业日": D3, "变动额": 500},
        ],
        "批-基",
    )
    抽取.日终抽取(D1, "抽-D1")
    抽取.日终抽取(D3, "抽-D3")
    conn = 连接()
    try:
        立即事务(conn)
        水位.封印(conn, D1, "封-D1", "手续-封-D1")
        conn.commit()
    finally:
        conn.close()
    assert _当前余额("户甲", D1) == 10000
    assert _当前余额("户甲", D3) == 500


# ---------------------------------------------------------------- 甲：无解封整拒


def test_甲_封印后跨日迟到无解封_整笔拒绝_D1D3皆不变(库):
    _造_D1_D3_并封印_D1()
    with pytest.raises(跨日拒绝):
        装载.装载流水(
            [
                {
                    "流水号": "迟-D1",
                    "账户键": "户甲",
                    "营业日": D1,
                    "到达营业日": D3,
                    "变动额": 700,
                }
            ],
            "批-迟-无手续",
        )
    # 整笔拒绝：D1/D3 正式镜不变；流水、水位、处置均不得半写。
    assert _当前余额("户甲", D1) == 10000
    assert _当前余额("户甲", D3) == 500
    conn = 连接()
    try:
        assert conn.execute(
            "SELECT COUNT(*) c FROM 变动流水 WHERE 流水号='迟-D1'"
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM 跨日水位账表 WHERE 流水号='迟-D1'"
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM 迟到处置单 WHERE 流水号='迟-D1'"
        ).fetchone()["c"] == 0
    finally:
        conn.close()


# ---------------------------------------------------------------- 甲：持解封 → D1 动、D3 不动


def test_甲_持解封跨日迟到_净额归价值日D1_D3不变_水位可查(库):
    _造_D1_D3_并封印_D1()
    报 = 装载.装载流水(
        [
            {
                "流水号": "迟-D1-解封",
                "账户键": "户甲",
                "营业日": D1,
                "到达营业日": D3,
                "变动额": 700,
            }
        ],
        "批-迟-解封",
        解封手续="手续-解封-D1-001",
    )
    assert 报["跨日水位"] == 1

    # 水位账与流水同票写入，归属日钉价值日、valid。
    conn = 连接()
    try:
        水 = 水位.列水位(conn, 流水号="迟-D1-解封")
        assert len(水) == 1
        assert 水[0]["归属日"] == D1
        assert 水[0]["价值日"] == D1
        assert 水[0]["到达日"] == D3
        assert 水[0]["valid"] == 1
        核 = 水位.核证行(水[0])
        assert 核["归属日"] == D1 and 核["valid"] is True and 核["钉法"] == "价值日"
    finally:
        conn.close()

    # 甲口径：净额归价值日 D1，故须重抽 D1（已解封）；D3 正式镜不动。
    报2 = 抽取.日终抽取(D1, "抽-D1-补")
    assert 报2["水位归位"] >= 1
    assert _当前余额("户甲", D1) == 10700  # v2 = 10000 + 700
    assert _当前版本("户甲", D1) == 2
    assert _当前余额("户甲", D3) == 500  # 到达日 D3 不含该笔净额

    conn = 连接()
    try:
        水 = 水位.列水位(conn, 流水号="迟-D1-解封")[0]
        assert 水["状态"] == "已归位"
        assert 水["结算批次编号"] == "抽-D1-补"
    finally:
        conn.close()


# ---------------------------------------------------------------- 伪造无水位双改 → 失败闭


def test_伪造无水位跨日双改_抽取失败闭(库):
    """绕过装载直接塞一条跨日流水（无水位号），抽取价值日或到达日都必须拒绝。"""
    _造_D1_D3_并封印_D1()
    conn = 连接()
    try:
        立即事务(conn)
        conn.execute(
            "INSERT INTO 变动流水(流水号, 账户键, 营业日, 到达日, 水位号, 发生时, "
            "变动额, 摘要, 批次编号, 命运) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("伪造-双改", "户甲", D1, D3, "", f"{D3}T10:00:00Z", 900, "伪造无水位", "伪造批", "已入账"),
        )
        conn.commit()
    finally:
        conn.close()

    # 抽取价值日 D1：无水位 → 失败闭（且 D1 已封印，先被封印闸拦，同样拒绝）。
    with pytest.raises(跨日拒绝):
        抽取.日终抽取(D1, "抽-D1-伪造", 解封手续="手续-解封-伪造")
    # 抽取到达日 D3：同样不得因该伪造流水改写 D3 正式净额。
    with pytest.raises(跨日拒绝):
        抽取.日终抽取(D3, "抽-D3-伪造")

    # D1、D3 正式镜皆未被改写。
    assert _当前余额("户甲", D1) == 10000
    assert _当前余额("户甲", D3) == 500


# ---------------------------------------------------------------- 封印/解封闸


def test_抽取已封印日_无手续拒绝_持手续放行(库):
    _造_D1_D3_并封印_D1()
    with pytest.raises(跨日拒绝):
        抽取.日终抽取(D1, "抽-封日无手续")
    assert _当前版本("户甲", D1) == 1
    # 持解封手续后放行并追加版本。
    抽取.日终抽取(D1, "抽-封日持手续", 解封手续="手续-解封-D1-xyz")
    assert _当前版本("户甲", D1) == 2


def test_解封无手续拒绝(库):
    _造_D1_D3_并封印_D1()
    conn = 连接()
    try:
        立即事务(conn)
        with pytest.raises(跨日拒绝):
            水位.解封(conn, D1, "批-x", "", "无手续")
        conn.rollback()
    finally:
        conn.close()
    # 仍封印。
    conn = 连接()
    try:
        assert 水位.是否封印(conn, D1) is True
    finally:
        conn.close()


# ---------------------------------------------------------------- 并发：迟到与封印抢锁


def test_迟到装载与封印抢锁_不得双日正式同加(库):
    _造_D1_D3_并封印_D1()
    # 先解封 D1，模拟“价值日可动”的并发窗口，然后让装载迟到与再封印抢锁。
    conn = 连接()
    try:
        立即事务(conn)
        水位.解封(conn, D1, "批-预解封", "手续-预解封", "并发前置")
        conn.commit()
    finally:
        conn.close()

    屏障 = threading.Barrier(2)
    结局: dict = {}

    def 装():
        屏障.wait()
        try:
            结局["装"] = 装载.装载流水(
                [
                    {
                        "流水号": "并发-迟-D1",
                        "账户键": "户甲",
                        "营业日": D1,
                        "到达营业日": D3,
                        "变动额": 750,
                    }
                ],
                "批-并发装",
            )
        except (跨日拒绝, sqlite3.OperationalError) as e:
            结局["装"] = f"拒:{type(e).__name__}"

    def 封():
        屏障.wait()
        try:
            c = 连接()
            try:
                立即事务(c)
                水位.封印(c, D1, "批-并发封", "手续-并发封")
                c.commit()
            finally:
                c.close()
            结局["封"] = "ok"
        except sqlite3.OperationalError as e:
            结局["封"] = f"冲突:{type(e).__name__}"

    t1 = threading.Thread(target=装)
    t2 = threading.Thread(target=封)
    t1.start(); t2.start()
    t1.join(); t2.join()

    # 无论谁先：D3 正式镜绝不因该跨日迟到新增净额。
    assert _当前余额("户甲", D3) == 500, "到达日正式镜不得被跨日迟到双加"

    conn = 连接()
    try:
        流水在 = conn.execute(
            "SELECT COUNT(*) c FROM 变动流水 WHERE 流水号='并发-迟-D1'"
        ).fetchone()["c"]
        水位在 = conn.execute(
            "SELECT COUNT(*) c FROM 跨日水位账表 WHERE 流水号='并发-迟-D1'"
        ).fetchone()["c"]
        # 失败闭：流水与水位同生共死。
        assert 流水在 == 水位在, "流水已入却无水位账，违反失败闭"
        if 流水在:
            水 = 水位.列水位(conn, 流水号="并发-迟-D1")[0]
            assert 水["归属日"] == D1 and 水["valid"] == 1
    finally:
        conn.close()


# ---------------------------------------------------------------- 核证只读接口


def test_核证只读接口_水位号归属日valid(库):
    _造_D1_D3_并封印_D1()
    装载.装载流水(
        [
            {
                "流水号": "核-迟-D1",
                "账户键": "户甲",
                "营业日": D1,
                "到达营业日": D3,
                "变动额": 300,
            }
        ],
        "批-核",
        解封手续="手续-核-001",
    )
    conn = 连接()
    try:
        现 = 水位.查现场(conn, "核-迟-D1")
        assert 现["valid"] is True
        assert 现["钉法"] == "价值日"
        assert len(现["水位"]) == 1
        row = 现["水位"][0]
        assert row["归属日"] == D1
        assert row["到达营业日"] == D3
        assert row["水位号"]
        assert row["valid"] is True
    finally:
        conn.close()
