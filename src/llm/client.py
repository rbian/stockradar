"""LLM API调用封装模块

核心特性：
- 多模型支持（GLM-4/Qwen/DeepSeek，均兼容OpenAI API格式）
- 结果缓存（DuckDB llm_cache表，基于cache_key = hash(code + analysis_type + input_data_hash)）
- 重试机制（失败重试N次）
- 降级策略（LLM不可用时返回默认值，不影响核心流程）
- 异步批量调用（asyncio + Semaphore控制并发）
- 费用统计
"""

import asyncio
import hashlib
import json
import time
from datetime import date, datetime
from typing import Any

import pandas as pd
from loguru import logger
from openai import AsyncOpenAI

from src.infra.config import get_settings
from src.llm.parser import parse_llm_json, SCHEMAS
from src.llm.prompts import PromptManager


class LLMClient:
    """LLM API客户端

    所有LLM调用都经过此类，自动处理缓存、重试和降级。
    """

    def __init__(self, store=None):
        settings = get_settings()
        llm_cfg = settings.get("llm", {})

        self.base_url = llm_cfg.get("base_url", "")
        self.api_key = llm_cfg.get("api_key", "")
        self.model = llm_cfg.get("model", "glm-4")
        self.temperature = llm_cfg.get("temperature", 0.1)
        self.max_tokens = llm_cfg.get("max_tokens", 2000)
        self.max_concurrent = llm_cfg.get("max_concurrent", 10)
        self.retry_times = llm_cfg.get("retry_times", 2)
        self.retry_delay = llm_cfg.get("retry_delay", 2.0)
        self.cache_ttl = llm_cfg.get("cache_ttl_hours", {})

        self.store = store
        self.prompt_mgr = PromptManager()

        # 费用统计
        self._cost_stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_errors": 0,
        }

        # 延迟初始化AsyncOpenAI（使用时才创建）
        self._async_client = None

    @property
    def async_client(self) -> AsyncOpenAI:
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._async_client

    # ============ 缓存管理 ============

    def _make_cache_key(self, code: str, analysis_type: str,
                        input_data: Any) -> str:
        """生成缓存键: hash(code + analysis_type + input_data_hash)"""
        input_str = json.dumps(input_data, ensure_ascii=False, sort_keys=True, default=str)
        input_hash = hashlib.md5(input_str.encode()).hexdigest()[:16]
        raw = f"{code}|{analysis_type}|{input_hash}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cache(self, cache_key: str, analysis_type: str) -> dict | None:
        """从DuckDB缓存中查询结果

        Returns:
            缓存的解析结果dict，无缓存返回None
        """
        if self.store is None:
            return None

        try:
            prompt_hash = self.prompt_mgr.get_prompt_hash(analysis_type)
            df = self.store.query(
                "SELECT result_json, prompt_hash, created_at FROM llm_cache WHERE cache_key = ?",
                [cache_key],
            )
            if df.empty:
                return None

            row = df.iloc[0]

            # Prompt版本变更则缓存失效
            if row["prompt_hash"] != prompt_hash:
                logger.debug(f"缓存失效(prompt变更): {cache_key}")
                return None

            # TTL检查
            ttl_hours = self.cache_ttl.get(analysis_type, 24)
            if ttl_hours < 999999:  # 999999表示永不过期
                created = pd.Timestamp(row["created_at"])
                age_hours = (pd.Timestamp.now() - created).total_seconds() / 3600
                if age_hours > ttl_hours:
                    logger.debug(f"缓存过期(TTL={ttl_hours}h): {cache_key}")
                    return None

            result = json.loads(row["result_json"])
            logger.debug(f"缓存命中: {cache_key}")
            self._cost_stats["cache_hits"] += 1
            return result

        except Exception as e:
            logger.warning(f"缓存查询失败: {e}")
            return None

    def _set_cache(self, cache_key: str, code: str, analysis_type: str,
                   result: dict):
        """将结果写入缓存"""
        if self.store is None:
            return

        try:
            prompt_hash = self.prompt_mgr.get_prompt_hash(analysis_type)
            cache_df = pd.DataFrame([{
                "cache_key": cache_key,
                "code": code,
                "analysis_type": analysis_type,
                "date": date.today(),
                "result_json": json.dumps(result, ensure_ascii=False),
                "model": self.model,
                "prompt_hash": prompt_hash,
                "created_at": datetime.now(),
            }])
            self.store.upsert_df("llm_cache", cache_df, pk_cols=["cache_key"])
        except Exception as e:
            logger.warning(f"缓存写入失败: {e}")

    # ============ 单次调用 ============

    async def _call_api(self, system_prompt: str, user_prompt: str) -> str | None:
        """调用LLM API（单次，不含重试）

        Returns:
            LLM原始输出文本，失败返回None
        """
        try:
            response = await self.async_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # 统计token
            if hasattr(response, "usage") and response.usage:
                self._cost_stats["total_input_tokens"] += response.usage.prompt_tokens or 0
                self._cost_stats["total_output_tokens"] += response.usage.completion_tokens or 0

            content = response.choices[0].message.content
            return content

        except Exception as e:
            self._cost_stats["total_errors"] += 1
            logger.error(f"LLM API调用失败: {e}")
            return None

    async def _call_with_retry(self, system_prompt: str,
                               user_prompt: str) -> str | None:
        """带重试的LLM调用"""
        for attempt in range(self.retry_times + 1):
            result = await self._call_api(system_prompt, user_prompt)
            if result is not None:
                return result

            if attempt < self.retry_times:
                logger.info(f"LLM调用失败，{self.retry_delay}s后重试 "
                            f"({attempt + 1}/{self.retry_times})")
                await asyncio.sleep(self.retry_delay)

        return None

    # ============ 公开接口 ============

    async def analyze(self, code: str, analysis_type: str,
                      input_data: dict) -> dict:
        """分析单只股票（自动缓存+重试+降级）

        Args:
            code: 股票代码
            analysis_type: 分析类型 (earnings/news_sentiment/stock_review)
            input_data: 模板变量dict

        Returns:
            解析后的结果dict，LLM不可用时返回默认值
        """
        self._cost_stats["total_calls"] += 1

        # 1. 缓存检查
        cache_key = self._make_cache_key(code, analysis_type, input_data)
        cached = self._get_cache(cache_key, analysis_type)
        if cached is not None:
            return cached

        # 2. 构建Prompt
        try:
            system_prompt, user_prompt = self.prompt_mgr.get(
                analysis_type, **input_data
            )
        except Exception as e:
            logger.error(f"Prompt构建失败 [{analysis_type}]: {e}")
            return dict(SCHEMAS.get(analysis_type, {}).get("defaults", {}))

        # 3. 调用LLM（带重试）
        raw_text = await self._call_with_retry(system_prompt, user_prompt)

        if raw_text is None:
            logger.warning(f"LLM降级 [{code}][{analysis_type}]: 返回默认值")
            return dict(SCHEMAS.get(analysis_type, {}).get("defaults", {}))

        # 4. 解析输出
        result = parse_llm_json(raw_text, analysis_type)

        # 5. 写入缓存
        self._set_cache(cache_key, code, analysis_type, result)

        return result

    async def batch_analyze(self, tasks: list[dict]) -> list[dict]:
        """批量分析多只股票（异步并发）

        Args:
            tasks: [{"code": ..., "analysis_type": ..., "input_data": {...}}, ...]

        Returns:
            与tasks等长的结果列表
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _limited(task):
            async with semaphore:
                return await self.analyze(
                    task["code"], task["analysis_type"], task["input_data"]
                )

        results = await asyncio.gather(
            *[_limited(task) for task in tasks],
            return_exceptions=True,
        )

        # 异常降级
        final = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"批量分析异常 [{tasks[i]['code']}]: {r}")
                defaults = SCHEMAS.get(
                    tasks[i]["analysis_type"], {}
                ).get("defaults", {})
                final.append(dict(defaults))
            else:
                final.append(r)

        return final

    # ============ 费用统计 ============

    def get_cost_stats(self) -> dict:
        """获取费用统计"""
        return dict(self._cost_stats)

    def reset_cost_stats(self):
        """重置费用统计"""
        self._cost_stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_errors": 0,
        }

    def log_cost_summary(self):
        """打印费用摘要"""
        s = self._cost_stats
        cache_rate = (
            s["cache_hits"] / s["total_calls"] * 100
            if s["total_calls"] > 0
            else 0
        )
        logger.info(
            f"LLM费用统计: "
            f"调用{s['total_calls']}次, "
            f"缓存命中率{cache_rate:.0f}%, "
            f"输入{s['total_input_tokens']}tokens, "
            f"输出{s['total_output_tokens']}tokens, "
            f"错误{s['total_errors']}次"
        )
