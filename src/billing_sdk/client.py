import asyncio
import json
import logging
import ssl
import time
from asyncio import Queue
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
        self.keepalive_interval = 10  # 固定保活检查间隔为 10 秒

        self._client: AioMQTTClient | None = None
        self._is_connected = False
        # 用于缓存有效的 API keys，从 MQTT 推送中动态更新
        self._valid_keys: set[str] = set()
        # 用于缓存被阻止的 API keys
        self._blocked_keys: set[str] = set()
        self._key_status_callback: Callable | None = None
        # 使用自定义 logger 或默认 logger
        self._logger = logger or logging.getLogger(__name__)

        # 异步队列用于缓存上报数据（无限大小）
        self._usage_queue: Queue[UsageData] = Queue()

        # 后台任务
        self._message_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._queue_consumer_task: asyncio.Task | None = None

        # 控制任务运行的标志
        self._should_stop = False

        # 重连控制
        self._reconnecting = False  # 防止并发重连
        self._last_reconnect_time = 0.0  # 上次重连时间
        self._reconnect_delay = 5.0  # 重连间隔（秒）
        self._max_reconnect_attempts = 3  # 最大重连尝试次数
        self._reconnect_attempts = 0  # 当前重连尝试次数

        # 连接健康检查
        self._last_heartbeat_success = time.time()
        self._connection_timeout = 30.0  # 连接超时时间（秒）

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
        return self._is_connected and self._client is not None

    def _should_reconnect(self) -> bool:
        """检查是否应该重连"""
        current_time = time.time()

        # 检查重连频率限制
        if current_time - self._last_reconnect_time < self._reconnect_delay:
            return False

        # 检查重连尝试次数
        if self._reconnect_attempts >= self._max_reconnect_attempts:
            # 重置重连计数器，增加延迟
            if current_time - self._last_reconnect_time > self._reconnect_delay * 2:
                self._reconnect_attempts = 0
                return True
            return False

        return True

    async def _reconnect_with_backoff(self) -> bool:
        """带退避策略的重连"""
        if self._reconnecting:
            return False

        if not self._should_reconnect():
            return False

        self._reconnecting = True
        self._last_reconnect_time = time.time()
        self._reconnect_attempts += 1

        try:
            self._logger.warning(
                f"检测到连接断开，尝试重新连接... (尝试 {self._reconnect_attempts}/{self._max_reconnect_attempts})"
            )

            # 先清理旧连接
            await self._cleanup_connection()

            # 重新连接
            await self.connect()

            # 重连成功，重置计数器
            self._reconnect_attempts = 0
            self._logger.info("重连成功")
            return True

        except Exception as e:
            self._logger.error(f"重连失败: {e}")
            return False
        finally:
            self._reconnecting = False

    async def _cleanup_connection(self) -> None:
        """清理现有连接"""
        self._is_connected = False
        if self._client:
            try:
                await self._client.__aexit__(None, None, None)
            except Exception as e:
                self._logger.debug(f"清理连接时出现异常: {e}")
            finally:
                self._client = None

    async def connect(self) -> None:
        """连接到 MQTT 代理（默认使用 TLS）"""
        async with self._lock:
            if self._is_connected and self._client is not None:
                # 进行更严格的连接检查
                try:
                    # 尝试发送一个简单的ping消息来验证连接
                    test_msg = {"type": "ping", "timestamp": int(time.time() * 1000)}
                    await self._client.publish("billing/ping", json.dumps(test_msg))
                    self._logger.debug("连接验证成功，跳过重复连接")
                    return
                except Exception as e:
                    self._logger.warning(f"连接验证失败: {e}，将重新建立连接")
                    await self._cleanup_connection()

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
                self._last_heartbeat_success = time.time()

                self._logger.info("已通过 TLS 连接到 MQTT 代理")

                # 订阅 Key 状态更新
                await self._client.subscribe("billing/keys/update")

                # 启动后台任务
                await self._start_background_tasks()

                # 首次连接后请求 Key 列表
                await self._request_keys_list()

            except Exception as e:
                self._logger.error(f"连接 MQTT 代理失败: {e}")
                await self._cleanup_connection()
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

    async def _start_background_tasks(self) -> None:
        """启动所有后台任务"""
        self._should_stop = False

        # 启动消息处理任务
        self._message_task = asyncio.create_task(self._handle_messages())

        # 启动连接保活任务
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        # 启动队列消费者任务
        self._queue_consumer_task = asyncio.create_task(self._queue_consumer_loop())

        self._logger.info("所有后台任务已启动")

    async def _stop_background_tasks(self) -> None:
        """停止所有后台任务"""
        self._should_stop = True

        # 停止所有任务
        tasks = [self._message_task, self._keepalive_task, self._queue_consumer_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # 重置任务引用
        self._message_task = None
        self._keepalive_task = None
        self._queue_consumer_task = None

        self._logger.info("所有后台任务已停止")

    async def _keepalive_loop(self) -> None:
        """MQTT连接保活循环"""
        self._logger.info(f"连接保活任务启动，检查间隔: {self.keepalive_interval}秒")

        while not self._should_stop:
            try:
                await asyncio.sleep(self.keepalive_interval)

                if self._should_stop:
                    break

                # 更严格的连接状态检查
                current_time = time.time()
                connection_lost = False

                if not self._is_connected or self._client is None:
                    connection_lost = True
                elif (
                    current_time - self._last_heartbeat_success
                    > self._connection_timeout
                ):
                    self._logger.warning("心跳超时，认为连接已断开")
                    connection_lost = True

                if connection_lost:
                    # 尝试重连
                    await self._reconnect_with_backoff()
                    continue

                # 发送心跳消息
                try:
                    if self._client and self._is_connected:
                        heartbeat_msg = {
                            "type": "heartbeat",
                            "timestamp": int(time.time() * 1000),
                        }
                        await self._client.publish(
                            "billing/heartbeat", json.dumps(heartbeat_msg)
                        )
                        self._last_heartbeat_success = current_time
                        self._logger.debug("发送心跳消息成功")
                except Exception as e:
                    self._logger.warning(f"发送心跳消息失败: {e}")
                    self._is_connected = False

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"保活循环异常: {e}")
                await asyncio.sleep(5)  # 异常后等待5秒再继续

        self._logger.info("连接保活任务已停止")

    async def _queue_consumer_loop(self) -> None:
        """队列消费者循环"""
        self._logger.info("队列消费者任务启动")

        while not self._should_stop:
            try:
                # 等待队列中的数据，设置超时避免阻塞
                try:
                    usage_data = await asyncio.wait_for(
                        self._usage_queue.get(), timeout=1.0
                    )
                except TimeoutError:
                    continue

                # 确保连接存在
                if not self.is_connected():
                    # 如果连接断开，将数据放回队列头部
                    await self._usage_queue.put(usage_data)
                    await asyncio.sleep(1)
                    continue

                # 发送数据
                try:
                    await self._send_usage_data(usage_data)
                    self._usage_queue.task_done()
                    self._logger.debug(
                        f"成功上报用量: {usage_data.model} - {usage_data.usage}"
                    )
                except Exception as e:
                    # 发送失败，将数据放回队列
                    await self._usage_queue.put(usage_data)
                    self._usage_queue.task_done()
                    self._logger.error(f"上报用量失败: {e}")
                    # 标记连接可能有问题
                    self._is_connected = False
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"队列消费者循环异常: {e}")
                await asyncio.sleep(1)

        self._logger.info("队列消费者任务已停止")

    async def _send_usage_data(self, usage_data: UsageData) -> None:
        """实际发送用量数据到MQTT"""
        if not self.is_connected() or self._client is None:
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

        await self._client.publish("billing/report", json.dumps(message))

    async def disconnect(self) -> None:
        """断开 MQTT 连接"""
        async with self._lock:
            # 停止所有后台任务
            await self._stop_background_tasks()

            if self._client and self._is_connected:
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

                    self._logger.info(
                        f"API Key 被阻止: {_mask_api_key(key)}, 原因: {reason or '未知'}"
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
        # 将数据放入队列，由队列消费者处理（队列无限大小，不会失败）
        self._usage_queue.put_nowait(usage_data)
        self._logger.debug(
            f"用量数据已加入队列: {usage_data.model} - {usage_data.usage}"
        )

    def is_key_valid(self, api_key: str) -> bool:
        """检查 API Key 是否有效"""
        return api_key in self._valid_keys

    def get_valid_keys(self) -> set[str]:
        """获取当前有效的 API Keys"""
        return self._valid_keys.copy()

    def get_blocked_keys(self) -> set[str]:
        """获取当前被阻止的 API Keys"""
        return self._blocked_keys.copy()

    def get_queue_status(self) -> dict[str, Any]:
        """获取队列状态信息"""
        return {
            "queue_size": self._usage_queue.qsize(),
            "queue_maxsize": None,  # 无限队列
            "queue_full": False,  # 无限队列永远不会满
            "queue_empty": self._usage_queue.empty(),
            "usage_rate": None,  # 无限队列没有使用率概念
        }

    def clear_queue(self) -> int:
        """清空队列，返回清除的数据条数"""
        count = 0
        while not self._usage_queue.empty():
            try:
                self._usage_queue.get_nowait()
                self._usage_queue.task_done()
                count += 1
            except asyncio.QueueEmpty:
                break

        self._logger.info(f"已清空队列，清除了 {count} 条数据")
        return count

    async def wait_queue_empty(self, timeout: float = 30.0) -> bool:
        """
        等待队列为空

        Args:
            timeout: 超时时间（秒）

        Returns:
            bool: 如果队列在超时前变空返回True，否则返回False
        """
        try:
            await asyncio.wait_for(self._usage_queue.join(), timeout=timeout)
            return True
        except TimeoutError:
            self._logger.warning(
                f"等待队列清空超时，当前队列大小: {self._usage_queue.qsize()}"
            )
            return False

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
            # 在同步上下文中创建任务来断开连接
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.disconnect())
            except RuntimeError:
                # 如果没有运行中的事件循环，创建新的来执行断开连接
                asyncio.run(self.disconnect())

    async def __aenter__(self) -> "BillingClient":
        """异步上下文管理器入口"""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """异步上下文管理器出口"""
        await self.disconnect()


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
        RuntimeError: 当 BillingClient 未初始化时
    """
    client = BillingClient.get_instance()
    if not client:
        raise RuntimeError("BillingClient 尚未初始化，请先初始化 BillingClient")

    usage_data = UsageData(
        api_key=api_key,
        module=module,
        model=model,
        usage=usage,
        metadata=metadata,
    )

    await client.report_usage(usage_data)
