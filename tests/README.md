# 计费 SDK 测试文档

这个目录包含了计费 SDK 的完整测试套件，包括单元测试、集成测试和使用示例。

## 测试覆盖的功能

### 核心功能测试 (`test_client.py`)

- **单例模式**: 确保 BillingClient 实例全局唯一
- **MQTT 连接**: TLS 连接建立、断开、重连等
- **用量上报**: `report_usage` 方法和全局 `report_usage` 函数
- **Key 状态管理**: 有效/阻止 Key 的动态更新
- **错误处理**: 连接失败、上报失败等异常情况

### 装饰器测试 (`test_decorators.py`)

- **装饰器**: `@require_api_key` 的各种场景
- **API Key 验证**: 有效性检查、格式支持、错误处理
- **辅助函数**: 掩码函数、单例获取等

## 测试运行

### 快速测试
```bash
# 运行所有测试
uv run run_tests.py

# 运行特定文件的测试
uv run pytest tests/test_client.py -v
uv run pytest tests/test_decorators.py -v
```

### 详细测试选项
```bash
# 只运行单元测试（排除集成测试）
uv run run_tests.py --unit

# 运行测试并生成覆盖率报告
uv run run_tests.py --coverage

# 查看测试详情和输出
uv run pytest -v -s

# 运行特定测试方法
uv run pytest tests/test_client.py::TestBillingClient::test_singleton_pattern -v
```

## 测试结构

### 单元测试

- ✅ BillingClient 单例模式
- ✅ MQTT 连接管理
- ✅ 用量数据结构
- ✅ Key 状态验证
- ✅ 全局 `report_usage` 函数
- ✅ `@require_api_key` 装饰器
- ✅ 错误处理和边界情况

### Mock 策略

#### MQTT 连接 Mock
```python
# Mock 自动连接，避免实际网络连接
with patch.object(BillingClient, "_auto_connect"):
    client = BillingClient("localhost", 8883)

# Mock MQTT 客户端
mock_mqtt_client = AsyncMock()
client._client = mock_mqtt_client
client._is_connected = True
```

#### gRPC Stream Mock
```python
# Mock gRPC stream 和 metadata
mock_stream = Mock()
mock_stream.metadata = [("api-key", "test-key")]
```

## 测试数据

### 测试用的 API Keys
- `"test-key"` - 基础测试用密钥
- `"valid_key"` - 有效密钥
- `"blocked_key"` - 被阻止的密钥
- `"sk-proj-1234567890abcdef"` - 长格式密钥

### 测试用的用量数据
```python
UsageData(
    api_key="test-key",
    module="llm",
    model="gpt-4",
    usage=100,
    metadata={"test": "data"}
)
```

## 常见测试场景

### 成功场景
- BillingClient 正常初始化和连接
- 用量数据成功上报
- API Key 验证通过
- Key 状态正确更新

### 错误场景
- 网络连接失败
- 无效的 API Key
- 缺失的 API Key
- MQTT 上报失败
- 单例未初始化

### 边界情况
- 空的元数据
- 极长的 API Key
- 重复初始化
- 并发访问

## 测试命名规范

测试方法命名遵循以下模式：
- `test_[功能]_[场景]`: 例如 `test_report_success`
- `test_[装饰器]_[场景]`: 例如 `test_require_api_key_success`
- `test_[异常情况]`: 例如 `test_singleton_pattern`

## 代码覆盖率目标

- **总体覆盖率**: > 90%
- **核心功能**: > 95%
- **错误处理**: > 85%

查看当前覆盖率：
```bash
uv run run_tests.py --coverage
```
