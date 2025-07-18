from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from billing_sdk import BillingClient, UsageData
from billing_sdk.decorators import (
    _mask_api_key,
    get_billing_client,
    require_api_key,
    track_usage,
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
        with patch("asyncio.create_task"):
            original = BillingClient("localhost", 1883)

        client = get_billing_client()
        assert client is original


class TestTrackUsageDecorator:
    """track_usage 装饰器测试类"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @pytest.mark.asyncio
    async def test_track_usage_async_success(self):
        """测试异步函数用量追踪成功"""
        # 初始化 billing client
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        # Mock 连接状态
        client._is_connected = True
        mock_report_usage = AsyncMock()
        client.report_usage = mock_report_usage

        class TestService:
            def __init__(self):
                self._billing_api_key = "test_key"

            @track_usage("llm", "gpt-4")
            async def call_api(self, prompt):
                return {"result": "success", "tokens": 100}

        service = TestService()
        result = await service.call_api("Hello")

        # 验证原函数返回值
        assert result == {"result": "success", "tokens": 100}

        # 验证用量上报被调用
        mock_report_usage.assert_called_once()
        usage_data = mock_report_usage.call_args[0][0]
        assert isinstance(usage_data, UsageData)
        assert usage_data.api_key == "test_key"
        assert usage_data.module == "llm"
        assert usage_data.model == "gpt-4"
        assert usage_data.usage == 1  # 默认用量

    @pytest.mark.asyncio
    async def test_track_usage_async_with_calculator(self):
        """测试带用量计算器的异步函数"""
        # 初始化 billing client
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._is_connected = True
        mock_report_usage = AsyncMock()
        client.report_usage = mock_report_usage

        def calculate_usage(args, kwargs, result) -> int:
            return result.get("tokens", 1)

        def extract_metadata(args, kwargs, result) -> dict:
            prompt = args[0] if len(args) > 0 else kwargs.get("prompt", "")
            return {"prompt_length": len(prompt)}

        class TestService:
            def __init__(self):
                self._billing_api_key = "test_key"

            @track_usage("llm", "gpt-4", calculate_usage, extract_metadata)
            async def call_api(self, prompt):
                return {"result": "success", "tokens": 150}

        service = TestService()
        await service.call_api("Hello World")

        # 验证用量上报
        mock_report_usage.assert_called_once()
        usage_data = mock_report_usage.call_args[0][0]
        assert usage_data.usage == 150
        assert usage_data.metadata == {"prompt_length": 11}

    @pytest.mark.asyncio
    async def test_track_usage_async_no_api_key(self):
        """测试无 API Key 时的异步函数"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._is_connected = True
        mock_report_usage = AsyncMock()
        client.report_usage = mock_report_usage

        class TestService:
            @track_usage("llm", "gpt-4")
            async def call_api(self, prompt):
                return {"result": "success"}

        service = TestService()
        result = await service.call_api("Hello")

        # 函数应该正常执行
        assert result == {"result": "success"}
        # 但不应该上报用量
        mock_report_usage.assert_not_called()

    @pytest.mark.asyncio
    async def test_track_usage_async_no_billing_client(self):
        """测试无 billing client 时的异步函数"""

        class TestService:
            def __init__(self):
                self._billing_api_key = "test_key"

            @track_usage("llm", "gpt-4")
            async def call_api(self, prompt):
                return {"result": "success"}

        service = TestService()
        result = await service.call_api("Hello")

        # 函数应该正常执行
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_track_usage_async_report_failure(self):
        """测试上报失败时的异步函数"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._is_connected = True
        mock_report_usage = AsyncMock(side_effect=Exception("Report failed"))
        client.report_usage = mock_report_usage

        class TestService:
            def __init__(self):
                self._billing_api_key = "test_key"

            @track_usage("llm", "gpt-4")
            async def call_api(self, prompt):
                return {"result": "success"}

        service = TestService()
        # 即使上报失败，函数也应该正常执行
        result = await service.call_api("Hello")
        assert result == {"result": "success"}

    def test_track_usage_sync_success(self):
        """测试同步函数用量追踪成功"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._is_connected = True

        class TestService:
            def __init__(self):
                self._billing_api_key = "test_key"

            @track_usage("llm", "gpt-4")
            def call_api(self, prompt):
                return {"result": "success"}

        with patch("asyncio.create_task") as mock_create_task:
            service = TestService()
            result = service.call_api("Hello")

            # 验证函数正常执行
            assert result == {"result": "success"}
            # 验证创建了异步任务进行上报
            mock_create_task.assert_called()

    def test_track_usage_invalid_usage_calculator(self):
        """测试无效的用量计算器"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._is_connected = True
        mock_report_usage = AsyncMock()
        client.report_usage = mock_report_usage

        def invalid_calculator(args, kwargs, result) -> str:  # 返回错误类型
            return "not_an_int"

        class TestService:
            def __init__(self):
                self._billing_api_key = "test_key"

            @track_usage("llm", "gpt-4", invalid_calculator)
            def call_api(self, prompt):
                return {"result": "success"}

        with patch("asyncio.create_task"):
            service = TestService()
            service.call_api("Hello")

    def test_track_usage_calculator_exception(self):
        """测试用量计算器抛出异常"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._is_connected = True

        def failing_calculator(args, kwargs, result) -> int:
            raise Exception("Calculator failed")

        class TestService:
            def __init__(self):
                self._billing_api_key = "test_key"

            @track_usage("llm", "gpt-4", failing_calculator)
            def call_api(self, prompt):
                return {"result": "success"}

        with patch("asyncio.create_task"):
            service = TestService()
            result = service.call_api("Hello")
            # 函数应该正常执行，使用默认用量
            assert result == {"result": "success"}


class TestRequireApiKeyDecorator:
    """require_api_key 装饰器测试类"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @pytest.mark.asyncio
    async def test_require_api_key_success(self):
        """测试 API Key 验证成功"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._valid_keys.add("valid_key")

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                return "success"

        # Mock stream with metadata
        mock_stream = MagicMock()
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
        with patch("asyncio.create_task"):
            BillingClient("localhost", 1883)

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                return "success"

        # Mock stream without API key
        mock_stream = MagicMock()
        mock_stream.metadata = [("session_id", "test_session")]

        service = TestService()
        with pytest.raises(Exception, match="API key is required"):
            await service.protected_method(mock_stream)

    @pytest.mark.asyncio
    async def test_require_api_key_invalid(self):
        """测试无效的 API Key"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._blocked_keys.add("blocked_key")

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                return "success"

        # Mock stream with invalid API key
        mock_stream = MagicMock()
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
        mock_stream = MagicMock()
        mock_stream.metadata = [("api-key", "any_key"), ("session_id", "test_session")]

        service = TestService()
        # 应该记录警告但不阻止执行
        result = await service.protected_method(mock_stream)
        assert result == "success"

    @pytest.mark.asyncio
    async def test_require_api_key_cleanup(self):
        """测试 API Key 清理"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._valid_keys.add("valid_key")

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                # 验证 API key 在执行期间存在
                assert hasattr(self, "_billing_api_key")
                assert self._billing_api_key == "valid_key"
                return "success"

        mock_stream = MagicMock()
        mock_stream.metadata = [
            ("api-key", "valid_key"),
            ("session_id", "test_session"),
        ]

        service = TestService()
        await service.protected_method(mock_stream)

        # 验证 API key 被清理
        assert not hasattr(service, "_billing_api_key")

    @pytest.mark.asyncio
    async def test_require_api_key_exception_cleanup(self):
        """测试异常时的 API Key 清理"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._valid_keys.add("valid_key")

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                raise Exception("Method failed")

        mock_stream = MagicMock()
        mock_stream.metadata = [
            ("api-key", "valid_key"),
            ("session_id", "test_session"),
        ]

        service = TestService()
        with pytest.raises(Exception, match="Method failed"):
            await service.protected_method(mock_stream)

        # 即使有异常，API key 也应该被清理
        assert not hasattr(service, "_billing_api_key")

    @pytest.mark.asyncio
    async def test_require_api_key_alternative_header(self):
        """测试备用的 API Key 头部格式"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._valid_keys.add("valid_key")

        class TestService:
            @require_api_key
            async def protected_method(self, stream):
                return "success"

        # 使用 'apikey' 而不是 'api-key'
        mock_stream = MagicMock()
        mock_stream.metadata = [("apikey", "valid_key"), ("session_id", "test_session")]

        service = TestService()
        result = await service.protected_method(mock_stream)
        assert result == "success"


class TestIntegration:
    """集成测试"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @pytest.mark.asyncio
    async def test_full_flow(self):
        """测试完整的验证和用量追踪流程"""
        with patch("asyncio.create_task"):
            client = BillingClient("localhost", 1883)

        client._is_connected = True
        client._valid_keys.add("valid_key")
        mock_report_usage = AsyncMock()
        client.report_usage = mock_report_usage

        def calculate_tokens(args, kwargs, result) -> int:
            return len(result.get("text", ""))

        class AIService:
            @require_api_key
            @track_usage("llm", "gpt-4", calculate_tokens)
            async def generate_text(self, stream, prompt):
                return {"text": "Hello, world! This is AI generated text."}

        # Mock stream with valid API key
        mock_stream = MagicMock()
        mock_stream.metadata = [
            ("api-key", "valid_key"),
            ("session_id", "test_session"),
        ]

        service = AIService()
        result = await service.generate_text(mock_stream, "Generate some text")

        # 验证函数正常执行
        assert result == {"text": "Hello, world! This is AI generated text."}

        # 验证用量上报被调用
        mock_report_usage.assert_called_once()
        usage_data = mock_report_usage.call_args[0][0]
        assert usage_data.api_key == "valid_key"
        assert usage_data.module == "llm"
        assert usage_data.model == "gpt-4"
        assert (
            usage_data.usage == 40
        )  # "Hello, world! This is AI generated text." 的长度

        # 验证 API key 被清理
        assert not hasattr(service, "_billing_api_key")
