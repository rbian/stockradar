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


def calc_adx(daily_df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ADX (Average Directional Index) - 趋势强度指标

    ADX衡量趋势强度（而非方向），用于动态调整风控参数：
    - ADX < 20: 弱趋势或震荡，收紧止损(multiplier=2.0)
    - 20 <= ADX < 25: 中等趋势，标准止损(multiplier=2.5)
    - ADX >= 25: 强趋势，放宽止损避免被震荡洗出(multiplier=3.0)

    计算步骤：
    1. +DM = high - prev_high (if > low - prev_low, else 0)
    2. -DM = low - prev_low (if > high - prev_high, else 0)
    3. TR = max(high-low, |high-prev_close|, |low-prev_close|)
    4. +DI = SMA(+DM) / SMA(TR) * 100
    5. -DI = SMA(-DM) / SMA(TR) * 100
    6. DX = |+DI - -DI| / (+DI + -DI) * 100
    7. ADX = SMA(DX)

    参考: Wilder (1978),广泛应用于Qlib/Backtrader等框架

    Args:
        daily_df: 日线行情DataFrame，需包含high/low/close列
        period: ADX计算周期，默认14

    Returns:
        Series, index=code, value=ADX值(0-100)
    """
    def adx_for_group(group):
        if len(group) < period * 2:
            return np.nan

        group = group.sort_values("date")
        high = group["high"].values
        low = group["low"].values
        close = group["close"].values

        # 计算DM (Directional Movement)
        up_move = np.diff(high)
        down_move = -np.diff(low)

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # 计算TR (True Range)
        tr = np.zeros(len(group))
        for i in range(1, len(group)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )

        # 平滑处理（使用Wilder's smoothing: alpha = 1/period）
        alpha = 1.0 / period

        # 初始SMA
        tr_smooth = np.zeros_like(tr)
        plus_dm_smooth = np.zeros_like(plus_dm)
        minus_dm_smooth = np.zeros_like(minus_dm)

        # 从第period个值开始
        if len(tr) > period:
            tr_smooth[period] = np.mean(tr[1:period+1])
            plus_dm_smooth[period] = np.mean(plus_dm[:period])
            minus_dm_smooth[period] = np.mean(minus_dm[:period])

            # 使用指数移动平均平滑
            for i in range(period + 1, len(tr)):
                tr_smooth[i] = alpha * tr[i] + (1 - alpha) * tr_smooth[i-1]
                plus_dm_smooth[i] = alpha * plus_dm[i-1] + (1 - alpha) * plus_dm_smooth[i-1]
                minus_dm_smooth[i] = alpha * minus_dm[i-1] + (1 - alpha) * minus_dm_smooth[i-1]

            # 计算DI (Directional Index)
            plus_di = np.zeros_like(tr_smooth)
            minus_di = np.zeros_like(tr_smooth)

            for i in range(period, len(tr_smooth)):
                if tr_smooth[i] != 0:
                    plus_di[i] = (plus_dm_smooth[i] / tr_smooth[i]) * 100
                    minus_di[i] = (minus_dm_smooth[i] / tr_smooth[i]) * 100

            # 计算DX (Directional Index)
            dx = np.zeros_like(plus_di)
            for i in range(period, len(plus_di)):
                di_sum = plus_di[i] + minus_di[i]
                if di_sum != 0:
                    dx[i] = abs(plus_di[i] - minus_di[i]) / di_sum * 100

            # 平滑DX得到ADX
            adx = np.zeros_like(dx)
            if len(dx) > period:
                adx[period] = np.mean(dx[period:period*2])
                for i in range(period + 1, len(dx)):
                    adx[i] = alpha * dx[i] + (1 - alpha) * adx[i-1]

            return adx[-1] if not np.isnan(adx[-1]) else np.nan

        return np.nan

    return daily_df.groupby("code").apply(adx_for_group)


def get_adx_multiplier(adx_value: float) -> float:
    """根据ADX值获取ATR止损倍数

    趋势越强，止损距离越远（避免被震荡洗出）：
    - ADX < 20: 弱趋势 → multiplier = 2.0
    - 20 <= ADX < 25: 中趋势 → multiplier = 2.5
    - ADX >= 25: 强趋势 → multiplier = 3.0

    Args:
        adx_value: ADX值

    Returns:
        ATR multiplier
    """
    if adx_value < 20:
        return 2.0
    elif adx_value < 25:
        return 2.5
    else:
        return 3.0


def calc_mean_reversion_score(daily_df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    """均值回归评分因子

    衡量短期超卖/超买程度，用于捕捉反弹机会：
    - 计算短期收益率相对长期均值的偏离
    - 负偏离越大 → 超卖越严重 → 反弹概率越高（得分越高）
    - 结合换手率确认（放量下跌后反弹更可靠）

    灵感来源: mean reversion literature (De Bondt & Thaler 1985),
    je-suis-tm/quant-trading的reversal策略, 以及A股短线反弹实战

    Args:
        daily_df: 日线行情DataFrame
        fast: 短期天数
        slow: 长期天数

    Returns:
        Series, index=code, value=均值回归评分(-100~100, 越高越可能反弹)
    """
    def mrev(group):
        if len(group) < slow:
            return np.nan
        group = group.sort_values("date")
        recent = group.tail(slow)
        close = recent["close"]

        # 短期收益率
        fast_return = close.iloc[-1] / close.iloc[-fast] - 1 if len(close) >= fast else 0

        # 长期收益率均值
        daily_returns = close.pct_change().dropna()
        if len(daily_returns) < 5:
            return np.nan
        long_avg_return = daily_returns.mean()
        long_std = daily_returns.std()
        if long_std == 0:
            return np.nan

        # Z-score: 偏离程度（负偏离=超卖=高得分）
        z_score = (fast_return - fast * long_avg_return) / (np.sqrt(fast) * long_std)

        # 换手率变化确认（放量下跌后反弹更可靠）
        vol_recent = recent["volume"].tail(fast).mean()
        vol_older = recent["volume"].iloc[:-fast].mean() if len(recent) > fast else vol_recent
        vol_ratio = vol_recent / vol_older if vol_older > 0 else 1.0

        # 下跌且放量 → 更强的均值回归信号
        if fast_return < 0:
            score = abs(z_score) * min(vol_ratio, 2.0)  # cap vol_ratio at 2x
        else:
            score = -abs(z_score) * 0.5  # 上涨时不给反转分

        return np.clip(score, -100, 100)

    return daily_df.groupby("code").apply(mrev)


def calc_williams_r(daily_df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R 因子 - 超买超卖指标

    衡量当前价格在近期价格范围中的位置：
    - Williams %R = (Highest High - Close) / (Highest High - Lowest Low) * (-100)
    - 值范围: -100 到 0
    - < -80: 超卖区域（可能反弹）
    - > -20: 超买区域（可能回调）

    在选股评分中：超卖股票得分高（higher_better方向反转）
    参考: Larry Williams (1973), 广泛用于趋势反转判断

    Args:
        daily_df: 日线行情DataFrame
        period: 回看天数

    Returns:
        Series, index=code, value=Williams %R (-100 ~ 0)
    """
    def wr(group):
        if len(group) < period:
            return np.nan
        group = group.sort_values("date")
        recent = group.tail(period)
        highest = recent["high"].max()
        lowest = recent["low"].min()
        close_val = recent["close"].iloc[-1]
        if highest == lowest:
            return np.nan
        return (highest - close_val) / (highest - lowest) * (-100)

    return daily_df.groupby("code").apply(wr)


def calc_ichimoku_signal(daily_df: pd.DataFrame, tenkan: int = 9, kijun: int = 26) -> pd.Series:
    """一目均衡表信号因子 (Ichimoku Cloud)

    日本最流行的技术指标之一，综合判断趋势方向和支撑/阻力：
    - 转换线(Tenkan): (highest high + lowest low) / 2 over tenkan period
    - 基准线(Kijun): (highest high + lowest low) / 2 over kijun period
    - 信号 = 转换线相对基准线的位置 + 价格相对转换线的位置

    得分: 正值=多头信号, 负值=空头信号
    参考: 一目山人(1930s), 日本主流量化指标

    Args:
        daily_df: 日线行情DataFrame
        tenkan: 转换线周期
        kijun: 基准线周期

    Returns:
        Series, index=code, value=信号强度(-100~100)
    """
    def ichimoku(group):
        if len(group) < kijun:
            return np.nan
        group = group.sort_values("date")

        high = group["high"]
        low = group["low"]
        close = group["close"]

        # 转换线
        recent_t = group.tail(tenkan)
        tenkan_val = (recent_t["high"].max() + recent_t["low"].min()) / 2

        # 基准线
        recent_k = group.tail(kijun)
        kijun_val = (recent_k["high"].max() + recent_k["low"].min()) / 2

        close_val = close.iloc[-1]
        if kijun_val == 0:
            return np.nan

        # 信号1: 转换线 vs 基准线 (金叉/死叉方向)
        tk_signal = (tenkan_val - kijun_val) / kijun_val * 100

        # 信号2: 价格 vs 转换线 (价格在转换线上方=强势)
        pc_signal = (close_val - tenkan_val) / tenkan_val * 100

        return np.clip(tk_signal + pc_signal, -100, 100)

    return daily_df.groupby("code").apply(ichimoku)
