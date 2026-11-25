"""跨日水位账 · 只读核证接口与封印页协同（HTTP 端到端）。"""

import pytest
from fastapi.testclient import TestClient

D1 = "2026-11-01"
D3 = "2026-11-03"


@pytest.fixture()
def 客户端(库):
    from app.main import app

    with TestClient(app) as c:
        yield c


def _备(客户端):
    客户端.post("/api/装载", json={"批次编号": "h-基", "流水": [
        {"流水号": "h-D1", "账户键": "户甲", "营业日": D1, "变动额": 10000},
        {"流水号": "h-D3", "账户键": "户甲", "营业日": D3, "变动额": 500},
    ]})
    客户端.post("/api/抽取", json={"营业日": D1, "批次编号": "h-抽D1"})
    客户端.post("/api/抽取", json={"营业日": D3, "批次编号": "h-抽D3"})
    r = 客户端.post("/api/封印", json={"营业日": D1, "批次编号": "h-封", "手续编号": "手续-封-D1"})
    assert r.status_code == 200 and r.json()["状态"] == "已封印"


def _余额(c: TestClient, 日: str):
    行 = c.get(f"/api/快照?营业日={日}&账户键=户甲").json()
    assert len(行) == 1
    return 行[0]["余额"], 行[0]["版本号"]


def test_核证接口_空水位_valid钉法(客户端):
    r = 客户端.get("/api/核证/跨日水位").json()
    assert r["valid"] is True and r["钉法"] == "价值日"
    assert r["水位"] == []
    assert isinstance(r["封印"], list)


def test_封印后迟到无解封_409_两日正式不变(客户端):
    _备(客户端)
    r = 客户端.post("/api/装载", json={"批次编号": "h-迟", "流水": [
        {"流水号": "h-迟D1", "账户键": "户甲", "营业日": D1, "到达营业日": D3, "变动额": 700},
    ]})
    assert r.status_code == 409
    assert _余额(客户端, D1) == (10000, 1)
    assert _余额(客户端, D3) == (500, 1)
    # 水位账、流水都不得残留。
    assert 客户端.get("/api/跨日水位").json() == []


def test_持解封迟到_水位可查_D1动D3不动(客户端):
    _备(客户端)
    r = 客户端.post("/api/装载", json={
        "批次编号": "h-迟解封",
        "解封手续": "手续-解封-D1-001",
        "流水": [
            {"流水号": "h-迟D1-解封", "账户键": "户甲", "营业日": D1, "到达营业日": D3, "变动额": 700},
        ],
    })
    assert r.status_code == 200 and r.json()["跨日水位"] == 1

    # 只读核证接口：水位号、归属日、valid 显式可查。
    核 = 客户端.get("/api/核证/跨日水位?键=h-迟D1-解封").json()
    assert 核["valid"] is True and 核["钉法"] == "价值日"
    assert len(核["水位"]) == 1
    w = 核["水位"][0]
    assert w["归属日"] == D1
    assert w["价值日"] == D1
    assert w["到达营业日"] == D3
    assert w["valid"] is True and w["水位号"]

    水位页 = 客户端.get("/api/跨日水位?流水号=h-迟D1-解封").json()
    assert len(水位页) == 1 and 水位页[0]["归属日"] == D1
    assert 水位页[0]["valid"] is True

    # 流水页带水位列。
    流 = {x["流水号"]: x for x in 客户端.get(f"/api/流水?营业日={D1}").json()}
    assert 流["h-迟D1-解封"]["水位账号"] == w["水位号"]
    assert 流["h-迟D1-解封"]["水位归属日"] == D1

    # 甲口径：重抽价值日 D1 才把净额落到 D1；D3 正式镜不动。
    客户端.post("/api/抽取", json={"营业日": D1, "批次编号": "h-抽D1补", "解封手续": "手续-解封-D1-001"})
    assert _余额(客户端, D1) == (10700, 2)
    assert _余额(客户端, D3) == (500, 1)

    # 归位后状态闭合。
    核2 = 客户端.get("/api/核证/跨日水位?键=h-迟D1-解封").json()["水位"][0]
    assert 核2["状态"] == "已归位" and 核2["结算批次编号"] == "h-抽D1补"


def test_未解封抽取已封印日_409(客户端):
    _备(客户端)
    r = 客户端.post("/api/抽取", json={"营业日": D1, "批次编号": "h-再抽"})
    assert r.status_code == 409
    assert _余额(客户端, D1) == (10000, 1)


def test_解封接口_无手续409_有手续放行(客户端):
    _备(客户端)
    r = 客户端.post("/api/解封", json={"营业日": D1, "批次编号": "h-解", "手续编号": ""})
    assert r.status_code == 409
    r = 客户端.post("/api/解封", json={"营业日": D1, "批次编号": "h-解", "手续编号": "手续-解-D1"})
    assert r.status_code == 200 and r.json()["状态"] == "已解封"
    封印 = {x["营业日"]: x for x in 客户端.get("/api/封印").json()}
    assert 封印[D1]["状态"] == "已解封"
    手续 = 客户端.get(f"/api/封印/手续?营业日={D1}").json()
    assert any(h["动作"] == "解封" and h["手续编号"] == "手续-解-D1" for h in 手续)


def test_跨日水位夹具文件_封印后拒绝(客户端):
    import json
    from pathlib import Path

    根 = Path(__file__).resolve().parent.parent.parent / "fixtures"
    基 = json.loads((根 / "跨日水位_基线.json").read_text(encoding="utf-8"))
    # 夹具基线用 D1/D3 日期与默认种子户一致。
    客户端.post("/api/装载夹具", json={"名": "跨日水位_基线.json"})
    客户端.post("/api/抽取", json={"营业日": D1, "批次编号": "j-D1"})
    客户端.post("/api/抽取", json={"营业日": D3, "批次编号": "j-D3"})
    客户端.post("/api/封印", json={"营业日": D1, "批次编号": "j-封", "手续编号": "j-手"})
    r = 客户端.post("/api/装载夹具", json={"名": "跨日水位_封印后迟到.json"})
    assert r.status_code == 409
    assert _余额(客户端, D1)[0] == 10000 and _余额(客户端, D3)[0] == 500


def test_跨日水位夹具文件_解封后迟到D1动D3不动(客户端):
    客户端.post("/api/装载夹具", json={"名": "跨日水位_基线.json"})
    客户端.post("/api/抽取", json={"营业日": D1, "批次编号": "j-D1"})
    客户端.post("/api/抽取", json={"营业日": D3, "批次编号": "j-D3"})
    客户端.post("/api/封印", json={"营业日": D1, "批次编号": "j-封", "手续编号": "j-封手"})
    r = 客户端.post("/api/装载夹具", json={"名": "跨日水位_解封后迟到.json"})
    assert r.status_code == 200 and r.json()["跨日水位"] == 1
    # 水位可查、归属价值日。
    核 = 客户端.get("/api/核证/跨日水位?键=水位-甲-迟D1-解封").json()
    assert 核["水位"] and 核["水位"][0]["归属日"] == D1
    # 甲口径：重抽 D1 才落净额；D3 正式镜不动。
    客户端.post("/api/抽取", json={"营业日": D1, "批次编号": "j-D1补", "解封手续": "手续-解封-D1-001"})
    assert _余额(客户端, D1) == (10700, 2)
    assert _余额(客户端, D3) == (500, 1)
