# 计费系统 Python SDK

基于 MQTT 的计费系统 Python SDK，提供用量自动上报和 API Key 验证功能。

## 特性

- 🚀 **单例模式**: 全局唯一的 MQTT 连接，避免资源浪费
- 🔒 **API Key 验证**: 自动验证 gRPC metadata 中的 API Key
- 📊 **用量上报**: 使用全局 report_usage 函数上报 API 使用量
- 🛡️ **类型安全**: 完整的类型注解和运行时检查
- ⚡ **异步优先**: 全面支持 asyncio 和异步操作
- 🔐 **默认 TLS 加密**: 默认使用 TLS 连接确保通信安全

## 前置要求

## 安装

```bash
# 基础安装
uv add billing-python-sdk

# 通过 Git 直接安装
uv add git+https://github.com/uozi-tech/billing-python-sdk.git

# 安装指定分支或标签
uv add git+https://github.com/uozi-tech/billing-python-sdk.git@main
uv add git+https://github.com/uozi-tech/billing-python-sdk.git@v1.0.0

# 或从源码安装（开发模式）
git clone https://github.com/uozi-tech/billing-python-sdk.git
cd billing-python-sdk
uv sync

# 安装开发依赖
uv sync --extra dev --extra test
```

## 安全性

### TLS 加密连接

SDK 默认使用 TLS 加密连接

- **传输加密**: 所有 MQTT 通信都通过 TLS 1.2+ 加密
- **自动连接**: 客户端自动使用安全连接

### 连接状态监控

```python
# 检查连接状态
if client.is_connected():
    print("已连接到 MQTT 代理")
else:
    print("未连接")

# 手动连接（如果需要）
await client.connect()
```

## 快速开始

### 简单示例

```python
from billing_sdk import BillingClient, require_api_key, report_usage_usage

# 初始化全局单例
client = BillingClient("localhost", 8883, "user", "pass")

class MyService:
    @require_api_key
    async def my_api(self, stream, data):
        # 业务逻辑
        result = {"output": "processed", "tokens": 100}
        
        # 从 stream metadata 获取 API key
        api_key = stream.metadata.get("api-key", "")
        
        # 上报用量
        await report_usage(
            api_key=api_key,
            module="llm",
            model="my-model",
            usage=result["tokens"]
        )
        
        return result
```

### 1. 初始化全局单例

```python
from billing_sdk import BillingClient

# 初始化全局单例（整个应用只需要初始化一次，会自动通过 TLS 连接 MQTT）
client = BillingClient(
    broker_host="localhost",
    broker_port=8883,  # TLS 默认端口
    username="your_username",
    password="your_password"
)
```

### 2. 使用 API Key 验证和用量上报

```python
from billing_sdk import require_api_key, report_usage

class YourService:
    
    @require_api_key
    async def chat_completion(self, stream, messages):
        # 你的业务逻辑
        result = {"response": "Hello, world!", "token_count": 100}
        
        # 从 stream metadata 获取 API key
        api_key = stream.metadata.get("api-key", "")
        
        # 使用全局 report_usage 函数上报用量
        await report_usage(
            api_key=api_key,
            module="llm",
            model="gpt-3.5-turbo",
            usage=result["token_count"],
            metadata={"prompt_tokens": 50, "completion_tokens": 50}
        )
        
        return result
```

## API 说明

### @require_api_key 装饰器
- 自动从 gRPC metadata 中验证 API Key
- 支持 `api-key` 和 `apikey` 两种格式
- 验证失败会抛出异常
- 在方法内部可以通过 `stream.metadata.get("api-key", "")` 获取 API Key

### report_usage 函数
全局用量上报函数，自动使用单例 BillingClient 实例：

```python
async def report_usage(
    api_key: str,
    module: str,
    model: str,
    usage: int,
    metadata: dict[str, Any] | None = None,
) -> None
```

**参数:**
- `api_key`: API 密钥
- `module`: 模块名称 (如 "llm", "tts", "asr")
- `model`: 模型名称
- `usage`: 用量数值 (int)
- `metadata`: 元数据字典 (可选)

**示例:**
```python
from billing_sdk import report_usage

# 直接上报用量
await report_usage(
    api_key="your-api-key",
    module="llm",
    model="gpt-4",
    usage=150,  # token 数量
    metadata={
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "temperature": 0.7
    }
)
```

### report_usage 方法
手动上报 API 使用量到计费系统：

```python
async def report_usage(self, usage_data: UsageData) -> None
```

**参数:**
- `usage_data`: UsageData 对象，包含以下字段：
  - `api_key`: API 密钥
  - `module`: 模块名称 (如 "llm", "tts", "asr")
  - `model`: 模型名称
  - `usage`: 用量数值 (int)
  - `metadata`: 元数据字典 (可选)

**示例:**
```python
from billing_sdk import UsageData

# 创建用量数据
usage_data = UsageData(
    api_key="your-api-key",
    module="llm",
    model="gpt-4",
    usage=150,  # token 数量
    metadata={
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "temperature": 0.7
    }
)

# 上报用量
client = get_billing_client()
if client:
    await client.report_usage(usage_data)
```

## 完整示例

```python
import asyncio
from billing_sdk import BillingClient, require_api_key, report_usage

# 初始化全局单例
client = BillingClient(
    broker_host="localhost",
    broker_port=8883,  # TLS 端口
    username="billing_user",
    password="billing_pass"
)

class LLMService:
    
    @require_api_key
    async def chat_completion(self, stream, messages):
        # 模拟处理
        await asyncio.sleep(0.1)
        result = {"content": "Hello from AI", "token_count": 100}
        
        # 从 stream metadata 获取 API key
        api_key = stream.metadata.get("api-key", "")
        
        # 使用全局 report_usage 函数上报用量
        await report_usage(
            api_key=api_key,
            module="llm",
            model="gpt-3.5-turbo",
            usage=result["token_count"],
            metadata={"prompt_length": len(str(messages))}
        )
        
        return result

async def main():
    # 等待连接建立
    await client.connect()
    
    # 使用服务
    service = LLMService()
    
    # 模拟 gRPC stream
    class MockStream:
        metadata = [('api-key', 'your-api-key')]
    
    result = await service.chat_completion(MockStream(), ["Hello"])
    print(result)
    
    # 断开连接
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

## 获取全局实例

如果需要在其他地方获取已初始化的全局单例：

```python
from billing_sdk import get_billing_client

# 获取全局单例实例
client = get_billing_client()
if client:
    # 使用 client
    pass
```

## 高级用法

### 多服务集成

```python
from billing_sdk import require_api_key, report_usage

# LLM 服务
class LLMService:
    @require_api_key
    async def generate_text(self, stream, prompt):
        result = {"text": f"Generated: {prompt}", "tokens": len(prompt) + 20}
        
        # 从 stream metadata 获取 API key
        api_key = stream.metadata.get("api-key", "")
        
        # 上报用量
        await report_usage(
            api_key=api_key,
            module="llm",
            model="gpt-4",
            usage=result["tokens"]
        )
        return result

# TTS 服务
class TTSService:
    @require_api_key
    async def synthesize(self, stream, text):
        result = {"audio": f"<audio_data>", "duration": len(text) * 0.1}
        
        # 从 stream metadata 获取 API key
        api_key = stream.metadata.get("api-key", "")
        
        # 基于文本长度计算用量
        await report_usage(
            api_key=api_key,
            module="tts",
            model="eleven-labs",
            usage=len(text),  # 以字符数为用量单位
            metadata={"text_length": len(text), "duration": result["duration"]}
        )
        return result

# ASR 服务
class ASRService:
    @require_api_key
    async def transcribe(self, stream, audio_file):
        result = {"text": "转录的文本内容", "duration": 30, "confidence": 0.95}
        
        # 从 stream metadata 获取 API key
        api_key = stream.metadata.get("api-key", "")
        
        # 基于音频时长计算用量
        await report_usage(
            api_key=api_key,
            module="asr",
            model="whisper",
            usage=int(result["duration"]),  # 以秒为用量单位
            metadata={"confidence": result["confidence"], "file": audio_file}
        )
        return result
```

### 错误处理

```python
import logging

class RobustService:
    @require_api_key
    async def safe_operation(self, stream, data):
        # 从 stream metadata 获取 API key
        api_key = stream.metadata.get("api-key", "")
        usage_reported = False
        
        try:
            # 业务逻辑
            result = process_data(data)
            
            # 成功时上报用量
            await report_usage(
                api_key=api_key,
                module="processing",
                model="data-processor",
                usage=len(str(result)),
                metadata={"status": "success"}
            )
            usage_reported = True
            
            return result
            
        except Exception as e:
            # 即使出错，也要上报用量（避免免费使用）
            if not usage_reported:
                try:
                    await report_usage(
                        api_key=api_key,
                        module="processing",
                        model="data-processor",
                        usage=1,  # 最小用量
                        metadata={"status": "error", "error": str(e)}
                    )
                except Exception as report_error:
                    logging.error(f"用量上报失败: {report_error}")
            
            logging.error(f"处理失败: {e}")
            raise
```

## 开发

### 环境设置

```bash
# 克隆项目
git clone https://github.com/your-org/billing-python-sdk.git
cd billing-python-sdk

# 安装依赖（使用 uv）
uv sync --extra dev --extra test

# 或使用便利脚本
uv run run_tests.py --install
```

### 运行测试

```bash
# 运行所有测试
uv run run_tests.py

# 运行特定类型的测试
uv run run_tests.py --unit        # 单元测试
uv run run_tests.py --integration # 集成测试

# 生成覆盖率报告
uv run run_tests.py --coverage

# 查看测试详情
uv run pytest -v

# 运行特定测试
uv run pytest tests/test_client.py::TestBillingClient::test_singleton_pattern
```

详细的测试说明请参考 [tests/README.md](tests/README.md)。

### 代码质量检查

```bash
# 代码格式检查
uv run ruff check src/ tests/

# 类型检查
uv run mypy src/

# 自动格式化
uv run ruff format src/ tests/

# 运行所有检查（测试 + 格式 + 类型）
uv run run_tests.py
```

### UV 常用命令

```bash
# 安装包
uv add <package>

# 安装开发依赖
uv add --dev <package>

# 更新依赖
uv sync

# 运行 Python 脚本
uv run python script.py

# 运行命令
uv run <command>

# 查看项目信息
uv tree
```

### 项目结构

```
billing-python-sdk/
├── src/
│   └── billing_sdk/
│       ├── __init__.py          # 公共接口
│       ├── client.py            # BillingClient、UsageData 和 report_usage 函数
│       └── decorators.py        # 装饰器实现
├── tests/
│   ├── test_client.py           # 客户端测试
│   ├── test_decorators.py       # 装饰器测试
│   └── README.md               # 测试文档
├── pyproject.toml              # 项目配置
├── uv.lock                     # 锁定的依赖版本
├── run_tests.py               # 测试运行脚本
└── README.md                  # 本文档
```

## 贡献

我们欢迎社区贡献！请遵循以下步骤：

1. **Fork 项目**
2. **创建功能分支**: `git checkout -b feature/amazing-feature`
3. **安装开发环境**: `uv sync --extra dev --extra test`
4. **提交更改**: `git commit -m 'Add amazing feature'`
5. **推送分支**: `git push origin feature/amazing-feature`
6. **创建 Pull Request**

### 贡献指南

- 所有新功能必须包含测试
- 确保测试覆盖率不低于 90%
- 遵循现有的代码风格
- 更新相关文档
- 使用 `uv run run_tests.py` 确保所有检查通过

## 许可证

MIT License
