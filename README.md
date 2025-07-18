# 计费系统 Python SDK

基于 MQTT 的计费系统 Python SDK，提供用量自动上报和 API Key 验证功能。

## 特性

- 🚀 **单例模式**: 全局唯一的 MQTT 连接，避免资源浪费
- 🔒 **API Key 验证**: 自动验证 gRPC metadata 中的 API Key
- 📊 **自动用量上报**: 装饰器自动追踪和上报 API 使用量
- 🛡️ **类型安全**: 完整的类型注解和运行时检查
- ⚡ **异步优先**: 全面支持 asyncio 和异步操作
- 🔧 **高度可配置**: 自定义用量计算和元数据提取

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

## 快速开始

### 1. 初始化全局单例

```python
from billing_sdk import BillingClient

# 初始化全局单例（整个应用只需要初始化一次，会自动连接 MQTT）
client = BillingClient(
    broker_host="localhost",
    broker_port=1883,
    username="your_username",
    password="your_password"
)
```

### 2. 使用装饰器

```python
from billing_sdk import track_usage, require_api_key

class YourService:
    
    @require_api_key
    @track_usage("llm", "gpt-3.5-turbo")
    async def chat_completion(self, stream, messages):
        # 你的业务逻辑
        return {"response": "Hello, world!"}
```

## 装饰器说明

### @require_api_key
- 自动从 gRPC metadata 中验证 API Key
- 支持 `api-key` 和 `apikey` 两种格式
- 验证失败会抛出异常
- 自动清理临时 API Key，防止内存泄漏

### @track_usage(module, model, usage_calculator=None, metadata_extractor=None)
- 自动上报用量到计费系统
- `module`: 模块名称 (如 "llm", "tts", "asr")
- `model`: 模型名称
- `usage_calculator`: 自定义用量计算函数 (可选，必须返回 int)
- `metadata_extractor`: 自定义元数据提取函数 (可选，必须返回 dict)

## 自定义用量计算

```python
def calculate_tokens(args, kwargs, result) -> int:
    """计算实际使用的 token 数量"""
    if hasattr(result, 'usage') and 'total_tokens' in result.usage:
        return result.usage['total_tokens']
    return len(str(result)) // 4  # 简单估算

def extract_metadata(args, kwargs, result) -> dict:
    """提取请求元数据"""
    return {
        "model_version": result.get("model", "unknown"),
        "temperature": kwargs.get("temperature", 0.7),
        "max_tokens": kwargs.get("max_tokens", 150),
    }

@track_usage("llm", "gpt-4", calculate_tokens, extract_metadata)
async def your_method(self, stream, *args, **kwargs):
    # 业务逻辑
    pass
```

## 完整示例

```python
import asyncio
from billing_sdk import BillingClient, track_usage, require_api_key

# 初始化全局单例
BillingClient(
    broker_host="localhost",
    broker_port=1883,
    username="billing_user",
    password="billing_pass"
)

class LLMService:
    
    @require_api_key
    @track_usage("llm", "gpt-3.5-turbo")
    async def chat_completion(self, stream, messages):
        # 模拟处理
        await asyncio.sleep(0.1)
        return {"content": "Hello from AI", "token_count": 100}

async def main():
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
# LLM 服务
class LLMService:
    @require_api_key
    @track_usage("llm", "gpt-4")
    async def generate_text(self, stream, prompt): pass

# TTS 服务
class TTSService:
    @require_api_key
    @track_usage("tts", "eleven-labs", lambda args, kwargs, result: len(args[1]))
    async def synthesize(self, stream, text): pass

# ASR 服务
class ASRService:
    @require_api_key
    @track_usage("asr", "whisper")
    async def transcribe(self, stream, audio): pass
```

### 错误处理

```python
class RobustService:
    @require_api_key
    @track_usage("llm", "gpt-4")
    async def safe_operation(self, stream, data):
        try:
            # 业务逻辑
            return process_data(data)
        except Exception as e:
            # 即使出错，用量也会被正确上报
            logger.error(f"处理失败: {e}")
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
│       ├── client.py            # BillingClient 和 UsageData
│       └── decorators.py        # 装饰器实现
├── tests/
│   ├── test_client.py           # 客户端测试
│   ├── test_decorators.py       # 装饰器测试
│   ├── test_integration.py      # 集成测试
│   ├── test_examples.py         # 使用示例测试
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
