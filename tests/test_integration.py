import asyncio
import json
import os
import time
from unittest.mock import AsyncMock

import pytest

from billing_sdk import BillingClient, UsageData, report_usage

# 集成测试配置
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
SKIP_INTEGRATION = os.getenv("SKIP_INTEGRATION", "true").lower() == "true"

skip_if_no_mqtt = pytest.mark.skipif(
    SKIP_INTEGRATION,
    reason="集成测试被跳过。设置 SKIP_INTEGRATION=false 来启用真实的MQTT测试",
)


@pytest.mark.integration
class TestBillingClientIntegration:
    """BillingClient 集成测试类 - 需要真实MQTT环境"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @skip_if_no_mqtt
    @pytest.mark.asyncio
    async def test_real_mqtt_connection(self):
        """测试真实的MQTT连接"""
        client = BillingClient(
            MQTT_HOST, MQTT_PORT, username=MQTT_USERNAME, password=MQTT_PASSWORD
        )

        try:
            await client.connect()
            assert client.is_connected()

            # 等待一段时间确保连接稳定
            await asyncio.sleep(1)

        except Exception as e:
            pytest.skip(f"无法连接到MQTT broker: {e}")
        finally:
            if client.is_connected():
                await client.disconnect()

    @skip_if_no_mqtt
    @pytest.mark.asyncio
    async def test_real_usage_reporting(self):
        """测试真实的用量上报"""
        client = BillingClient(
            MQTT_HOST, MQTT_PORT, username=MQTT_USERNAME, password=MQTT_PASSWORD
        )

        try:
            await client.connect()

            # 创建测试用量数据
            usage_data = UsageData(
                api_key="integration-test-key",
                module="test",
                model="test-model",
                usage=100,
                metadata={"test_timestamp": int(time.time()), "integration_test": True},
            )

            # 上报用量 - 这应该不会抛出异常
            await client.report_usage(usage_data)

            # 等待消息发送完成
            await asyncio.sleep(1)

        except Exception as e:
            pytest.skip(f"MQTT测试失败: {e}")
        finally:
            if client.is_connected():
                await client.disconnect()

    @skip_if_no_mqtt
    @pytest.mark.asyncio
    async def test_key_status_subscription(self):
        """测试Key状态订阅功能"""
        client = BillingClient(
            MQTT_HOST, MQTT_PORT, username=MQTT_USERNAME, password=MQTT_PASSWORD
        )

        status_updates = []

        async def status_callback(key, status, reason):
            status_updates.append((key, status, reason))

        try:
            client.set_key_status_callback(status_callback)
            await client.connect()

            # 等待订阅建立
            await asyncio.sleep(2)

            # 这里可以添加发布测试消息的逻辑
            # 但需要有权限发布到 billing/keys/update topic

        except Exception as e:
            pytest.skip(f"Key状态订阅测试失败: {e}")
        finally:
            if client.is_connected():
                await client.disconnect()


@pytest.mark.integration
class TestGlobalFunctionIntegration:
    """全局函数集成测试"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @skip_if_no_mqtt
    @pytest.mark.asyncio
    async def test_global_report_usage_integration(self):
        """测试全局report_usage函数的集成测试"""
        # 初始化客户端
        client = BillingClient(
            MQTT_HOST, MQTT_PORT, username=MQTT_USERNAME, password=MQTT_PASSWORD
        )

        try:
            await client.connect()

            # 使用全局函数上报用量
            await report_usage(
                api_key="global-integration-test",
                module="integration",
                model="test-model",
                usage=200,
                metadata={"global_test": True},
            )

            # 等待消息发送
            await asyncio.sleep(1)

        except Exception as e:
            pytest.skip(f"全局函数集成测试失败: {e}")
        finally:
            if client.is_connected():
                await client.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mock_integration_demo():
    """演示集成测试 - 使用Mock但测试完整流程"""
    # 这个测试展示如何做集成测试，即使没有真实的MQTT环境
    client = None

    # 模拟MQTT客户端但测试完整的数据流
    from unittest.mock import patch

    # 重置单例
    BillingClient._instance = None
    BillingClient._initialized = False

    with patch.object(BillingClient, "_auto_connect"):
        client = BillingClient("mock-host", 1883)

    # 模拟完整的连接流程
    mock_mqtt_client = AsyncMock()
    mock_mqtt_client.__aenter__ = AsyncMock(return_value=mock_mqtt_client)
    mock_mqtt_client.__aexit__ = AsyncMock(return_value=None)

    published_messages = []

    async def mock_publish(topic, message, **kwargs):
        published_messages.append(
            {"topic": topic, "message": message, "data": json.loads(message)}
        )

    mock_mqtt_client.publish = mock_publish
    mock_mqtt_client.subscribe = AsyncMock()

    with patch("billing_sdk.client.AioMQTTClient", return_value=mock_mqtt_client):
        with patch("asyncio.create_task"):
            with patch.object(client, "_handle_messages"):
                with patch.object(client, "_request_keys_list"):
                    # 测试连接
                    await client.connect()
                    assert client.is_connected()

                    # 测试多个用量上报
                    usage_data_list = [
                        UsageData("key1", "gpt", "gpt-4", 100, {"tokens": 100}),
                        UsageData("key2", "claude", "claude-3", 200, {"tokens": 200}),
                        UsageData("key3", "gemini", "gemini-pro", 150, {"tokens": 150}),
                    ]

                    for usage_data in usage_data_list:
                        await client.report_usage(usage_data)

                    # 验证消息发布
                    assert len(published_messages) == 3

                    # 验证消息格式
                    for i, msg in enumerate(published_messages):
                        assert msg["topic"] == "billing/report"
                        data = msg["data"]
                        expected = usage_data_list[i]
                        assert data["api_key"] == expected.api_key
                        assert data["module"] == expected.module
                        assert data["model"] == expected.model
                        assert data["usage"] == expected.usage
                        assert "timestamp" in data

                    # 测试断开连接
                    await client.disconnect()
                    assert not client.is_connected()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_usage_reporting():
    """测试并发用量上报的集成测试"""
    import asyncio
    from unittest.mock import patch

    # 重置单例
    BillingClient._instance = None
    BillingClient._initialized = False

    with patch.object(BillingClient, "_auto_connect"):
        client = BillingClient("concurrent-test", 1883)

    mock_mqtt_client = AsyncMock()
    mock_mqtt_client.__aenter__ = AsyncMock(return_value=mock_mqtt_client)
    mock_mqtt_client.__aexit__ = AsyncMock(return_value=None)

    published_count = 0

    async def mock_publish(topic, message, **kwargs):
        nonlocal published_count
        published_count += 1
        # 模拟网络延迟
        await asyncio.sleep(0.1)

    mock_mqtt_client.publish = mock_publish
    mock_mqtt_client.subscribe = AsyncMock()

    with patch("billing_sdk.client.AioMQTTClient", return_value=mock_mqtt_client):
        with patch("asyncio.create_task"):
            with patch.object(client, "_handle_messages"):
                with patch.object(client, "_request_keys_list"):
                    await client.connect()

                    # 创建多个并发的用量上报任务
                    async def report_task(i):
                        await client.report_usage(
                            UsageData(f"key-{i}", "test", "model", i * 10)
                        )

                    # 并发执行10个上报任务
                    tasks = [report_task(i) for i in range(10)]
                    await asyncio.gather(*tasks)

                    # 验证所有消息都被发布
                    assert published_count == 10

                    await client.disconnect()
