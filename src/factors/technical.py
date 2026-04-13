"""技术面因子 - 纯函数"""

import pandas as pd
import numpy as np


def calc_price_vs_ma(daily_df: pd.DataFrame, period: int = 20) -> pd.Series:
    """价格相对均线偏离度 (%)

    Args:
        daily_df: 日线行情DataFrame
        period: 均线周期

    Returns:
        Series, index=code, value=偏离度百分比
    """
    def deviation(group):
        if len(group) < period:
            return np.nan
        group = group.sort_values("date")
        ma = group["close"].rolling(period).mean()
        return (group["close"].iloc[-1] / ma.iloc[-1] - 1) * 100

    return daily_df.groupby("code").apply(deviation)


def calc_ma_slope(daily_df: pd.DataFrame, period: int = 20) -> pd.Series:
    """均线斜率（归一化）

    用最近5天的MA变化率来衡量趋势方向

    Args:
        daily_df: 日线行情DataFrame
        period: 均线周期

    Returns:
        Series, index=code, value=斜率百分比
    """
    def slope(group):
        if len(group) < period + 5:
            return np.nan
        group = group.sort_values("date")
        ma = group["close"].rolling(period).mean()
        ma_recent = ma.iloc[-5:]
        if ma_recent.iloc[0] == 0:
            return np.nan
        return (ma_recent.iloc[-1] / ma_recent.iloc[0] - 1) * 100

    return daily_df.groupby("code").apply(slope)


def calc_momentum(daily_df: pd.DataFrame, period: int = 20) -> pd.Series:
    """N日动量（涨跌幅 %）

    Args:
        daily_df: 日线行情DataFrame
        period: 回看天数

    Returns:
        Series, index=code, value=涨跌幅
    """
    def mom(group):
        if len(group) < period:
            return np.nan
        group = group.sort_values("date")
        return (group["close"].iloc[-1] / group["close"].iloc[-period] - 1) * 100

    return daily_df.groupby("code").apply(mom)


def calc_volatility(daily_df: pd.DataFrame, period: int = 20) -> pd.Series:
    """N日年化波动率 (%)

    Args:
        daily_df: 日线行情DataFrame
        period: 计算周期

    Returns:
        Series, index=code, value=年化波动率
    """
    def vol(group):
        if len(group) < period:
            return np.nan
        group = group.sort_values("date")
        returns = group["close"].pct_change()
        return returns.tail(period).std() * (252 ** 0.5) * 100

    return daily_df.groupby("code").apply(vol)


def calc_max_drawdown(daily_df: pd.DataFrame, period: int = 60) -> pd.Series:
    """N日最大回撤 (%)

    Args:
        daily_df: 日线行情DataFrame
        period: 回看天数

    Returns:
        Series, index=code, value=最大回撤（正数表示回撤幅度）
    """
    def max_dd(group):
        if len(group) < period:
            group_tail = group.sort_values("date")
        else:
            group_tail = group.sort_values("date").tail(period)

        prices = group_tail["close"]
        cummax = prices.cummax()
        drawdown = (cummax - prices) / cummax * 100
        return drawdown.max()

    return daily_df.groupby("code").apply(max_dd)


def calc_rsi(daily_df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI相对强弱指标

    RSI = 100 - 100/(1 + avg_gain/avg_loss)

    Args:
        daily_df: 日线行情DataFrame
        period: RSI周期

    Returns:
        Series, index=code, value=RSI值(0-100)
    """
    def rsi(group):
        if len(group) < period + 1:
            return np.nan
        group = group.sort_values("date")
        delta = group["close"].diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.rolling(period, min_periods=period).mean()
        avg_loss = loss.rolling(period, min_periods=period).mean()
        last_avg_gain = avg_gain.iloc[-1]
        last_avg_loss = avg_loss.iloc[-1]
        if last_avg_loss == 0:
            return 100.0
        rs = last_avg_gain / last_avg_loss
        return 100 - 100 / (1 + rs)

    return daily_df.groupby("code").apply(rsi)


def calc_macd_signal(daily_df: pd.DataFrame) -> pd.Series:
    """MACD信号 - MACD柱状图值(DIF-DEA)

    正值看多，负值看空

    Args:
        daily_df: 日线行情DataFrame

    Returns:
        Series, index=code, value=MACD柱状图值
    """
    def macd(group):
        if len(group) < 35:
            return np.nan
        group = group.sort_values("date")
        close = group["close"]
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_hist = (dif - dea) * 2
        return macd_hist.iloc[-1]

    return daily_df.groupby("code").apply(macd)


def calc_bollinger_width(daily_df: pd.DataFrame, period: int = 20) -> pd.Series:
    """布林带宽度

    (upper - lower) / middle * 100，收窄预示大波动

    Args:
        daily_df: 日线行情DataFrame
        period: 计算周期

    Returns:
        Series, index=code, value=布林带宽度百分比
    """
    def boll(group):
        if len(group) < period:
            return np.nan
        group = group.sort_values("date")
        close = group["close"]
        ma = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = ma + 2 * std
        lower = ma - 2 * std
        last_ma = ma.iloc[-1]
        if last_ma == 0:
            return np.nan
        width = (upper.iloc[-1] - lower.iloc[-1]) / last_ma * 100
        return width

    return daily_df.groupby("code").apply(boll)


def calc_volume_price_divergence(daily_df: pd.DataFrame, period: int = 20) -> pd.Series:
    """量价背离因子

    价格创新高但成交量未创新高 → 负值（看空信号）
    价格创新低但成交量未创新低 → 正值（看多信号）

    Args:
        daily_df: 日线行情DataFrame
        period: 回看天数

    Returns:
        Series, index=code, value=背离信号值
    """
    def divergence(group):
        if len(group) < period:
            return np.nan
        group = group.sort_values("date")
        recent = group.tail(period)
        close = recent["close"]
        volume = recent["volume"]

        current_price = close.iloc[-1]
        current_vol = volume.iloc[-1]
        hist_high = close.iloc[:-1].max()
        hist_low = close.iloc[:-1].min()
        vol_high = volume.iloc[:-1].max()
        vol_low = volume.iloc[:-1].min()

        # 价格创新高但量未创新高 → 顶背离（看空）
        if current_price >= hist_high and current_vol < vol_high:
            return -1.0
        # 价格创新低但量未创新低 → 底背离（看多）
        if current_price <= hist_low and current_vol > vol_low:
            return 1.0
        return 0.0

    return daily_df.groupby("code").apply(divergence)


def calc_turnover_rate_change(daily_df: pd.DataFrame, period: int = 5) -> pd.Series:
    """换手率变化

    近N日平均换手率 / 20日平均换手率 - 1
    换手率突增可能有主力进出

    Args:
        daily_df: 日线行情DataFrame
        period: 近N日

    Returns:
        Series, index=code, value=换手率变化比率
    """
    def turnover_change(group):
        if len(group) < 20:
            return np.nan
        group = group.sort_values("date")
        recent_avg = group["turnover"].tail(period).mean()
        base_avg = group["turnover"].tail(20).mean()
        if base_avg == 0:
            return np.nan
        return recent_avg / base_avg - 1

    return daily_df.groupby("code").apply(turnover_change)


def calc_amplitude(daily_df: pd.DataFrame, period: int = 10) -> pd.Series:
    """日内振幅N日均值

    (high - low) / pre_close 的N日均值
    振幅大=多空分歧大

    Args:
        daily_df: 日线行情DataFrame
        period: 计算周期

    Returns:
        Series, index=code, value=平均振幅百分比
    """
    def amp(group):
        if len(group) < period:
            return np.nan
        group = group.sort_values("date")
        recent = group.tail(period)
        pre_close = recent["pre_close"].replace(0, np.nan)
        amplitude = (recent["high"] - recent["low"]) / pre_close * 100
        return amplitude.mean()

    return daily_df.groupby("code").apply(amp)


def calc_atr(daily_df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR (Average True Range) - 真实波幅均值

    经典波动率因子，广泛用于仓位管理：
    - ATR大 → 波动大 → 仓位应减少
    - ATR小 → 波动小 → 仓位可增大
    参考: Wilder (1978), Qlib/聚宽等主流量化框架

    TR = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = SMA(TR, period)

    Args:
        daily_df: 日线行情DataFrame
        period: ATR周期

    Returns:
        Series, index=code, value=ATR占收盘价百分比(归一化)
    """
    def atr(group):
        if len(group) < period + 1:
            return np.nan
        group = group.sort_values("date")
        high = group["high"]
        low = group["low"]
        prev_close = group["close"].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        atr_val = tr.rolling(period).mean().iloc[-1]
        close_val = group["close"].iloc[-1]
        if close_val == 0 or pd.isna(atr_val):
            return np.nan
        return atr_val / close_val * 100  # 归一化为百分比

    return daily_df.groupby("code").apply(atr)


def calc_volume_trend(daily_df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    """成交量趋势因子 (简化版Klinger思路)

    短期均量 vs 长期均量，结合价格趋势方向加权：
    - 价涨 + 量增 → 强势
    - 价跌 + 量缩 → 弱势

    Args:
        daily_df: 日线行情DataFrame
        fast: 短期天数
        slow: 长期天数

    Returns:
        Series, index=code, value=成交量趋势信号
    """
    def vtrend(group):
        if len(group) < slow:
            return np.nan
        group = group.sort_values("date")
        recent = group.tail(slow)
        vol_fast = recent["volume"].tail(fast).mean()
        vol_slow = recent["volume"].mean()
        if vol_slow == 0:
            return np.nan
        vol_signal = vol_fast / vol_slow - 1  # 量比变化
        # 价格趋势方向
        price_change = (recent["close"].iloc[-1] / recent["close"].iloc[-fast] - 1)
        # 同向加强，反向减弱
        return vol_signal * np.sign(price_change) if price_change != 0 else vol_signal * 0.5

    return daily_df.groupby("code").apply(vtrend)
