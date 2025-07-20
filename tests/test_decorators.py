from unittest.mock import Mock, patch

import pytest

from billing_sdk import BillingClient
from billing_sdk.decorators import (
    _mask_api_key,
    get_billing_client,
    require_api_key,
)


class TestDecorators:
    """装饰器测试类"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    def test_mask_api_key_long(self):
        """测试长 API Key 的掩码"""
        api_key = "sk-1234567890abcdef"
        masked = _mask_api_key(api_key)
        assert masked == "sk-12345***********"

    def test_mask_api_key_short(self):
        """测试短 API Key 的掩码"""
        api_key = "short"
        masked = _mask_api_key(api_key)
        assert masked == "*****"

    def test_get_billing_client_not_initialized(self):
        """测试未初始化时获取 billing client"""
        client = get_billing_client()
        assert client is None

    def test_get_billing_client_initialized(self):
        """测试已初始化时获取 billing client"""
        with patch.object(BillingClient, "_auto_connect"):
            original = BillingClient("localhost", 8883)

        client = get_billing_client()
        assert client is original


class TestRequireApiKeyDecorator:
    """require_api_key 装饰器测试类"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @pytest.mark.asyncio
    async def test_require_api_key_success(self):
        """测试 API Key 验证成功"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        client._valid_keys.add("valid_key")

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                return "success"

        # Mock stream with metadata，使用简单对象避免AsyncMock问题
        mock_stream = Mock()
        mock_stream.metadata = [
            ("api-key", "valid_key"),
            ("session_id", "test_session"),
        ]

        service = TestService()
        result = await service.protected_method(mock_stream)

        assert result == "success"
        # 验证 API key 被清理（装饰器执行完后会清理）
        assert not hasattr(service, "_billing_api_key")

    @pytest.mark.asyncio
    async def test_require_api_key_missing(self):
        """测试缺少 API Key"""
        with patch.object(BillingClient, "_auto_connect"):
            BillingClient("localhost", 8883)

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                return "success"

        # Mock stream without API key
        mock_stream = Mock()
        mock_stream.metadata = [("session_id", "test_session")]

        service = TestService()
        with pytest.raises(Exception, match="API key is required"):
            await service.protected_method(mock_stream)

    @pytest.mark.asyncio
    async def test_require_api_key_invalid(self):
        """测试无效的 API Key"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        client._blocked_keys.add("blocked_key")
        # 停用消息处理任务避免警告
        client._message_task = None

        # 阻止_handle_messages被调用
        with patch.object(client, "_handle_messages"):

            class TestService:
                @require_api_key
                async def protected_method(self, stream):
                    return "success"

            # Mock stream with invalid API key
            mock_stream = Mock()
            mock_stream.metadata = [
                ("api-key", "blocked_key"),
                ("session_id", "test_session"),
            ]

            service = TestService()
            with pytest.raises(Exception, match="Invalid API key"):
                await service.protected_method(mock_stream)

    @pytest.mark.asyncio
    async def test_require_api_key_no_billing_client(self):
        """测试无 billing client 时的验证"""

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                return "success"

        # Mock stream with API key
        mock_stream = Mock()
        mock_stream.metadata = [("api-key", "any_key"), ("session_id", "test_session")]

        service = TestService()
        # 应该记录警告但不阻止执行
        result = await service.protected_method(mock_stream)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_require_api_key_cleanup(self):
        """测试 API Key 清理"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        client._valid_keys.add("valid_key")
        # 停用消息处理任务避免警告
        client._message_task = None

        # 阻止_handle_messages被调用
        with patch.object(client, "_handle_messages"):

            class TestService:
                @require_api_key
                async def protected_method(self, stream):
                    # 验证可以从 stream metadata 获取 API key
                    metadata = dict(stream.metadata)
                    api_key = metadata.get("api-key")
                    assert api_key == "valid_key"
                    return "success"

            mock_stream = Mock()
            mock_stream.metadata = [
                ("api-key", "valid_key"),
                ("session_id", "test_session"),
            ]

            service = TestService()
            result = await service.protected_method(mock_stream)
            assert result == "success"

    @pytest.mark.asyncio
    async def test_require_api_key_exception_cleanup(self):
        """测试异常时的 API Key 清理"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        client._valid_keys.add("valid_key")

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                raise Exception("Method failed")

        # 使用Mock代替MagicMock避免AsyncMock问题
        mock_stream = Mock()
        mock_stream.metadata = [
            ("api-key", "valid_key"),
            ("session_id", "test_session"),
        ]

        service = TestService()
        with pytest.raises(Exception, match="Method failed"):
            await service.protected_method(mock_stream)

        # 验证异常正常抛出，方法执行失败
        # 装饰器不再保存 API key 到对象中

    @pytest.mark.asyncio
    async def test_require_api_key_alternative_header(self):
        """测试使用替代的 API Key header"""
        with patch.object(BillingClient, "_auto_connect"):
            client = BillingClient("localhost", 8883)

        client._valid_keys.add("valid_key")

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                return "success"

        # 使用 'apikey' 而不是 'api-key'
        mock_stream = Mock()
        mock_stream.metadata = [("apikey", "valid_key"), ("session_id", "test_session")]

        service = TestService()
        result = await service.protected_method(mock_stream)
        assert result == "success"
