"""迟到处置只读接口与装载/抽取/快照/回放/流水页协同的端到端测试。"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def 客户端(库):
    from app.main import app

    with TestClient(app) as c:
        yield c


日 = "2026-11-20"


def _造双笔迟到(c: TestClient):
    c.post("/api/装载", json={"批次编号": "h-基", "流水": [
        {"流水号": "h-甲-基", "账户键": "户甲", "营业日": 日, "变动额": 7500},
    ]})
    c.post("/api/抽取", json={"营业日": 日, "批次编号": "h-抽1"})
    c.post("/api/装载", json={"批次编号": "h-迟1", "流水": [
        {"流水号": "h-甲-迟1", "账户键": "户甲", "营业日": 日, "变动额": 2000},
    ]})
    c.post("/api/抽取", json={"营业日": 日, "批次编号": "h-抽2"})
    c.post("/api/装载", json={"批次编号": "h-迟2", "流水": [
        {"流水号": "h-甲-迟2", "账户键": "户甲", "营业日": 日, "变动额": 3000},
    ]})
    c.post("/api/抽取", json={"营业日": 日, "批次编号": "h-抽3"})


def test_迟到处置只读接口_基线当前链_valid(客户端):
    _造双笔迟到(客户端)
    基线 = 客户端.get(f"/api/迟到处置/镜?账户键=户甲&营业日={日}&视角=基线").json()
    当前 = 客户端.get(f"/api/迟到处置/镜?账户键=户甲&营业日={日}&视角=当前").json()
    链 = 客户端.get(f"/api/迟到处置/镜?账户键=户甲&营业日={日}&视角=链").json()
    assert 基线["镜"]["余额"] == 7500 and 基线["镜"]["版本号"] == 1
    assert 当前["镜"]["余额"] == 12500 and 当前["镜"]["版本号"] == 3
    assert [v["余额"] for v in 链["链"]] == [7500, 9500, 12500]

    单们 = 客户端.get(f"/api/迟到处置?营业日={日}").json()
    assert len(单们) == 2
    assert all(s["valid"] == 1 and s["状态"] == "已纠偏" for s in 单们)

    r = 客户端.get(f"/api/迟到处置/镜?账户键=户甲&营业日={日}&视角=错")
    assert r.status_code == 400


def test_快照页默认当前_含历史给全链(客户端):
    _造双笔迟到(客户端)
    当前 = 客户端.get(f"/api/快照?营业日={日}&账户键=户甲").json()
    assert len(当前) == 1 and 当前[0]["余额"] == 12500 and 当前[0]["是否当前"] == 1
    全链 = 客户端.get(f"/api/快照?营业日={日}&账户键=户甲&含历史=true").json()
    assert [r["版本号"] for r in 全链] == [1, 2, 3]


def test_流水页带迟到处置列(客户端):
    _造双笔迟到(客户端)
    行 = 客户端.get(f"/api/流水?营业日={日}&账户键=户甲").json()
    by_id = {r["流水号"]: r for r in 行}
    assert by_id["h-甲-迟1"]["迟到状态"] == "已纠偏"
    assert by_id["h-甲-迟1"]["迟到valid"] == 1
    assert by_id["h-甲-基"]["迟到状态"] is None


def test_回放页守恒(客户端):
    _造双笔迟到(客户端)
    r = 客户端.post("/api/回放", json={"营业日": 日, "批次编号": "h-回放"}).json()
    assert r["通过"] is True and r["差额"] == 0
    assert 客户端.get("/api/差额").json() == []


def test_并发冲突返回409(客户端):
    c = 客户端
    c.post("/api/装载", json={"批次编号": "c-基", "流水": [
        {"流水号": "c-基1", "账户键": "户甲", "营业日": 日, "变动额": 100},
    ]})
    c.post("/api/抽取", json={"营业日": 日, "批次编号": "c-抽"})
    
    from app.db import 连接

    持锁 = 连接()
    持锁.execute("BEGIN IMMEDIATE")
    try:
        r = c.post("/api/装载", json={"批次编号": "c-撞", "流水": [
            {"流水号": "c-迟", "账户键": "户甲", "营业日": 日, "变动额": 50},
        ]})
        assert r.status_code == 409
    finally:
        持锁.rollback()
        持锁.close()
    行 = c.get("/api/流水").json()
    assert all(x["流水号"] != "c-迟" for x in 行)
    assert all(s["流水号"] != "c-迟" for s in c.get("/api/迟到处置").json())


def test_总览含迟到计数(客户端):
    _造双笔迟到(客户端)
    o = 客户端.get("/api/总览").json()
    assert o["迟到已纠偏"] == 2
    assert o["迟到待处置"] == 0
    assert o["快照版本数"] >= o["快照数"]
