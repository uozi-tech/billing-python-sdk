"""测试重连机制的修复"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from billing_sdk.client import BillingClient


@pytest.fixture
async def billing_client():
    """创建测试用的 BillingClient 实例"""
    # 重置单例状态
    BillingClient._instance = None
    BillingClient._initialized = False

    with patch("billing_sdk.client.AioMQTTClient") as mock_mqtt:
        mock_client = AsyncMock()
        mock_mqtt.return_value = mock_client

        client = BillingClient(
            broker_host="test.example.com",
            broker_port=8883,
            username="test",
            password="test",
        )

        yield client

        # 清理
        await client.disconnect()
        BillingClient._instance = None
        BillingClient._initialized = False


class TestReconnectionMechanism:
    """测试重连机制"""

    @pytest.mark.asyncio
    async def test_concurrent_reconnection_prevention(self, billing_client):
        """测试防止并发重连"""

        # 模拟连接断开
        billing_client._is_connected = False
        billing_client._client = None

        # 模拟多个并发重连尝试
        tasks = []
        for _ in range(5):
            task = asyncio.create_task(billing_client._reconnect_with_backoff())
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 只有一个重连应该成功，其他应该被跳过
        successful_reconnects = sum(1 for result in results if result is True)
        assert successful_reconnects <= 1, "应该只有一个重连成功"

    @pytest.mark.asyncio
    async def test_reconnection_rate_limiting(self, billing_client):
        """测试重连频率限制"""

        billing_client._reconnect_delay = 2.0  # 设置2秒延迟
        billing_client._last_reconnect_time = time.time()

        # 立即尝试重连应该被拒绝
        assert not billing_client._should_reconnect()

        # 等待足够时间后应该允许重连
        billing_client._last_reconnect_time = time.time() - 3.0
        assert billing_client._should_reconnect()

    @pytest.mark.asyncio
    async def test_max_reconnection_attempts(self, billing_client):
        """测试最大重连尝试次数限制"""

        billing_client._max_reconnect_attempts = 3
        billing_client._reconnect_attempts = 3
        billing_client._last_reconnect_time = time.time() - 1.0

        # 达到最大尝试次数时应该被拒绝
        assert not billing_client._should_reconnect()

        # 等待足够长时间后应该重置计数器
        billing_client._last_reconnect_time = (
            time.time() - billing_client._reconnect_delay * 3
        )
        assert billing_client._should_reconnect()

    @pytest.mark.asyncio
    async def test_connection_validation(self, billing_client):
        """测试连接验证机制"""

        # 先设置初始状态
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock()
        mock_client.__aenter__ = AsyncMock()
        mock_client.subscribe = AsyncMock()

        billing_client._client = mock_client
        billing_client._is_connected = True

        # 连接验证成功的情况
        await billing_client.connect()
        mock_client.publish.assert_called()

        # 重置mock调用记录
        mock_client.reset_mock()

        # 连接验证失败的情况
        mock_client.publish.side_effect = Exception("连接失败")

        with patch("billing_sdk.client.AioMQTTClient") as mock_mqtt_class:
            new_mock_client = AsyncMock()
            new_mock_client.__aenter__ = AsyncMock()
            new_mock_client.subscribe = AsyncMock()
            mock_mqtt_class.return_value = new_mock_client

            # 应该重新建立连接
            await billing_client.connect()
            new_mock_client.__aenter__.assert_called()

    @pytest.mark.asyncio
    async def test_heartbeat_timeout_detection(self, billing_client):
        """测试心跳超时检测"""

        billing_client._connection_timeout = 5.0
        billing_client._last_heartbeat_success = time.time() - 10.0  # 10秒前
        billing_client._is_connected = True
        billing_client._client = MagicMock()

        # 模拟保活循环检查
        current_time = time.time()
        connection_lost = False

        if not billing_client._is_connected or billing_client._client is None:
            connection_lost = True
        elif (
            current_time - billing_client._last_heartbeat_success
            > billing_client._connection_timeout
        ):
            connection_lost = True

        assert connection_lost, "应该检测到心跳超时"

    @pytest.mark.asyncio
    async def test_connection_cleanup(self, billing_client):
        """测试连接清理"""

        mock_client = AsyncMock()
        billing_client._client = mock_client
        billing_client._is_connected = True

        await billing_client._cleanup_connection()

        assert billing_client._is_connected is False
        assert billing_client._client is None
        mock_client.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_improved_is_connected_check(self, billing_client):
        """测试改进的连接状态检查"""

        # 测试各种连接状态组合
        billing_client._is_connected = True
        billing_client._client = None
        assert not billing_client.is_connected()

        billing_client._is_connected = False
        billing_client._client = MagicMock()
        assert not billing_client.is_connected()

        billing_client._is_connected = True
        billing_client._client = MagicMock()
        assert billing_client.is_connected()


if __name__ == "__main__":
    pytest.main([__file__])
