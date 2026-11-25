"""旧版每账日唯一快照表到版本链表的迁移。"""

from app.db import 连接


def test_旧快照迁移为v1基线且当前(库):
    
    from app import seed

    seed.初始化库()
    conn = 连接()
    conn.execute("DROP TABLE 周期快照")
    conn.execute(
        """
CREATE TABLE 周期快照 (
  快照键 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER NOT NULL,
  抽取批次编号 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '日终抽取',
  状态 TEXT NOT NULL DEFAULT '有效',
  UNIQUE(账户键, 营业日)
)
"""
    )
    conn.execute(
        "INSERT INTO 周期快照 VALUES ('户甲|2026-11-20','户甲','2026-11-20',7500,'旧批','日终抽取','有效')"
    )
    conn.commit()
    conn.close()

    seed.初始化库()
    conn = 连接()
    try:
        行 = conn.execute(
            "SELECT * FROM 周期快照 WHERE 账户键='户甲' AND 营业日='2026-11-20'"
        ).fetchone()
        assert 行["版本号"] == 1
        assert 行["余额"] == 7500
        assert 行["是否当前"] == 1
        assert 行["前序快照键"] == ""
        assert conn.execute(
            "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' AND name='周期快照_旧版'"
        ).fetchone()["c"] == 1
    finally:
        conn.close()


def test_旧水位与流水表补列(库):
    """旧库的 跨日水位账表/变动流水 缺新列时，初始化须补列且老行可读。"""
    from app import seed

    conn = 连接()
    conn.execute("DROP TABLE 变动流水")
    conn.execute(
        "CREATE TABLE 变动流水 (流水号 TEXT PRIMARY KEY, 账户键 TEXT NOT NULL, 营业日 TEXT NOT NULL, "
        "发生时 TEXT NOT NULL, 变动额 INTEGER NOT NULL, 摘要 TEXT NOT NULL DEFAULT '', "
        "批次编号 TEXT NOT NULL DEFAULT '', 命运 TEXT NOT NULL DEFAULT '已入账')"
    )
    conn.execute(
        "INSERT INTO 变动流水(流水号,账户键,营业日,发生时,变动额) VALUES ('老-1','户甲','2026-11-01','x',1)"
    )
    conn.execute("DROP TABLE 跨日水位账表")
    conn.execute(
        "CREATE TABLE 跨日水位账表 (编号 INTEGER PRIMARY KEY AUTOINCREMENT, 水位号 TEXT, 流水号 TEXT, "
        "价值日 TEXT, 到达日 TEXT, 归属日 TEXT, 状态 TEXT, 时刻 TEXT NOT NULL DEFAULT '', "
        "载荷 TEXT NOT NULL DEFAULT '{}')"
    )
    conn.commit()
    conn.close()

    seed.初始化库()
    conn = 连接()
    try:
        流水列 = {r["name"] for r in conn.execute("PRAGMA table_info(变动流水)")}
        assert {"到达日", "水位号"} <= 流水列
        老 = conn.execute("SELECT * FROM 变动流水 WHERE 流水号='老-1'").fetchone()
        assert 老["到达日"] == "" and 老["水位号"] == ""
        水位列 = {r["name"] for r in conn.execute("PRAGMA table_info(跨日水位账表)")}
        assert {"账户键", "装载批次编号", "结算批次编号", "valid", "处置时刻"} <= 水位列
        assert conn.execute(
            "SELECT COUNT(*) c FROM sqlite_master WHERE type='table' AND name='营业日封印'"
        ).fetchone()["c"] == 1
    finally:
        conn.close()
