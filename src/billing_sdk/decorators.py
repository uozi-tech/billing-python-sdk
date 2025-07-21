import functools
import logging
from collections.abc import Callable
from typing import Any

from .client import BillingClient


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

        masked_key = _mask_api_key(api_key)
        logger.info(
            f"API Key 验证成功 - 方法: {method_name}, SessionID: {session_id}, API Key: {masked_key}"
        )

        return await func(self, stream, *args, **kwargs)

    return wrapper


def get_billing_client() -> BillingClient | None:
    """
    便利函数：获取 BillingClient 全局单例实例

    Returns:
        BillingClient实例，如果未初始化则返回None
    """
    return _get_billing_client()
