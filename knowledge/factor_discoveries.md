# 因子发现记录

本文件记录通过LLM研究和回测验证发现的有效因子。

## 记录格式

每个因子发现包含：
- 因子名称和类别
- IC值（信息系数）
- 经济学直觉
- 计算方法
- 验证结果

## 初始因子

以下因子是系统初始配置中已包含的因子，其有效性已通过历史回测验证：

### 基本面因子
- **roe**: ROE（净资产收益率），衡量公司盈利能力
- **pe_percentile**: PE历史分位，衡量估值相对位置
- **revenue_yoy**: 营收同比增长率
- **profit_yoy**: 净利润同比增长率
- **gross_margin**: 毛利率
- **ocf_ratio**: 经营现金流/净利润
- **debt_ratio**: 资产负债率（越低越好）
- **goodwill_ratio**: 商誉/净资产（越低越好）

### 技术面因子
- **price_vs_ma20**: 价格偏离20日均线
- **price_vs_ma60**: 价格偏离60日均线
- **ma20_slope**: 20日均线斜率
- **momentum_20d**: 20日动量
- **volatility_20d**: 20日波动率（越低越好）
- **max_drawdown_60d**: 60日最大回撤（越小越好）

### 资金面因子
- **northbound_net_5d**: 北向资金5日净流入
- **northbound_consecutive_days**: 北向连续买入天数
- **main_force_net_1d**: 主力资金1日净流入
- **main_force_net_5d**: 主力资金5日净流入
- **margin_balance_change**: 融资余额变化

---

*新因子发现将自动追加到此处。*
