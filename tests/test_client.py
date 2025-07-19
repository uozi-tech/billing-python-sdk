import json
from unittest.mock import AsyncMock, patch

import pytest

from billing_sdk import BillingClient, UsageData


class TestBillingClient:
    """BillingClient 测试类"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @pytest.mark.asyncio
    async def test_singleton_pattern(self):
        """测试单例模式"""
        # 第一次初始化
        with patch("asyncio.create_task"):
            client1 = BillingClient("localhost", 8883)

        # 第二次获取应该返回同一个实例
        with patch("asyncio.create_task"):
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
        with patch("asyncio.create_task"):
            original = BillingClient("localhost", 8883)

        instance = BillingClient.get_instance()
        assert instance is original

    @pytest.mark.asyncio
    async def test_is_initialized(self):
        """测试初始化状态检查"""
        assert not BillingClient.is_initialized()

        with patch("asyncio.create_task"):
            BillingClient("localhost", 1883)

        assert BillingClient.is_initialized()

    @pytest.mark.asyncio
    async def test_auto_connect_with_event_loop(self):
        """测试有事件循环时的自动连接"""
        with patch("asyncio.create_task") as mock_create_task:
            BillingClient("localhost", 1883)
            # 验证自动连接任务被创建
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_connect_without_event_loop(self):
        """测试没有事件循环时的自动连接"""
        with patch("asyncio.create_task", side_effect=RuntimeError("No event loop")):
            # 应该没有抛出异常，只是记录警告
            BillingClient("localhost", 1883)

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """测试成功连接到 MQTT"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        mock_mqtt_client = AsyncMock()

        with patch("billing_sdk.client.AsyncMQTTClient", return_value=mock_mqtt_client):
            with patch("asyncio.create_task"):  # Mock message handler task
                await client.connect()

        # 验证连接状态
        assert client.is_connected()
        mock_mqtt_client.connect.assert_called_once()
        mock_mqtt_client.subscribe.assert_called_once_with("key-status-updates")

    @pytest.mark.asyncio
    async def test_connect_already_connected(self):
        """测试重复连接"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        # 模拟已连接状态
        client._is_connected = True

        mock_mqtt_client = AsyncMock()
        with patch("billing_sdk.client.AsyncMQTTClient", return_value=mock_mqtt_client):
            await client.connect()

        # 不应该再次连接
        mock_mqtt_client.connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """测试连接失败"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        mock_mqtt_client = AsyncMock()
        mock_mqtt_client.connect.side_effect = Exception("Connection failed")

        with patch("billing_sdk.client.AsyncMQTTClient", return_value=mock_mqtt_client):
            with pytest.raises(Exception, match="Connection failed"):
                await client.connect()

        assert not client.is_connected()

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试断开连接"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        # 模拟已连接状态
        mock_mqtt_client = AsyncMock()
        client._client = mock_mqtt_client
        client._is_connected = True

        await client.disconnect()

        mock_mqtt_client.disconnect.assert_called_once()
        assert not client.is_connected()

    @pytest.mark.asyncio
    async def test_report_usage_success(self):
        """测试成功上报用量"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        # 模拟连接状态
        mock_mqtt_client = AsyncMock()
        client._client = mock_mqtt_client
        client._is_connected = True

        usage_data = UsageData(
            api_key="test_key",
            module="llm",
            model="gpt-4",
            usage=100,
            metadata={"version": "1.0"},
        )

        with patch("time.time", return_value=1234567890.123):
            await client.report_usage(usage_data)

        # 验证消息发布
        mock_mqtt_client.publish.assert_called_once()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][0] == "usage-report"

        message = json.loads(call_args[0][1])
        assert message["api_key"] == "test_key"
        assert message["module"] == "llm"
        assert message["model"] == "gpt-4"
        assert message["usage"] == 100
        assert message["metadata"] == {"version": "1.0"}
        assert message["timestamp"] == 1234567890123

    @pytest.mark.asyncio
    async def test_report_usage_not_connected(self):
        """测试未连接时上报用量"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        usage_data = UsageData(
            api_key="test_key", module="llm", model="gpt-4", usage=100
        )

        with pytest.raises(RuntimeError, match="未连接到 MQTT 代理"):
            await client.report_usage(usage_data)

    @pytest.mark.asyncio
    async def test_report_usage_publish_failure(self):
        """测试发布失败"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        # 模拟连接状态
        mock_mqtt_client = AsyncMock()
        mock_mqtt_client.publish.side_effect = Exception("Publish failed")
        client._client = mock_mqtt_client
        client._is_connected = True

        usage_data = UsageData(
            api_key="test_key", module="llm", model="gpt-4", usage=100
        )

        with pytest.raises(Exception, match="Publish failed"):
            await client.report_usage(usage_data)

    def test_is_key_valid_blocked_key(self):
        """测试被阻止的 API Key"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._blocked_keys.add("blocked_key")
        assert not client.is_key_valid("blocked_key")

    def test_is_key_valid_valid_key(self):
        """测试有效的 API Key"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._valid_keys.add("valid_key")
        assert client.is_key_valid("valid_key")

    def test_is_key_valid_unknown_key(self):
        """测试未知的 API Key"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        # 未知的 key 应该默认有效
        assert client.is_key_valid("unknown_key")

    @pytest.mark.asyncio
    async def test_handle_key_status_update_blocked(self):
        """测试处理 Key 被阻止的状态更新"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        # 先添加到有效列表
        client._valid_keys.add("test_key")

        payload = json.dumps(
            {
                "updates": [
                    {"key": "test_key", "status": "blocked", "reason": "Quota exceeded"}
                ]
            }
        )

        await client._handle_key_status_update(payload)

        # 验证 key 被移到阻止列表
        assert "test_key" not in client._valid_keys
        assert "test_key" in client._blocked_keys

    @pytest.mark.asyncio
    async def test_handle_key_status_update_ok(self):
        """测试处理 Key 恢复正常的状态更新"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        # 先添加到阻止列表
        client._blocked_keys.add("test_key")

        payload = json.dumps(
            {"updates": [{"key": "test_key", "status": "ok", "reason": ""}]}
        )

        await client._handle_key_status_update(payload)

        # 验证 key 被移到有效列表
        assert "test_key" in client._valid_keys
        assert "test_key" not in client._blocked_keys

    @pytest.mark.asyncio
    async def test_handle_key_status_update_with_callback(self):
        """测试带回调函数的状态更新"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        callback_mock = AsyncMock()
        client.set_key_status_callback(callback_mock)

        payload = json.dumps(
            {
                "updates": [
                    {"key": "test_key", "status": "blocked", "reason": "Test reason"}
                ]
            }
        )

        await client._handle_key_status_update(payload)

        # 验证回调被调用
        callback_mock.assert_called_once_with("test_key", "blocked", "Test reason")

    def test_get_valid_keys(self):
        """测试获取有效 Keys"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._valid_keys.add("key1")
        client._valid_keys.add("key2")

        valid_keys = client.get_valid_keys()
        assert valid_keys == {"key1", "key2"}

        # 返回的应该是副本
        valid_keys.add("key3")
        assert "key3" not in client._valid_keys

    def test_get_blocked_keys(self):
        """测试获取被阻止的 Keys"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._blocked_keys.add("blocked1")
        client._blocked_keys.add("blocked2")

        blocked_keys = client.get_blocked_keys()
        assert blocked_keys == {"blocked1", "blocked2"}

        # 返回的应该是副本
        blocked_keys.add("blocked3")
        assert "blocked3" not in client._blocked_keys
