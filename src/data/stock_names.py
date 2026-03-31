"""股票名称查找"""

import pandas as pd
from pathlib import Path

_NAMES = None

def _load():
    global _NAMES
    if _NAMES is not None:
        return _NAMES
    f = Path(__file__).resolve().parent.parent.parent / "data" / "stock_names.csv"
    if f.exists():
        df = pd.read_csv(f)
        df["code"] = df["code"].str.replace("sh.", "").str.replace("sz.", "")
        _NAMES = dict(zip(df["code"], df["code_name"]))
    else:
        _NAMES = {}
    return _NAMES


def stock_name(code: str) -> str:
    """获取股票名称，找不到返回代码"""
    names = _load()
    return names.get(code, code)


def enrich_df(df: pd.DataFrame, code_col: str = "code") -> pd.DataFrame:
    """给DataFrame加name列"""
    names = _load()
    df = df.copy()
    df["name"] = df[code_col].map(names).fillna(df[code_col])
    return df
