import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from billing_sdk import BillingClient, UsageData


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
        mock_create_task.assert_called_once()

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

        # 阻止_handle_messages被调用
        with patch.object(client, "_handle_messages"):
            mock_mqtt_client = AsyncMock()
            with patch(
                "billing_sdk.client.AioMQTTClient", return_value=mock_mqtt_client
            ):
                await client.connect()

            # 不应该再次连接
            mock_mqtt_client.__aenter__.assert_not_called()

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
    async def test_report_usage_success(self):
        """测试成功上报用量"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 模拟已连接状态
        mock_mqtt_client = AsyncMock()
        client._client = mock_mqtt_client
        client._is_connected = True

        usage_data = UsageData(
            api_key="test-key",
            module="gpt",
            model="gpt-4",
            usage=100,
            metadata={"input_tokens": 50, "output_tokens": 50},
        )

        await client.report_usage(usage_data)

        # 验证 publish 被调用
        mock_mqtt_client.publish.assert_called_once()
        args = mock_mqtt_client.publish.call_args[0]
        assert args[0] == "billing/report"

        # 验证消息内容
        message_data = json.loads(args[1])
        assert message_data["api_key"] == "test-key"
        assert message_data["module"] == "gpt"
        assert message_data["model"] == "gpt-4"
        assert message_data["usage"] == 100

    @pytest.mark.asyncio
    async def test_report_usage_not_connected(self):
        """测试未连接时上报用量"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        usage_data = UsageData(
            api_key="test-key", module="gpt", model="gpt-4", usage=100
        )

        with pytest.raises(RuntimeError, match="未连接到 MQTT 代理"):
            await client.report_usage(usage_data)

    @pytest.mark.asyncio
    async def test_report_usage_publish_failure(self):
        """测试发布失败时的异常处理"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 模拟已连接状态
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client.publish.side_effect = Exception("Publish failed")
        client._client = mock_mqtt_client
        client._is_connected = True

        usage_data = UsageData(
            api_key="test-key", module="gpt", model="gpt-4", usage=100
        )

        with pytest.raises(Exception, match="Publish failed"):
            await client.report_usage(usage_data)

    def test_is_key_valid_scenarios(self):
        """测试API Key验证的所有场景"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 测试被阻止的Key
        client._blocked_keys.add("blocked-key")
        assert not client.is_key_valid("blocked-key")

        # 测试有效的Key
        client._valid_keys.add("valid-key")
        assert client.is_key_valid("valid-key")

        # 测试未知Key（应该默认为有效）
        assert client.is_key_valid("unknown-key")

    @pytest.mark.asyncio
    async def test_handle_key_status_update_blocked(self):
        """测试处理 Key 被阻止的状态更新"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        payload = {
            "updates": [
                {"key": "test-key", "status": "blocked", "reason": "quota exceeded"}
            ]
        }

        await client._handle_key_status_update(json.dumps(payload))

        assert "test-key" in client._blocked_keys
        assert "test-key" not in client._valid_keys

    @pytest.mark.asyncio
    async def test_handle_key_status_update_ok(self):
        """测试处理 Key 恢复正常的状态更新"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 先添加到阻止列表
        client._blocked_keys.add("test-key")

        payload = {"updates": [{"key": "test-key", "status": "ok"}]}

        await client._handle_key_status_update(json.dumps(payload))

        assert "test-key" not in client._blocked_keys
        assert "test-key" in client._valid_keys

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
                {"key": "test-key", "status": "blocked", "reason": "test reason"}
            ]
        }

        await client._handle_key_status_update(json.dumps(payload))

        assert len(callback_data) == 1
        assert callback_data[0] == ("test-key", "blocked", "test reason")

    def test_get_keys_functionality(self):
        """测试获取有效和被阻止Keys的功能"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        # 测试获取有效Keys
        client._valid_keys.add("key1")
        client._valid_keys.add("key2")
        valid_keys = client.get_valid_keys()
        assert valid_keys == {"key1", "key2"}
        assert valid_keys is not client._valid_keys  # 应该是副本

        # 测试获取被阻止的Keys
        client._blocked_keys.add("blocked1")
        client._blocked_keys.add("blocked2")
        blocked_keys = client.get_blocked_keys()
        assert blocked_keys == {"blocked1", "blocked2"}
        assert blocked_keys is not client._blocked_keys  # 应该是副本
