"""時系列のOOS（学習期間外）分割。未来リーク防止のため日付で厳密に分ける。"""

import pandas as pd


def time_split(df: pd.DataFrame, cutoff: str, date_col: str = "_race_date"):
    """cutoff 未満を train、cutoff 以降を test として返す。

    Returns: (train_df, test_df)
    """
    dates = pd.to_datetime(df[date_col])
    cut = pd.to_datetime(cutoff)
    train = df[dates < cut].copy()
    test = df[dates >= cut].copy()
    return train, test
