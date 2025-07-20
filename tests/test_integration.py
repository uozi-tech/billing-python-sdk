"""
集成测试 - 测试完整的使用场景
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from billing_sdk import BillingClient, UsageData, require_api_key, track_usage


@pytest.mark.integration
class TestRealWorldScenarios:
    """真实世界场景测试"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @pytest.mark.asyncio
    async def test_llm_service_complete_flow(self):
        """测试 LLM 服务的完整流程"""
        # 1. 初始化计费客户端
        with patch.object(BillingClient, "_auto_connect"):
            billing_client = BillingClient(
                broker_host="localhost",
                broker_port=8883,
                username="test_user",
                password="test_pass",
            )

        # Mock MQTT 连接
        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True
        billing_client._valid_keys.add("sk-1234567890abcdef")

        # 2. 定义真实的 LLM 服务
        def calculate_token_usage(args, kwargs, result) -> int:
            """计算 token 使用量"""
            if "usage" in result:
                return result["usage"]["total_tokens"]
            return len(result.get("content", "")) // 4  # 简单估算

        def extract_model_metadata(args, kwargs, result) -> dict:
            """提取模型元数据"""
            return {
                "prompt_length": len(args[1]),  # prompt 参数
                "model_version": result.get("model", "unknown"),
                "finish_reason": result.get("finish_reason", "stop"),
                "response_time_ms": result.get("response_time", 0),
            }

        class LLMService:
            """LLM 服务示例"""

            @require_api_key
            @track_usage("llm", "gpt-4", calculate_token_usage, extract_model_metadata)
            async def chat_completion(
                self, stream, prompt: str, temperature: float = 0.7
            ):
                """聊天完成接口"""
                # 模拟 LLM API 调用
                await asyncio.sleep(0.01)  # 模拟网络延迟

                return {
                    "content": f"这是对 '{prompt}' 的回复",
                    "model": "gpt-4-0125-preview",
                    "usage": {
                        "prompt_tokens": len(prompt) // 4,
                        "completion_tokens": 20,
                        "total_tokens": len(prompt) // 4 + 20,
                    },
                    "finish_reason": "stop",
                    "response_time": 150,
                }

            @require_api_key
            @track_usage(
                "llm", "gpt-4-vision", calculate_token_usage, extract_model_metadata
            )
            async def vision_analysis(self, stream, image_url: str, prompt: str):
                """视觉分析接口"""
                await asyncio.sleep(0.02)  # 模拟图像处理时间

                return {
                    "content": f"图像分析结果: {prompt}",
                    "model": "gpt-4-vision-preview",
                    "usage": {
                        "prompt_tokens": 200,  # 图像 token
                        "completion_tokens": 30,
                        "total_tokens": 230,
                    },
                    "finish_reason": "stop",
                    "response_time": 300,
                }

        # 3. 测试正常流程
        service = LLMService()

        # Mock gRPC stream
        mock_stream = MagicMock()
        mock_stream.metadata = [
            ("api-key", "sk-1234567890abcdef"),
            ("session_id", "session_123"),
            ("user_id", "user_456"),
        ]

        # 执行聊天完成
        result1 = await service.chat_completion(
            mock_stream, "你好世界", temperature=0.8
        )

        # 验证结果
        assert "这是对 '你好世界' 的回复" in result1["content"]
        assert result1["usage"]["total_tokens"] == 21  # 1 + 20

        # 执行视觉分析
        result2 = await service.vision_analysis(
            mock_stream, "https://example.com/image.jpg", "描述这张图片"
        )

        assert "图像分析结果" in result2["content"]
        assert result2["usage"]["total_tokens"] == 230

        # 4. 验证用量上报
        assert mock_mqtt_client.publish.call_count == 2

        # 检查第一次上报（聊天完成）
        first_call = mock_mqtt_client.publish.call_args_list[0]
        assert first_call[0][0] == "billing/report"
        first_message = json.loads(first_call[0][1])
        assert first_message["api_key"] == "sk-1234567890abcdef"
        assert first_message["module"] == "llm"
        assert first_message["model"] == "gpt-4"
        assert first_message["usage"] == 21
        assert first_message["metadata"]["prompt_length"] == 4  # "你好世界" 是 4 个字符
        assert first_message["metadata"]["model_version"] == "gpt-4-0125-preview"

        # 检查第二次上报（视觉分析）
        second_call = mock_mqtt_client.publish.call_args_list[1]
        second_message = json.loads(second_call[0][1])
        assert second_message["model"] == "gpt-4-vision"
        assert second_message["usage"] == 230

    @pytest.mark.asyncio
    async def test_tts_service_with_error_handling(self):
        """测试 TTS 服务及错误处理"""
        with patch.object(BillingClient, "_auto_connect"):
            billing_client = BillingClient("localhost", 8883)

        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True
        billing_client._valid_keys.add("tts-key-123")

        def calculate_audio_usage(args, kwargs, result) -> int:
            """计算音频使用量（字符数）"""
            text = args[1] if len(args) > 1 else kwargs.get("text", "")
            return len(text)

        def extract_tts_metadata(args, kwargs, result) -> dict:
            """提取 TTS 元数据"""
            return {
                "voice": kwargs.get("voice", "default"),
                "speed": kwargs.get("speed", 1.0),
                "audio_format": result.get("format", "mp3"),
                "duration_seconds": result.get("duration", 0),
            }

        class TTSService:
            """TTS 服务示例"""

            @require_api_key
            @track_usage("tts", "edge-tts", calculate_audio_usage, extract_tts_metadata)
            async def synthesize_speech(
                self,
                stream,
                text: str,
                voice: str = "zh-CN-XiaoxiaoNeural",
                speed: float = 1.0,
            ):
                """语音合成接口"""
                if not text.strip():
                    raise ValueError("文本不能为空")

                # 模拟 TTS 处理
                await asyncio.sleep(len(text) * 0.001)  # 基于文本长度的处理时间

                return {
                    "audio_data": f"<binary_audio_for_{len(text)}_chars>",
                    "format": "mp3",
                    "duration": len(text) * 0.1,  # 简单估算
                    "sample_rate": 24000,
                }

        service = TTSService()
        mock_stream = MagicMock()
        mock_stream.metadata = [("api-key", "tts-key-123")]

        # 测试正常情况
        result = await service.synthesize_speech(
            mock_stream,
            "这是一段测试文本，用于语音合成。",
            voice="zh-CN-XiaoxiaoNeural",
            speed=1.2,
        )

        assert "binary_audio" in result["audio_data"]
        assert result["format"] == "mp3"

        # 验证用量上报
        mock_mqtt_client.publish.assert_called_once()
        call_args = mock_mqtt_client.publish.call_args
        message = json.loads(call_args[0][1])
        assert message["module"] == "tts"
        assert message["model"] == "edge-tts"
        assert message["usage"] == 16  # "这是一段测试文本，用于语音合成。" 是 16 个字符
        assert message["metadata"]["voice"] == "zh-CN-XiaoxiaoNeural"
        assert message["metadata"]["speed"] == 1.2

        # 测试错误情况
        with pytest.raises(ValueError, match="文本不能为空"):
            await service.synthesize_speech(mock_stream, "")

    @pytest.mark.asyncio
    async def test_api_key_lifecycle(self):
        """测试 API Key 生命周期管理"""
        with patch.object(BillingClient, "_auto_connect"):
            billing_client = BillingClient("localhost", 8883)

        # 初始状态：key 未知但假设有效
        assert billing_client.is_key_valid("new_key_123")

        # 模拟接收到 key 状态更新
        await billing_client._handle_key_status_update(
            json.dumps(
                {
                    "updates": [
                        {"key": "new_key_123", "status": "ok", "reason": ""},
                        {
                            "key": "blocked_key_456",
                            "status": "blocked",
                            "reason": "Quota exceeded",
                        },
                    ]
                }
            )
        )

        # 验证 key 状态
        assert billing_client.is_key_valid("new_key_123")
        assert not billing_client.is_key_valid("blocked_key_456")
        assert "new_key_123" in billing_client.get_valid_keys()
        assert "blocked_key_456" in billing_client.get_blocked_keys()

        # 模拟 key 被阻止
        await billing_client._handle_key_status_update(
            json.dumps(
                {
                    "updates": [
                        {
                            "key": "new_key_123",
                            "status": "blocked",
                            "reason": "Abuse detected",
                        }
                    ]
                }
            )
        )

        assert not billing_client.is_key_valid("new_key_123")
        assert "new_key_123" not in billing_client.get_valid_keys()
        assert "new_key_123" in billing_client.get_blocked_keys()

    @pytest.mark.asyncio
    async def test_concurrent_requests(self):
        """测试并发请求处理"""
        with patch.object(BillingClient, "_auto_connect"):
            billing_client = BillingClient("localhost", 8883)

        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True

        # 添加多个有效 key
        for i in range(5):
            billing_client._valid_keys.add(f"key_{i}")

        class ConcurrentService:
            @require_api_key
            @track_usage("api", "concurrent-test")
            async def process_request(self, stream, request_id: int):
                # 模拟不同的处理时间
                await asyncio.sleep(0.01 + (request_id % 3) * 0.01)
                return {"request_id": request_id, "status": "processed"}

        # 创建并发请求，每个请求使用独立的服务实例
        tasks = []
        for i in range(10):
            service_instance = ConcurrentService()
            mock_stream = MagicMock()
            mock_stream.metadata = [("api-key", f"key_{i % 5}")]  # 循环使用 5 个 key

            task = service_instance.process_request(mock_stream, i)
            tasks.append(task)

        # 并发执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 验证所有请求都成功
        for i, result in enumerate(results):
            assert not isinstance(result, Exception)
            assert result["request_id"] == i
            assert result["status"] == "processed"

        # 验证用量上报次数
        assert mock_mqtt_client.publish.call_count == 10

    @pytest.mark.asyncio
    async def test_connection_resilience(self):
        """测试连接恢复能力"""
        with patch.object(BillingClient, "_auto_connect"):
            billing_client = BillingClient("localhost", 8883)

        mock_mqtt_client = AsyncMock()

        # 第一次连接失败
        mock_mqtt_client.__aenter__.side_effect = [
            Exception("Connection refused"),
            None,  # 第二次成功
        ]
        mock_mqtt_client.subscribe = AsyncMock()

        with patch("billing_sdk.client.AioMQTTClient", return_value=mock_mqtt_client):
            # 第一次连接应该失败
            with pytest.raises(Exception, match="Connection refused"):
                await billing_client.connect()

            # 重置 side_effect，第二次连接成功
            mock_mqtt_client.__aenter__.side_effect = None

            # 创建mock任务用于消息处理
            mock_task = AsyncMock()
            with patch("asyncio.create_task", return_value=mock_task):
                await billing_client.connect()

            assert billing_client.is_connected()

    @pytest.mark.asyncio
    async def test_usage_data_validation(self):
        """测试用量数据验证"""
        with patch.object(BillingClient, "_auto_connect"):
            billing_client = BillingClient("localhost", 8883)

        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True
        # 停用消息处理任务避免警告
        billing_client._message_task = None

        # 彻底阻止_handle_messages被调用
        with patch.object(billing_client, "_handle_messages"):
            # 测试有效的用量数据
            valid_usage_data = UsageData(
                api_key="test_key",
                module="llm",
                model="gpt-4",
                usage=100,
                metadata={"tokens": 100},
            )

            await billing_client.report_usage(valid_usage_data)
            mock_mqtt_client.publish.assert_called_once()

            # 重置mock
            mock_mqtt_client.reset_mock()

            # 测试最小用量数据
            minimal_usage_data = UsageData(
                api_key="test_key", module="llm", model="gpt-3.5", usage=50
            )

            await billing_client.report_usage(minimal_usage_data)
            mock_mqtt_client.publish.assert_called_once()
