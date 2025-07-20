# 测试说明

本项目包含单元测试和集成测试，使用 pytest 标记进行分类。

## 测试类型

### 单元测试 (Unit Tests)
- 标记: `@pytest.mark.unit`
- 特点: 使用 Mock 对象，不需要外部依赖
- 覆盖: 客户端功能、装饰器、基本逻辑

### 集成测试 (Integration Tests)  
- 标记: `@pytest.mark.integration`
- 特点: 测试完整的数据流和集成场景
- 部分测试需要真实的 MQTT 环境

## 运行测试

### 运行所有测试
```bash
uv run pytest tests/
```

### 运行单元测试
```bash
uv run pytest tests/ -m unit
```

### 运行集成测试
```bash
uv run pytest tests/ -m integration
```

### 运行特定测试文件
```bash
uv run pytest tests/test_client.py
uv run pytest tests/test_decorators.py  
uv run pytest tests/test_integration.py
```

## 集成测试环境配置

默认情况下，需要真实 MQTT 环境的集成测试会被跳过。要启用真实的 MQTT 测试：

### 环境变量
```bash
export SKIP_INTEGRATION=false
export MQTT_HOST=localhost        # 可选，默认 localhost
export MQTT_PORT=1883             # 可选，默认 1883  
export MQTT_USERNAME=your_user    # 可选
export MQTT_PASSWORD=your_pass    # 可选
```

### 运行真实 MQTT 测试
```bash
SKIP_INTEGRATION=false uv run pytest tests/ -m integration
```

## 覆盖率报告

测试会自动生成覆盖率报告：
- 终端显示: 运行测试时自动显示
- HTML 报告: `htmlcov/index.html`

## 测试结构

```
tests/
├── test_client.py      # BillingClient 单元测试
├── test_decorators.py  # 装饰器单元测试
├── test_integration.py # 集成测试
└── README.md          # 本文件
```

## 注意事项

1. 集成测试中的 Mock 测试仍然很有价值，它们测试完整的数据流
2. 真实 MQTT 测试需要可用的 MQTT broker
3. 某些警告信息是正常的，不影响测试结果
4. 使用 `-v` 参数可以看到详细的测试输出
