"""EvolverAgent 五维进化系统 — 闭源核心

开源用户：能看到接口，运行时降级为空实现
Pro用户：加载proprietary/*.pyd，获得完整进化能力

这个文件是开源侧的接口定义 + 降级实现。
闭源实现在 proprietary/ 目录下，编译为.pyd分发。
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import IntEnum
from typing import Any, Optional

import pandas as pd
from loguru import logger


# ============================================================
# 进化安全等级
# ============================================================

class ApprovalLevel(IntEnum):
    AUTO = 0          # 全自动执行
    NOTIFY = 1        # 通知用户，自动执行
    APPROVAL = 2      # 需要用户明确审批
    ADVISORY = 3      # 仅建议，不执行


# ============================================================
# 进化事件记录
# ============================================================

class EvolutionEvent:
    """一次进化动作的完整记录"""
    dimension: str         # signal/strategy/architecture/ability/interaction
    action: str            # adjust_weight/register_factor/...
    target: str            # 具体对象
    before_value: Any
    after_value: Any
    trigger: str           # 触发原因
    approval_level: ApprovalLevel
    result: str            # success/failed/rolled_back
    timestamp: str
    notes: str = ""


# ============================================================
# 五维进化器基类
# ============================================================

class BaseEvolver(ABC):
    """进化器基类 — 闭源模块必须实现这些接口"""
    
    @abstractmethod
    def get_status(self) -> dict:
        """获取当前进化状态"""
        ...
    
    @abstractmethod
    def get_log(self, days: int = 30) -> pd.DataFrame:
        """获取进化日志"""
        ...


class SignalEvolver(BaseEvolver):
    """D1: 信号进化 — 因子级"""
    
    @abstractmethod
    def daily_ic_track(self, data: dict, date: str) -> dict:
        """每日IC追踪 + 权重自动调整"""
        ...
    
    @abstractmethod
    async def weekly_factor_discovery(self, data: dict, date: str) -> dict:
        """每周LLM提出新因子假设"""
        ...
    
    @abstractmethod
    def monthly_factor_review(self) -> dict:
        """每月因子体系review"""
        ...


class StrategyEvolver(BaseEvolver):
    """D2: 策略进化"""
    
    @abstractmethod
    def weekly_param_tune(self, performance_data: dict) -> dict:
        """每周策略参数微调"""
        ...
    
    @abstractmethod
    async def monthly_diagnosis(self, date: str) -> dict:
        """每月策略全面体检"""
        ...
    
    @abstractmethod
    async def failure_postmortem(self, trade_data: dict) -> dict:
        """失败交易复盘"""
        ...


class ArchitectureEvolver(BaseEvolver):
    """D3: 架构进化"""
    
    @abstractmethod
    def profile_performance(self) -> dict:
        """运行时性能profiling"""
        ...
    
    @abstractmethod
    def auto_optimize(self, bottleneck: dict) -> Optional[EvolutionEvent]:
        """自动算法优化（Level 0）"""
        ...
    
    @abstractmethod
    async def suggest_code_improvements(self) -> list[dict]:
        """代码改进建议（Level 2）"""
        ...
    
    @abstractmethod
    async def generate_system_report(self) -> dict:
        """系统健康报告（Level 3）"""
        ...


class AbilityEvolver(BaseEvolver):
    """D4: 能力进化"""
    
    @abstractmethod
    async def discover_new_tools(self) -> list[dict]:
        """发现并注册新工具"""
        ...
    
    @abstractmethod
    def audit_data_sources(self) -> dict:
        """数据源健康审计"""
        ...
    
    @abstractmethod
    async def learn_skill(self, description: str) -> Optional[str]:
        """学习新技能"""
        ...
    
    @abstractmethod
    def evaluate_agent_split(self) -> list[dict]:
        """评估是否需要新Agent"""
        ...


class InteractionEvolver(BaseEvolver):
    """D5: 交互进化"""
    
    @abstractmethod
    def update_profile(self, interaction: dict) -> dict:
        """更新用户画像"""
        ...
    
    @abstractmethod
    def calibrate_proactivity(self) -> dict:
        """校准推送节奏"""
        ...
    
    @abstractmethod
    def get_proactivity_config(self) -> dict:
        """获取当前主动性配置"""
        ...
    
    @abstractmethod
    def get_user_profile(self) -> dict:
        """获取用户画像"""
        ...


# ============================================================
# EvolverAgent 总调度
# ============================================================

class EvolverAgent:
    """进化Agent总调度 — 五维进化统一入口
    
    开源版: 所有方法返回空结果，不执行进化
    Pro版: 加载闭源实现，完整进化能力
    """
    
    def __init__(self, store=None, engine=None, llm_client=None):
        self.store = store
        self.engine = engine
        self.llm_client = llm_client
        self._pro = False  # 是否加载了闭源模块
        
        # 尝试加载闭源模块
        self._load_proprietary()
    
    def _load_proprietary(self):
        """尝试加载闭源进化模块"""
        try:
            from proprietary.evolver_impl import (
                SignalEvolverImpl,
                StrategyEvolverImpl,
                ArchitectureEvolverImpl,
                AbilityEvolverImpl,
                InteractionEvolverImpl,
            )
            self.signal = SignalEvolverImpl(self.store, self.engine, self.llm_client)
            self.strategy = StrategyEvolverImpl(self.store, self.engine, self.llm_client)
            self.architecture = ArchitectureEvolverImpl(self.store, self.engine)
            self.ability = AbilityEvolverImpl(self.store, self.llm_client)
            self.interaction = InteractionEvolverImpl()
            self._pro = True
            logger.info("✅ EvolverAgent Pro 已加载")
        except ImportError:
            self.signal = _NoopEvolver("signal")
            self.strategy = _NoopEvolver("strategy")
            self.architecture = _NoopEvolver("architecture")
            self.ability = _NoopEvolver("ability")
            self.interaction = _NoopEvolver("interaction")
            logger.info("ℹ️ EvolverAgent 开源版（无进化能力）")
    
    @property
    def is_pro(self) -> bool:
        return self._pro
    
    def get_evolution_summary(self) -> dict:
        """获取进化系统整体状态"""
        return {
            "is_pro": self._pro,
            "dimensions": {
                "signal": self.signal.get_status(),
                "strategy": self.strategy.get_status(),
                "architecture": self.architecture.get_status(),
                "ability": self.ability.get_status(),
                "interaction": self.interaction.get_status(),
            },
        }


class _NoopEvolver(BaseEvolver):
    """开源版降级实现 — 所有方法返回空结果"""
    
    def __init__(self, dimension: str):
        self.dimension = dimension
    
    def get_status(self) -> dict:
        return {"dimension": self.dimension, "status": "disabled", "note": "Pro only"}
    
    def get_log(self, days: int = 30) -> pd.DataFrame:
        return pd.DataFrame()
    
    def __getattr__(self, name):
        """其他方法统一返回空"""
        def noop(*args, **kwargs):
            logger.debug(f"EvolverAgent.{self.dimension}.{name}() — Pro only")
            return {}
        return noop
