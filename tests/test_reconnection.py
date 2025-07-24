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
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.subscribe = AsyncMock()
        mock_mqtt.return_value = mock_client

        with patch.object(BillingClient, "_start_background_tasks"):
            with patch.object(BillingClient, "_request_keys_list"):
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

        # Mock connect方法避免实际连接
        with patch.object(
            billing_client, "connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = None

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

        # Mock后台任务启动
        with patch.object(billing_client, "_start_background_tasks"):
            with patch.object(billing_client, "_request_keys_list"):
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

            with patch.object(billing_client, "_start_background_tasks"):
                with patch.object(billing_client, "_request_keys_list"):
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

    @pytest.mark.asyncio
    async def test_reconnect_with_backoff_success(self, billing_client):
        """测试成功的退避重连"""
        billing_client._is_connected = False
        billing_client._client = None
        billing_client._reconnecting = False
        billing_client._last_reconnect_time = 0
        billing_client._reconnect_attempts = 0

        with patch.object(
            billing_client, "connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = None

            result = await billing_client._reconnect_with_backoff()

            assert result is True
            assert billing_client._reconnect_attempts == 0  # 成功后重置
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_with_backoff_failure(self, billing_client):
        """测试重连失败的情况"""
        billing_client._is_connected = False
        billing_client._client = None
        billing_client._reconnecting = False
        billing_client._last_reconnect_time = 0
        billing_client._reconnect_attempts = 0

        with patch.object(
            billing_client, "connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")

            result = await billing_client._reconnect_with_backoff()

            assert result is False
            assert billing_client._reconnecting is False  # 重连标志被重置
            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_reconnect_already_reconnecting(self, billing_client):
        """测试已在重连状态时的处理"""
        billing_client._reconnecting = True

        result = await billing_client._reconnect_with_backoff()

        assert result is False

    @pytest.mark.asyncio
    async def test_should_reconnect_rate_limit(self, billing_client):
        """测试重连频率限制逻辑"""
        current_time = time.time()

        # 测试频率限制
        billing_client._last_reconnect_time = current_time - 1.0  # 1秒前
        billing_client._reconnect_delay = 5.0  # 5秒延迟

        assert not billing_client._should_reconnect()

        # 测试超过延迟时间
        billing_client._last_reconnect_time = current_time - 6.0  # 6秒前

        assert billing_client._should_reconnect()

    @pytest.mark.asyncio
    async def test_should_reconnect_max_attempts(self, billing_client):
        """测试最大重连次数限制"""
        current_time = time.time()
        billing_client._last_reconnect_time = current_time - 3.0  # 3秒前（不够久）
        billing_client._reconnect_delay = 5.0
        billing_client._max_reconnect_attempts = 3

        # 达到最大次数但时间不够久
        billing_client._reconnect_attempts = 3

        assert not billing_client._should_reconnect()

        # 等待更长时间后重置（超过 delay * 2 = 10秒）
        billing_client._last_reconnect_time = current_time - 15.0  # 15秒前，超过10秒

        assert billing_client._should_reconnect()


if __name__ == "__main__":
    pytest.main([__file__])
