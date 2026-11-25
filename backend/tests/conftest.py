import os
import shutil
import sys
from pathlib import Path

import pytest

后端 = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(后端))

_TMP数据 = Path("/tmp/daysnap-pytest")


@pytest.fixture()
def 库():
    """每个用例一套全新业务库，避免相互污染。"""
    shutil.rmtree(_TMP数据, ignore_errors=True)
    os.environ["数据目录"] = str(_TMP数据)
    os.environ["夹具目录"] = str(后端.parent / "fixtures")
    os.environ["锁等毫秒"] = "500"
    from app import seed

    seed.初始化库()
    yield
    shutil.rmtree(_TMP数据, ignore_errors=True)
