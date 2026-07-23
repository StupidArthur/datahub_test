"""sys.path 设置:复用兄弟目录 tpt_api / ua_tpt_manager 的模块。

ua_tpt_manager 的模块用扁平 import(`from app_config import ...`),所以要把它的
目录本身加进 sys.path;tpt_api 同理(`from tpt_api import AlgAPI`)。
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent  # F:\github\supcon_tools

for _sub in ("tpt_api/python", "ua_tpt_manager"):
    _p = str(_REPO / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
