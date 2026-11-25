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
