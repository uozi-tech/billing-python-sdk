import asyncio
import functools
import logging
from collections.abc import Callable
from typing import Any

from .client import BillingClient, UsageData

logger = logging.getLogger(__name__)


def _mask_api_key(api_key: str) -> str:
    """掩码API Key，只显示前8位"""
    if len(api_key) > 8:
        return api_key[:8] + "*" * (len(api_key) - 8)
    else:
        return "*" * len(api_key)


def _get_billing_client() -> BillingClient | None:
    """获取全局单例 billing client"""
    if BillingClient.is_initialized():
        return BillingClient.get_instance()
    return None


def _handle_usage_reporting(
    self: Any,
    func: Callable,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    result: Any,
    module: str,
    model: str,
    usage_calculator: Callable[..., int] | None = None,
    metadata_extractor: Callable[..., dict[str, Any]] | None = None,
) -> UsageData | None:
    """处理用量上报的共同逻辑"""
    # 获取全局单例 billing client 和 logger
    billing_client = _get_billing_client()
    logger = billing_client._logger if billing_client else logging.getLogger(__name__)

    # 获取 API key
    api_key = getattr(self, "_billing_api_key", None)
    if not api_key:
        logger.warning(f"无法获取 API Key，跳过用量上报: {func.__name__}")
        return None

    # 计算用量
    usage = 1  # 默认用量
    if usage_calculator:
        try:
            calculated_usage = usage_calculator(args, kwargs, result)
            # 确保返回值是 int 类型
            if not isinstance(calculated_usage, int):
                logger.error(
                    f"用量计算函数必须返回 int 类型，实际返回: {type(calculated_usage)}"
                )
                usage = 1  # 使用默认值
            else:
                usage = calculated_usage
        except Exception as e:
            logger.error(f"用量计算失败: {e}")

    # 提取元数据
    metadata = {}
    if metadata_extractor:
        try:
            extracted_metadata = metadata_extractor(args, kwargs, result)
            # 确保返回值是字典类型
            if not isinstance(extracted_metadata, dict):
                logger.error(
                    f"元数据提取函数必须返回 dict 类型，实际返回: {type(extracted_metadata)}"
                )
                metadata = {}
            else:
                metadata = extracted_metadata
        except Exception as e:
            logger.error(f"元数据提取失败: {e}")

    # 检查 billing client 并准备上报数据
    if billing_client and isinstance(billing_client, BillingClient):
        return UsageData(
            api_key=api_key,
            module=module,
            model=model,
            usage=usage,
            metadata=metadata,
        )
    else:
        logger.warning("BillingClient 单例未初始化，跳过用量上报")
        return None


def track_usage(
    module: str,
    model: str,
    usage_calculator: Callable[..., int] | None = None,
    metadata_extractor: Callable[..., dict[str, Any]] | None = None,
) -> Callable:
    """
    用量追踪装饰器，自动上报API调用的用量信息

    Args:
        module: 模块名称 (llm/tts/asr)
        model: 模型名称
        usage_calculator: 用量计算函数，接收函数参数和返回值，返回 int 类型的用量数值
        metadata_extractor: 元数据提取函数，接收函数参数和返回值，返回 Dict[str, Any] 类型的元数据字典
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            # 执行原函数
            result = await func(self, *args, **kwargs)

            billing_client = _get_billing_client()

            # 处理用量上报
            usage_data = _handle_usage_reporting(
                self,
                func,
                args,
                kwargs,
                result,
                module,
                model,
                usage_calculator,
                metadata_extractor,
            )
            if usage_data and billing_client:
                try:
                    await billing_client.report_usage(usage_data)
                except Exception as e:
                    # 使用全局单例的 logger 记录错误
                    logger = (
                        billing_client._logger
                        if billing_client
                        else logging.getLogger(__name__)
                    )
                    logger.error(f"用量上报失败: {e}")

            return result

        @functools.wraps(func)
        def sync_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            # 执行原函数
            result = func(self, *args, **kwargs)

            # 处理用量上报
            usage_data = _handle_usage_reporting(
                self,
                func,
                args,
                kwargs,
                result,
                module,
                model,
                usage_calculator,
                metadata_extractor,
            )
            if usage_data:
                try:
                    # 异步上报用量
                    billing_client = _get_billing_client()
                    if billing_client:
                        asyncio.create_task(billing_client.report_usage(usage_data))
                except Exception as e:
                    # 使用全局单例的 logger 记录错误
                    billing_client = _get_billing_client()
                    logger = (
                        billing_client._logger
                        if billing_client
                        else logging.getLogger(__name__)
                    )
                    logger.error(f"用量上报失败: {e}")

            return result

        # 根据原函数是否为协程返回相应的wrapper
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def require_api_key(func: Callable) -> Callable:
    """
    API Key验证装饰器，适用于gRPC handler
    使用全局单例 billing client 进行实时key状态检查
    """

    @functools.wraps(func)
    async def wrapper(self: Any, stream: Any, *args: Any, **kwargs: Any) -> Any:
        method_name = func.__name__

        # 获取客户端信息用于日志记录
        metadata = dict(stream.metadata)
        session_id = (
            metadata.get("sessionid") or metadata.get("session_id") or "unknown"
        )

        # 获取全局单例 billing client 和 logger
        billing_client = _get_billing_client()
        logger = (
            billing_client._logger if billing_client else logging.getLogger(__name__)
        )

        # 从 metadata 中获取 API key
        api_key = metadata.get("api-key") or metadata.get("apikey")  # 支持两种 key 格式

        if not api_key:
            logger.warning(
                f"API Key 验证失败 - 方法: {method_name}, SessionID: {session_id}, 原因: 缺少 API Key"
            )
            raise Exception("API key is required")  # 替换为实际的gRPC异常

        # 使用全局单例 billing client 进行动态 key 验证
        if billing_client and isinstance(billing_client, BillingClient):
            # 使用 SDK 的动态验证机制
            if not billing_client.is_key_valid(api_key):
                masked_key = _mask_api_key(api_key)
                logger.warning(
                    f"API Key 验证失败 - 方法: {method_name}, SessionID: {session_id}, 原因: 无效的 API Key (masked: {masked_key})"
                )
                raise Exception("Invalid API key")  # 替换为实际的gRPC异常
        else:
            # 如果没有全局单例，记录警告但不阻止请求
            logger.warning(
                f"BillingClient 单例未初始化，跳过 API Key 验证 - 方法: {method_name}, SessionID: {session_id}"
            )

        # API key 验证成功，保存当前 API key 用于用量上报
        self._billing_api_key = api_key
        masked_key = _mask_api_key(api_key)
        logger.info(
            f"API Key 验证成功 - 方法: {method_name}, SessionID: {session_id}, API Key: {masked_key}"
        )

        try:
            return await func(self, stream, *args, **kwargs)
        finally:
            # 清理当前API key
            if hasattr(self, "_billing_api_key"):
                delattr(self, "_billing_api_key")

    return wrapper


def get_billing_client() -> BillingClient | None:
    """
    便利函数：获取 BillingClient 全局单例实例

    Returns:
        BillingClient实例，如果未初始化则返回None
    """
    return _get_billing_client()
