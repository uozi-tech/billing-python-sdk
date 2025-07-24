import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from billing_sdk import BillingClient, UsageData, report_usage


@pytest.mark.unit
class TestBillingClient:
    """BillingClient 测试类"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    async def test_singleton_pattern(self):
        """测试单例模式"""
        # 第一次初始化
        with patch.object(BillingClient, "_auto_connect"):
            client1 = BillingClient("localhost", 8883)

        # 第二次获取应该返回同一个实例
        with patch.object(BillingClient, "_auto_connect"):
            client2 = BillingClient("different_host", 9999)

        # 应该是同一个实例
        assert client1 is client2
        # 配置应该是第一次的配置
        assert client1.broker_host == "localhost"
        assert client1.broker_port == 8883

    @pytest.mark.asyncio
    async def test_get_instance_before_initialization(self):
        """测试在初始化前获取实例"""
        with pytest.raises(RuntimeError, match="BillingClient 尚未初始化"):
            BillingClient.get_instance()

    @pytest.mark.asyncio
    async def test_get_instance_after_initialization(self):
        """测试初始化后获取实例"""
        with patch.object(BillingClient, "_auto_connect"):
            original = BillingClient("localhost", 8883)

        instance = BillingClient.get_instance()
        assert instance is original

    async def test_is_initialized(self):
        """测试初始化状态检查"""
        assert not BillingClient.is_initialized()

        with patch.object(BillingClient, "_auto_connect"):
            BillingClient("localhost", 8883)

        assert BillingClient.is_initialized()

    @pytest.mark.asyncio
    async def test_auto_connect_with_event_loop(self):
        """测试有事件循环时的自动连接"""
        # 创建一个mock任务来模拟协程执行
        mock_task = Mock()
        mock_task.add_done_callback = Mock()
        mock_task.result = Mock(return_value=None)

        with (
            patch("asyncio.create_task", return_value=mock_task) as mock_create_task,
            patch("asyncio.get_running_loop"),
        ):
            BillingClient("localhost", 8883)

            # 验证自动连接任务被创建
            mock_create_task.assert_called_once()
            # 验证回调被设置
            mock_task.add_done_callback.assert_called_once()

            # 手动触发done回调以清理协程
            callback = mock_task.add_done_callback.call_args[0][0]
            callback(mock_task)

    @pytest.mark.asyncio
    async def test_auto_connect_without_event_loop(self):
        """测试没有事件循环时的自动连接"""
        # 全面mock所有可能的方法调用避免协程警告
        with (
            patch(
                "asyncio.get_running_loop", side_effect=RuntimeError("No event loop")
            ),
            patch.object(
                BillingClient, "connect", new_callable=AsyncMock
            ) as mock_connect,
            patch("asyncio.create_task") as mock_create_task,
        ):
            # 应该没有抛出异常，只是记录信息
            # Mock connect方法避免实际协程调用
            BillingClient("localhost", 8883)
            # 验证connect没有被调用（因为没有事件循环）
            mock_connect.assert_not_called()
            mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """测试成功连接到 MQTT"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        mock_mqtt_client = AsyncMock()
        # Mock aiomqtt 的上下文管理器方法
        mock_mqtt_client.__aenter__ = AsyncMock(return_value=mock_mqtt_client)
        mock_mqtt_client.__aexit__ = AsyncMock(return_value=None)
        mock_mqtt_client.subscribe = AsyncMock()

        # 创建mock任务用于消息处理，避免实际协程创建
        mock_task = Mock()
        mock_task.add_done_callback = Mock()

        # 阻止所有可能的协程调用
        with (
            patch("billing_sdk.client.AioMQTTClient", return_value=mock_mqtt_client),
            patch("asyncio.create_task", return_value=mock_task) as mock_create_task,
            patch.object(client, "_handle_messages"),
            patch.object(client, "_request_keys_list", new_callable=AsyncMock),
        ):
            await client.connect()

        # 验证连接状态
        assert client.is_connected()
        mock_mqtt_client.__aenter__.assert_called_once()
        mock_mqtt_client.subscribe.assert_called_once_with("billing/keys/update")
        # 现在会创建3个任务：消息处理、保活、队列消费者
        assert mock_create_task.call_count == 3

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """测试重复连接"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 模拟已连接状态
        client._is_connected = True
        # 防止_handle_messages协程警告
        client._message_task = None
        # 确保已有MQTT客户端实例
        client._client = AsyncMock()
        client._client.publish = AsyncMock()

        # 阻止_handle_messages被调用
        with patch.object(client, "_handle_messages"):
            # 连接验证成功的情况
            await client.connect()

            # 应该调用publish进行连接验证
            client._client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """测试连接失败"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        mock_mqtt_client = AsyncMock()
        mock_mqtt_client.__aenter__.side_effect = Exception("Connection failed")

        with patch("billing_sdk.client.AioMQTTClient", return_value=mock_mqtt_client):
            with pytest.raises(Exception, match="Connection failed"):
                await client.connect()

        assert not client.is_connected()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试断开连接"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 模拟已连接状态
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client.__aexit__ = AsyncMock()
        client._client = mock_mqtt_client
        client._is_connected = True

        await client.disconnect()

        mock_mqtt_client.__aexit__.assert_called_once()
        assert not client.is_connected()

    @pytest.mark.asyncio
    async def test_report_usage_always_works(self):
        """测试队列上报不依赖连接状态"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 即使未连接也能放入队列
        usage_data = UsageData(
            api_key="test-key", module="gpt", model="gpt-4", usage=100
        )

        # 不应该抛出异常
        await client.report_usage(usage_data)

        # 验证数据已在队列中
        assert client._usage_queue.qsize() == 1

    def test_is_key_valid_scenarios(self):
        """测试API Key验证的所有场景"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 测试有效的Key
        client._valid_keys["valid-key"] = "app-123"
        assert client.is_key_valid("valid-key")

        # 测试未知Key（应该默认为无效）
        assert not client.is_key_valid("unknown-key")

    @pytest.mark.asyncio
    async def test_handle_key_status_update_blocked(self):
        """测试处理 Key 被阻止的状态更新"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 先添加一个有效key
        client._valid_keys["test-key"] = "app-123"

        payload = {
            "updates": [
                {
                    "app_id": "app-123",
                    "api_key": "test-key",
                    "status": "blocked",
                    "reason": "quota exceeded",
                }
            ],
            "timestamp": 1234567890,
        }

        await client._handle_key_status_update(json.dumps(payload))

        assert "test-key" in client._blocked_keys
        assert client._blocked_keys["test-key"] == "app-123"
        assert "test-key" not in client._valid_keys

    @pytest.mark.asyncio
    async def test_handle_key_status_update_ok(self):
        """测试处理 Key 恢复正常的状态更新"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 先添加到阻止列表
        client._blocked_keys["test-key"] = "app-123"

        payload = {
            "updates": [{"app_id": "app-123", "api_key": "test-key", "status": "ok"}],
            "timestamp": 1234567890,
        }

        await client._handle_key_status_update(json.dumps(payload))

        assert "test-key" not in client._blocked_keys
        assert "test-key" in client._valid_keys
        assert client._valid_keys["test-key"] == "app-123"

    @pytest.mark.asyncio
    async def test_handle_key_status_update_with_callback(self):
        """测试带回调函数的 Key 状态更新"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        callback_data = []

        async def test_callback(key, status, reason):
            callback_data.append((key, status, reason))

        client.set_key_status_callback(test_callback)

        payload = {
            "updates": [
                {
                    "app_id": "app-123",
                    "api_key": "test-key",
                    "status": "blocked",
                    "reason": "test reason",
                }
            ],
            "timestamp": 1234567890,
        }

        await client._handle_key_status_update(json.dumps(payload))

        assert len(callback_data) == 1
        assert callback_data[0] == ("test-key", "blocked", "test reason")

    def test_queue_management_functions(self):
        """测试队列管理功能"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 测试初始队列状态
        status = client.get_queue_status()
        assert status["queue_size"] == 0
        assert status["queue_maxsize"] is None
        assert status["queue_full"] is False
        assert status["queue_empty"] is True
        assert status["usage_rate"] is None

        # 添加一些数据到队列
        usage_data1 = UsageData(api_key="key1", module="llm", model="gpt-4", usage=100)
        usage_data2 = UsageData(api_key="key2", module="tts", model="voice", usage=50)

        client._usage_queue.put_nowait(usage_data1)
        client._usage_queue.put_nowait(usage_data2)

        # 测试队列状态更新
        status = client.get_queue_status()
        assert status["queue_size"] == 2
        assert status["queue_empty"] is False

        # 测试清空队列
        cleared_count = client.clear_queue()
        assert cleared_count == 2
        assert client._usage_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_wait_queue_empty_success(self):
        """测试等待队列为空成功"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 队列已经为空
        result = await client.wait_queue_empty(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_queue_empty_timeout(self):
        """测试等待队列为空超时"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 添加数据到队列但不处理
        usage_data = UsageData(api_key="key", module="llm", model="gpt-4", usage=100)
        client._usage_queue.put_nowait(usage_data)

        result = await client.wait_queue_empty(timeout=0.1)
        assert result is False

    def test_keepalive_interval_fixed(self):
        """测试保活间隔固定为10秒"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        assert client.keepalive_interval == 10

    @pytest.mark.asyncio
    async def test_send_usage_data_success(self):
        """测试成功发送用量数据"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 设置连接状态和有效key
        client._is_connected = True
        mock_mqtt_client = AsyncMock()
        client._client = mock_mqtt_client
        client._valid_keys["test-key"] = "app-123"

        usage_data = UsageData(
            api_key="test-key",
            module="llm",
            model="gpt-4",
            usage=100,
            metadata={"tokens": 100},
        )

        await client._send_usage_data(usage_data)

        # 验证消息被发布
        mock_mqtt_client.publish.assert_called_once()
        args = mock_mqtt_client.publish.call_args
        assert args[0][0] == "billing/report"

        # 验证消息内容
        message_data = json.loads(args[0][1])
        assert message_data["app_id"] == "app-123"
        assert message_data["api_key"] == "test-key"
        assert message_data["module"] == "llm"
        assert message_data["model"] == "gpt-4"
        assert message_data["usage"] == 100
        assert message_data["metadata"] == {"tokens": 100}
        assert "timestamp" in message_data

    @pytest.mark.asyncio
    async def test_send_usage_data_invalid_key(self):
        """测试使用无效key发送用量数据"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 设置连接状态但不添加有效key
        client._is_connected = True
        client._client = AsyncMock()

        usage_data = UsageData(
            api_key="invalid-key", module="llm", model="gpt-4", usage=100
        )

        with pytest.raises(RuntimeError, match="API Key invalid-key 无效"):
            await client._send_usage_data(usage_data)

    @pytest.mark.asyncio
    async def test_send_usage_data_not_connected(self):
        """测试未连接时发送用量数据"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 设置未连接状态
        client._is_connected = False
        client._client = None

        usage_data = UsageData(
            api_key="test-key", module="llm", model="gpt-4", usage=100
        )

        with pytest.raises(RuntimeError, match="未连接到 MQTT 代理"):
            await client._send_usage_data(usage_data)


@pytest.mark.unit
class TestReportUsageFunction:
    """report_usage 函数测试类"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @pytest.mark.asyncio
    async def test_report_usage_global_success(self):
        """测试全局 report_usage 函数成功上报（队列方式）"""
        # 初始化 billing client
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 调用全局函数
        await report_usage(
            api_key="test-key",
            module="llm",
            model="gpt-4",
            usage=100,
            metadata={"test": "data"},
        )

        # 验证数据已在队列中
        assert client._usage_queue.qsize() == 1

        # 验证队列中的数据
        queued_data = client._usage_queue.get_nowait()
        assert queued_data.api_key == "test-key"
        assert queued_data.module == "llm"
        assert queued_data.model == "gpt-4"
        assert queued_data.usage == 100
        assert queued_data.metadata == {"test": "data"}

    @pytest.mark.asyncio
    async def test_report_usage_not_initialized(self):
        """测试全局 report_usage 在 BillingClient 未初始化时的错误"""
        with pytest.raises(RuntimeError, match="BillingClient 尚未初始化"):
            await report_usage("test-key", "llm", "gpt-4", 100)

    @pytest.mark.asyncio
    async def test_report_usage_minimal_params(self):
        """测试全局 report_usage 函数最小参数"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 只使用必需参数
        await report_usage("test-key", "llm", "gpt-4", 100)

        # 验证队列中的数据
        assert client._usage_queue.qsize() == 1
        queued_data = client._usage_queue.get_nowait()
        assert queued_data.metadata is None
