# 计费 SDK 测试文档

这个目录包含了计费 SDK 的完整测试套件，包括单元测试、集成测试和使用示例。

## 测试结构

```
tests/
├── __init__.py              # 测试包初始化
├── test_client.py           # BillingClient 单元测试
├── test_decorators.py       # 装饰器功能测试
├── test_integration.py      # 集成测试
├── test_examples.py         # 使用示例测试
└── README.md               # 本文档
```

## 快速开始

### 安装测试依赖

```bash
# 安装测试依赖（推荐方式）
uv sync --extra test

# 安装开发和测试依赖
uv sync --extra dev --extra test

# 使用便利脚本一键安装
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

# 快速测试（第一个失败就停止）
uv run run_tests.py --fast

# 运行特定测试文件
uv run run_tests.py --file test_client.py

# 运行特定测试函数
uv run run_tests.py --test test_singleton_pattern
```

### 直接使用 pytest

```bash
# 运行所有测试
uv run pytest

# 运行特定文件
uv run pytest tests/test_client.py

# 运行特定测试
uv run pytest tests/test_client.py::TestBillingClient::test_singleton_pattern

# 生成覆盖率报告
uv run pytest --cov=billing_sdk --cov-report=html

# 运行集成测试
uv run pytest -m integration

# 详细输出
uv run pytest -v

# 并行运行测试（需要 pytest-xdist）
uv add --dev pytest-xdist
uv run pytest -n auto
```

## 测试类型说明

### 1. 单元测试 (`test_client.py`, `test_decorators.py`)

测试单个组件的功能：
- **BillingClient**: 单例模式、连接管理、用量上报、API Key 验证
- **装饰器**: `@track_usage`、`@require_api_key` 的各种场景
- **工具函数**: API Key 掩码、类型检查等

```bash
# 只运行单元测试
uv run pytest -m "not integration"
```

### 2. 集成测试 (`test_integration.py`)

测试组件间的交互：
- **完整 LLM 服务流程**: API Key 验证 + 用量追踪
- **多服务场景**: LLM、TTS、ASR 服务并行
- **错误处理**: 连接失败、上报失败等
- **并发处理**: 多个请求同时处理
- **API Key 生命周期**: 状态更新、阻止/恢复

```bash
# 只运行集成测试
uv run pytest -m integration
```

### 3. 使用示例 (`test_examples.py`)

展示真实使用场景：
- **基础用法**: 简单的 API 包装
- **自定义计算器**: OpenAI token 计算
- **多服务集成**: 不同 API Key 的服务
- **错误处理**: 健壮的服务设计
- **批处理**: 批量操作的用量计算
- **流式处理**: 流式 API 的处理

## 测试覆盖范围

### BillingClient 测试覆盖

- ✅ 单例模式实现
- ✅ 自动连接机制
- ✅ MQTT 连接/断开
- ✅ 用量数据上报
- ✅ API Key 状态管理
- ✅ 错误处理和恢复
- ✅ 并发安全性

### 装饰器测试覆盖

- ✅ `@track_usage` 异步/同步函数
- ✅ 自定义用量计算器
- ✅ 元数据提取
- ✅ 错误处理和降级
- ✅ `@require_api_key` 验证逻辑
- ✅ API Key 清理机制
- ✅ 装饰器组合使用

### 边界条件测试

- ✅ 未初始化状态
- ✅ 网络连接失败
- ✅ 无效的用量计算器
- ✅ 缺失/无效 API Key
- ✅ MQTT 发布失败
- ✅ 异常时的资源清理

## Mock 策略

测试中使用了全面的 Mock 策略以确保：

1. **MQTT 连接隔离**: 使用 `AsyncMock` 模拟 MQTT 客户端
2. **单例状态重置**: 每个测试前重置 `BillingClient` 单例
3. **时间控制**: Mock `time.time()` 确保时间戳可预测
4. **异步任务**: Mock `asyncio.create_task` 避免实际后台任务

## 性能考虑

- **并发测试**: 验证多个请求同时处理的正确性
- **内存泄漏**: 确保 API Key 和临时数据被正确清理
- **连接复用**: 验证单例模式避免重复连接

## 调试技巧

### 运行单个测试并输出详细信息

```bash
uv run pytest tests/test_client.py::TestBillingClient::test_singleton_pattern -v -s
```

### 在测试失败时进入调试器

```bash
uv run pytest --pdb tests/test_client.py
```

### 查看覆盖率详情

```bash
uv run pytest --cov=billing_sdk --cov-report=html
open htmlcov/index.html
```

### 分析测试性能

```bash
uv run pytest --durations=10
```

### 使用 UV 的调试功能

```bash
# 详细输出 uv 操作
uv run --verbose pytest

# 查看项目依赖树
uv tree

# 检查依赖冲突
uv sync --resolution=highest
```

## 贡献指南

### 添加新测试

1. **单元测试**: 在相应的 `test_*.py` 文件中添加
2. **集成测试**: 在 `test_integration.py` 中添加，并标记 `@pytest.mark.integration`
3. **示例测试**: 在 `test_examples.py` 中添加真实使用场景

### 测试命名规范

- `test_[功能]_[场景]`: 例如 `test_track_usage_async_success`
- 使用描述性的测试名称
- 包含详细的文档字符串

### Mock 最佳实践

1. 在 `setup_method` 中重置单例状态
2. 使用 `patch` 上下文管理器隔离外部依赖
3. 验证 Mock 调用的参数和次数
4. 测试 Mock 失败的场景

## 持续集成

### GitHub Actions 配置示例

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
    
    steps:
    - uses: actions/checkout@v4
    - name: Install uv
      uses: astral-sh/setup-uv@v2
    - name: Set up Python ${{ matrix.python-version }}
      run: uv python install ${{ matrix.python-version }}
    - name: Install dependencies
      run: uv sync --extra dev --extra test
    - name: Run tests
      run: uv run run_tests.py --coverage
```

### 本地 pre-commit 钩子

```bash
# 安装 pre-commit
uv add --dev pre-commit

# 安装 git hooks
uv run pre-commit install

# 手动运行检查
uv run pre-commit run --all-files
```

## 常见问题

### Q: 测试运行很慢

A: 使用快速模式：`uv run run_tests.py --fast`

### Q: 单例状态影响测试

A: 确保在 `setup_method` 中重置：
```python
def setup_method(self):
    BillingClient._instance = None
    BillingClient._initialized = False
```

### Q: 异步测试失败

A: 确保使用 `@pytest.mark.asyncio` 装饰器并安装 `pytest-asyncio`

### Q: 覆盖率不完整

A: 检查是否有未测试的分支条件，使用 `--cov-report=html` 查看详细报告

### Q: UV 相关问题

A: 
- 检查 `uv.lock` 是否最新：`uv sync`
- 清理缓存：`uv clean`
- 查看详细错误：`uv run --verbose pytest`
