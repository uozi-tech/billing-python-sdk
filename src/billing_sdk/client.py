import asyncio
import json
import logging
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiomqtt import Client as AioMQTTClient


@dataclass
class UsageData:
    """用量数据结构"""

    api_key: str
    module: str
    model: str
    usage: int
    metadata: dict[str, Any] | None = None


class BillingClient:
    """MQTT客户端，用于计费系统的用量上报和Key状态监控（单例模式）"""

    _instance: "BillingClient | None" = None
    _initialized: bool = False
    _lock = asyncio.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "BillingClient":
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        broker_host: str,
        broker_port: int = 8883,  # TLS 默认端口
        username: str | None = None,
        password: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        # 防止重复初始化
        if self._initialized:
            return

        self.broker_host = broker_host
        self.broker_port = broker_port
        self.username = username
        self.password = password

        self._client: AioMQTTClient | None = None
        self._is_connected = False
        # 用于缓存有效的 API keys，从 MQTT 推送中动态更新
        self._valid_keys: set[str] = set()
        # 用于缓存被阻止的 API keys
        self._blocked_keys: set[str] = set()
        self._key_status_callback: Callable | None = None
        # 使用自定义 logger 或默认 logger
        self._logger = logger or logging.getLogger(__name__)

        # 消息处理任务
        self._message_task: asyncio.Task | None = None

        # 标记为已初始化
        BillingClient._initialized = True

        # 自动连接 MQTT
        self._auto_connect()

    def _create_tls_context(self) -> ssl.SSLContext:
        """创建默认的 TLS SSL 上下文"""
        # 创建 SSL 上下文，默认忽略证书验证
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False  # MQTT 通常不使用主机名验证
        context.verify_mode = ssl.CERT_NONE  # 忽略证书校验

        return context

    @classmethod
    def get_instance(cls) -> "BillingClient":
        """获取单例实例"""
        if cls._instance is None:
            raise RuntimeError("BillingClient 尚未初始化，请先调用构造函数")
        return cls._instance

    @classmethod
    def is_initialized(cls) -> bool:
        """检查是否已经初始化"""
        return cls._instance is not None and cls._initialized

    def _auto_connect(self) -> None:
        """自动连接到 MQTT 代理（后台任务）"""
        try:
            # 检查是否有运行中的事件循环
            asyncio.get_running_loop()
            # 创建后台任务进行连接
            task = asyncio.create_task(self.connect())
            # 添加异常处理回调
            task.add_done_callback(self._handle_auto_connect_result)
            self._logger.info("已启动 MQTT 自动连接任务")
        except RuntimeError:
            # 如果没有运行中的事件循环，则忽略（可能在同步环境中）
            self._logger.info(
                "未检测到事件循环，请手动调用 await client.connect() 连接 MQTT"
            )

    def _handle_auto_connect_result(self, task: asyncio.Task) -> None:
        """处理自动连接任务的结果"""
        try:
            task.result()
        except Exception as e:
            self._logger.debug(f"自动连接失败: {e}")
            # 静默处理，用户可以手动连接

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._is_connected

    async def connect(self) -> None:
        """连接到 MQTT 代理（默认使用 TLS）"""
        async with self._lock:
            if self._is_connected:
                self._logger.info("BillingClient 已经连接，跳过重复连接")
                return

            try:
                # 创建 TLS 上下文
                tls_context = self._create_tls_context()

                self._logger.info(
                    f"使用 TLS 连接到 MQTT 代理 {self.broker_host}:{self.broker_port}"
                )

                # 创建客户端
                self._client = AioMQTTClient(
                    hostname=self.broker_host,
                    port=self.broker_port,
                    username=self.username,
                    password=self.password,
                    tls_context=tls_context,
                )

                # 启动连接
                await self._client.__aenter__()
                self._is_connected = True

                self._logger.info("已通过 TLS 连接到 MQTT 代理")

                # 订阅 Key 状态更新
                await self._client.subscribe("billing/keys/update")

                # 启动消息处理任务
                self._message_task = asyncio.create_task(self._handle_messages())

                # 首次连接后请求 Key 列表
                await self._request_keys_list()

            except Exception as e:
                self._logger.error(f"连接 MQTT 代理失败: {e}")
                self._is_connected = False
                self._client = None
                raise

    async def _request_keys_list(self) -> None:
        """首次连接后请求 Key 列表"""
        if not self._is_connected or self._client is None:
            return

        try:
            request_message = {
                "timestamp": int(time.time() * 1000)  # 毫秒时间戳
            }

            await self._client.publish(
                "billing/keys/request", json.dumps(request_message)
            )
            self._logger.info("已发送 Key 列表请求")
        except Exception as e:
            self._logger.error(f"请求 Key 列表失败: {e}")

    async def disconnect(self) -> None:
        """断开 MQTT 连接"""
        async with self._lock:
            if self._client and self._is_connected:
                # 停止消息处理任务
                if self._message_task and not self._message_task.done():
                    self._message_task.cancel()
                    try:
                        await self._message_task
                    except asyncio.CancelledError:
                        pass
                    self._message_task = None

                # 断开连接
                try:
                    await self._client.__aexit__(None, None, None)
                except Exception as e:
                    self._logger.warning(f"断开连接时出现警告: {e}")

                self._is_connected = False
                self._client = None
                self._logger.info("已断开 MQTT 连接")

    async def _handle_messages(self) -> None:
        """处理接收到的 MQTT 消息"""
        if self._client is None:
            return

        try:
            async for message in self._client.messages:
                if message.topic.matches("billing/keys/update"):
                    payload = message.payload
                    if isinstance(payload, bytes | bytearray):
                        await self._handle_key_status_update(payload.decode())
                    elif isinstance(payload, str):
                        await self._handle_key_status_update(payload)
                    else:
                        self._logger.warning(
                            f"收到不支持的 payload 类型: {type(payload)}"
                        )
        except asyncio.CancelledError:
            # 正常取消，不需要记录错误
            pass
        except Exception as e:
            self._logger.error(f"处理 MQTT 消息时出错: {e}")

    async def _handle_key_status_update(self, payload: str) -> None:
        """处理 Key 状态更新消息"""
        try:
            data = json.loads(payload)
            updates = data.get("updates", [])
            timestamp = data.get("timestamp")

            self._logger.info(
                f"收到 Key 状态更新，时间戳: {timestamp}, 更新数量: {len(updates)}"
            )

            for update in updates:
                key = update.get("key")
                status = update.get("status")
                reason = update.get("reason", "")

                if status == "blocked":
                    # 从有效 keys 中移除被阻止的 key，添加到阻止列表
                    self._valid_keys.discard(key)
                    self._blocked_keys.add(key)
                    from .decorators import _mask_api_key

                    self._logger.warning(
                        f"API Key 被阻止: {_mask_api_key(key)}, 原因: {reason}"
                    )
                elif status == "ok":
                    # 添加到有效 keys 中，从阻止列表移除
                    self._valid_keys.add(key)
                    self._blocked_keys.discard(key)
                    from .decorators import _mask_api_key

                    self._logger.info(f"API Key 状态正常: {_mask_api_key(key)}")

                # 调用回调函数
                if self._key_status_callback:
                    await self._key_status_callback(key, status, reason)

        except Exception as e:
            self._logger.error(f"处理 Key 状态更新时出错: {e}")

    async def report_usage(self, usage_data: UsageData) -> None:
        """
        上报用量信息

        Args:
            usage_data: 用量数据对象，包含API密钥、模块、模型、用量和元数据
        """
        if not self._is_connected or self._client is None:
            raise RuntimeError("未连接到 MQTT 代理")

        message = {
            "api_key": usage_data.api_key,
            "module": usage_data.module,
            "model": usage_data.model,
            "usage": usage_data.usage,
            "timestamp": int(time.time() * 1000),  # 毫秒时间戳
        }

        if usage_data.metadata:
            message["metadata"] = usage_data.metadata

        try:
            await self._client.publish("billing/report", json.dumps(message))
            self._logger.info(f"用量上报成功: {usage_data.model} - {usage_data.usage}")
        except Exception as e:
            self._logger.error(f"用量上报失败: {e}")
            raise

    def is_key_valid(self, api_key: str) -> bool:
        """检查 API Key 是否有效"""
        return api_key in self._valid_keys

    def get_valid_keys(self) -> set[str]:
        """获取当前有效的 API Keys"""
        return self._valid_keys.copy()

    def get_blocked_keys(self) -> set[str]:
        """获取当前被阻止的 API Keys"""
        return self._blocked_keys.copy()

    def set_key_status_callback(self, callback: Callable) -> None:
        """设置 Key 状态变化回调函数"""
        self._key_status_callback = callback

    async def request_keys_list(self) -> None:
        """手动请求 Key 列表更新"""
        await self._request_keys_list()

    def __enter__(self) -> "BillingClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._is_connected:
            asyncio.create_task(self.disconnect())


async def report_usage(
    api_key: str,
    module: str,
    model: str,
    usage: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    """
    全局用量上报函数，自动使用单例 BillingClient 实例

    Args:
        api_key: API 密钥
        module: 模块名称 (如 "llm", "tts", "asr")
        model: 模型名称
        usage: 用量数值
        metadata: 元数据字典 (可选)

    Raises:
        RuntimeError: 当 BillingClient 未初始化或未连接时
    """
    client = BillingClient.get_instance()
    if not client:
        raise RuntimeError("BillingClient 尚未初始化，请先初始化 BillingClient")

    if not client.is_connected():
        raise RuntimeError("BillingClient 未连接，请先调用 connect() 方法")

    usage_data = UsageData(
        api_key=api_key,
        module=module,
        model=model,
        usage=usage,
        metadata=metadata,
    )

    await client.report_usage(usage_data)
