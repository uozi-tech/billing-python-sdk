"""
使用示例测试 - 展示 SDK 的各种使用场景
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from billing_sdk import BillingClient, require_api_key, track_usage


class TestUsageExamples:
    """使用示例测试"""

    def setup_method(self):
        """每个测试方法前重置单例状态"""
        BillingClient._instance = None
        BillingClient._initialized = False

    @pytest.mark.asyncio
    async def test_basic_usage_example(self):
        """基础使用示例"""
        # 1. 初始化 BillingClient（应用启动时）
        with patch("asyncio.create_task"):
            billing_client = BillingClient(
                broker_host="mqtt.billing.company.com",
                broker_port=1883,
                username="billing_user",
                password="billing_pass",
            )

        # Mock 连接状态
        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True
        billing_client._valid_keys.add("sk-proj-1234567890abcdef")

        # 2. 定义服务类
        class OpenAIService:
            """OpenAI API 服务包装器"""

            @require_api_key
            @track_usage("llm", "gpt-3.5-turbo")
            async def simple_chat(self, stream, message: str):
                """简单的聊天接口"""
                # 实际会调用 OpenAI API
                return {
                    "response": f"AI: 收到您的消息 '{message}'",
                    "tokens_used": len(message) + 10,
                }

        # 3. 使用服务
        service = OpenAIService()

        # Mock gRPC stream
        mock_stream = MagicMock()
        mock_stream.metadata = [("api-key", "sk-proj-1234567890abcdef")]

        # 调用服务
        result = await service.simple_chat(mock_stream, "你好")

        # 验证结果
        assert "收到您的消息" in result["response"]

        # 验证用量自动上报
        mock_mqtt_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_custom_usage_calculator_example(self):
        """自定义用量计算器示例"""
        with patch("asyncio.create_task"):
            billing_client = BillingClient("localhost", 1883)

        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True
        billing_client._valid_keys.add("openai-key-123")

        # 自定义用量计算函数
        def calculate_openai_tokens(args, kwargs, result) -> int:
            """从 OpenAI 响应中提取实际 token 使用量"""
            if isinstance(result, dict) and "usage" in result:
                return result["usage"]["total_tokens"]
            # 降级到简单估算
            return len(str(result)) // 4

        # 自定义元数据提取函数
        def extract_openai_metadata(args, kwargs, result) -> dict:
            """提取 OpenAI 相关元数据"""
            metadata = {
                "model": kwargs.get("model", "unknown"),
                "temperature": kwargs.get("temperature", 0.7),
                "max_tokens": kwargs.get("max_tokens", 150),
            }

            if isinstance(result, dict):
                metadata.update(
                    {
                        "finish_reason": result.get("finish_reason", "stop"),
                        "created": result.get("created", 0),
                    }
                )

            return metadata

        class AdvancedOpenAIService:
            """高级 OpenAI 服务"""

            @require_api_key
            @track_usage(
                "llm", "gpt-4", calculate_openai_tokens, extract_openai_metadata
            )
            async def chat_completion(
                self,
                stream,
                messages: list,
                model: str = "gpt-4",
                temperature: float = 0.7,
                max_tokens: int = 150,
            ):
                """聊天完成接口，支持完整参数"""
                # 模拟 OpenAI API 响应
                total_input_tokens = (
                    sum(len(msg.get("content", "")) for msg in messages) // 4
                )
                output_tokens = 50  # 模拟输出

                return {
                    "id": "chatcmpl-123",
                    "object": "chat.completion",
                    "created": 1677652288,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "这是 AI 的回复内容。",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": total_input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": total_input_tokens + output_tokens,
                    },
                }

        service = AdvancedOpenAIService()
        mock_stream = MagicMock()
        mock_stream.metadata = [("api-key", "openai-key-123")]

        # 调用服务
        messages = [{"role": "user", "content": "你好，请介绍一下人工智能的发展历史"}]

        result = await service.chat_completion(
            mock_stream, messages, model="gpt-4", temperature=0.8, max_tokens=200
        )

        # 验证响应格式
        assert result["model"] == "gpt-4"
        assert "usage" in result
        assert result["usage"]["total_tokens"] > 0

        # 验证用量上报
        mock_mqtt_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_services_example(self):
        """多个服务使用示例"""
        with patch("asyncio.create_task"):
            billing_client = BillingClient("localhost", 1883)

        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True

        # 添加不同服务的 API keys
        billing_client._valid_keys.update(
            ["openai-key-123", "elevenlabs-key-456", "whisper-key-789"]
        )

        # LLM 服务
        class LLMService:
            @require_api_key
            @track_usage("llm", "gpt-4")
            async def generate_text(self, stream, prompt: str):
                return {"text": f"Generated: {prompt}", "tokens": len(prompt) + 20}

        # TTS 服务
        class TTSService:
            @require_api_key
            @track_usage(
                "tts", "eleven-labs", lambda args, kwargs, result: len(args[1])
            )
            async def synthesize(self, stream, text: str):
                return {
                    "audio": f"<audio_for_{len(text)}_chars>",
                    "duration": len(text) * 0.1,
                }

        # ASR 服务
        class ASRService:
            @require_api_key
            @track_usage(
                "asr", "whisper", lambda args, kwargs, result: result.get("duration", 0)
            )
            async def transcribe(self, stream, audio_file: str):
                return {"text": "转录的文本内容", "duration": 30, "confidence": 0.95}

        # 创建服务实例
        llm_service = LLMService()
        tts_service = TTSService()
        asr_service = ASRService()

        # 模拟不同的 API keys
        llm_stream = MagicMock()
        llm_stream.metadata = [("api-key", "openai-key-123")]

        tts_stream = MagicMock()
        tts_stream.metadata = [("api-key", "elevenlabs-key-456")]

        asr_stream = MagicMock()
        asr_stream.metadata = [("api-key", "whisper-key-789")]

        # 并发调用不同服务
        results = await asyncio.gather(
            llm_service.generate_text(llm_stream, "写一首诗"),
            tts_service.synthesize(tts_stream, "这是要转换为语音的文本"),
            asr_service.transcribe(asr_stream, "audio_file.wav"),
        )

        # 验证所有服务都正常工作
        assert "Generated: 写一首诗" in results[0]["text"]
        assert "audio_for_11_chars" in results[1]["audio"]  # "这是要转换为语音的文本" 是 11 个字符
        assert results[2]["text"] == "转录的文本内容"

        # 验证所有服务都上报了用量
        assert mock_mqtt_client.publish.call_count == 3

    @pytest.mark.asyncio
    async def test_error_handling_example(self):
        """错误处理示例"""
        with patch("asyncio.create_task"):
            billing_client = BillingClient("localhost", 1883)

        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True

        class RobustService:
            """健壮的服务，演示错误处理"""

            @require_api_key
            @track_usage("llm", "robust-model")
            async def risky_operation(self, stream, data: str):
                """可能失败的操作"""
                if data == "fail":
                    raise ValueError("操作失败")
                elif data == "timeout":
                    await asyncio.sleep(0.1)  # 模拟超时
                    raise TimeoutError("操作超时")
                else:
                    return {"result": f"处理结果: {data}"}

        service = RobustService()

        # 测试正常情况
        mock_stream = MagicMock()
        mock_stream.metadata = [("api-key", "valid-key")]
        billing_client._valid_keys.add("valid-key")

        result = await service.risky_operation(mock_stream, "normal")
        assert "处理结果: normal" in result["result"]

        # 测试业务异常（用量仍应上报）
        with pytest.raises(ValueError, match="操作失败"):
            await service.risky_operation(mock_stream, "fail")

        # 测试超时异常
        with pytest.raises(asyncio.TimeoutError):
            await service.risky_operation(mock_stream, "timeout")

        # 验证即使有异常，用量上报仍然工作
        assert mock_mqtt_client.publish.call_count >= 1

    @pytest.mark.asyncio
    async def test_batch_processing_example(self):
        """批处理示例"""
        with patch("asyncio.create_task"):
            billing_client = BillingClient("localhost", 1883)

        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True
        billing_client._valid_keys.add("batch-key")

        def calculate_batch_usage(args, kwargs, result) -> int:
            """计算批处理的用量"""
            items = args[1] if len(args) > 1 else kwargs.get("items", [])
            return len(items)

        def extract_batch_metadata(args, kwargs, result) -> dict:
            """提取批处理元数据"""
            items = args[1] if len(args) > 1 else kwargs.get("items", [])
            return {
                "batch_size": len(items),
                "processing_time": result.get("processing_time", 0),
                "success_count": result.get("success_count", 0),
                "error_count": result.get("error_count", 0),
            }

        class BatchService:
            """批处理服务"""

            @require_api_key
            @track_usage(
                "batch", "text-processor", calculate_batch_usage, extract_batch_metadata
            )
            async def process_batch(self, stream, items: list):
                """批量处理文本"""
                success_count = 0
                error_count = 0
                results = []

                for item in items:
                    try:
                        # 模拟处理每个项目
                        if item.startswith("error"):
                            raise ValueError("处理失败")
                        results.append(f"processed: {item}")
                        success_count += 1
                    except ValueError:
                        results.append(f"error: {item}")
                        error_count += 1

                return {
                    "results": results,
                    "success_count": success_count,
                    "error_count": error_count,
                    "processing_time": len(items) * 10,  # 模拟处理时间
                }

        service = BatchService()
        mock_stream = MagicMock()
        mock_stream.metadata = [("api-key", "batch-key")]

        # 批量处理
        batch_items = ["text1", "text2", "error_text", "text3", "text4"]

        result = await service.process_batch(mock_stream, batch_items)

        # 验证处理结果
        assert result["success_count"] == 4
        assert result["error_count"] == 1
        assert len(result["results"]) == 5

        # 验证用量上报
        mock_mqtt_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_streaming_example(self):
        """流式处理示例"""
        with patch("asyncio.create_task"):
            billing_client = BillingClient("localhost", 1883)

        mock_mqtt_client = AsyncMock()
        billing_client._client = mock_mqtt_client
        billing_client._is_connected = True
        billing_client._valid_keys.add("stream-key")

        def calculate_stream_usage(args, kwargs, result) -> int:
            """计算流式处理的用量"""
            # 统计生成的 chunk 数量
            chunks = result.get("chunks", [])
            return len(chunks)

        class StreamingService:
            """流式服务"""

            @require_api_key
            @track_usage("llm", "streaming-gpt", calculate_stream_usage)
            async def streaming_chat(self, stream, prompt: str):
                """流式聊天"""
                chunks = []

                # 模拟流式生成
                response_parts = ["这", "是", "一个", "流式", "响应", "的", "示例"]

                for part in response_parts:
                    chunks.append({"delta": {"content": part}, "finish_reason": None})
                    await asyncio.sleep(0.001)  # 模拟流式延迟

                # 最后一个 chunk
                chunks.append({"delta": {}, "finish_reason": "stop"})

                return {
                    "chunks": chunks,
                    "total_content": "".join(
                        part["delta"].get("content", "") for part in chunks
                    ),
                }

        service = StreamingService()
        mock_stream = MagicMock()
        mock_stream.metadata = [("api-key", "stream-key")]

        result = await service.streaming_chat(mock_stream, "请流式生成回复")

        # 验证流式结果
        assert len(result["chunks"]) == 8  # 7个内容 chunk + 1个结束 chunk
        assert result["total_content"] == "这是一个流式响应的示例"

        # 验证用量上报
        mock_mqtt_client.publish.assert_called_once()
