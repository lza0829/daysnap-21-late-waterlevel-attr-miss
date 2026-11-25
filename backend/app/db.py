import os
import sqlite3
from pathlib import Path

夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))
_默认数据目录 = Path(__file__).resolve().parent.parent / "data"


def 当前库路径() -> Path:
    
    目录 = Path(os.environ.get("数据目录", _默认数据目录))
    return 目录 / "日镜账.db"



数据目录 = Path(os.environ.get("数据目录", _默认数据目录))
库路径 = 数据目录 / "日镜账.db"


def 连接() -> sqlite3.Connection:
    路径 = 当前库路径()
    路径.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(路径, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    
    锁等 = int(os.environ.get("锁等毫秒", "10000"))
    c.execute(f"PRAGMA busy_timeout = {锁等}")
    return c


def 立即事务(conn: sqlite3.Connection) -> None:
    """开启立即事务：先取 RESERVED 锁，把写冲突在事务入口暴露而不是留到半途。"""
    conn.execute("BEGIN IMMEDIATE")
