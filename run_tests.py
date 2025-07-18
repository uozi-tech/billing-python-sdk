#!/usr/bin/env python3
"""
测试运行脚本 - 提供便利的测试运行命令

使用方法:
    uv run run_tests.py              # 运行所有测试
    uv run run_tests.py --unit       # 只运行单元测试
    uv run run_tests.py --integration # 只运行集成测试
    uv run run_tests.py --coverage   # 运行测试并生成覆盖率报告
    uv run run_tests.py --fast       # 快速测试（跳过慢测试）
    uv run run_tests.py --install    # 安装依赖项
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> int:
    """运行命令并打印描述"""

    result = subprocess.run(cmd, cwd=Path(__file__).parent)

    if result.returncode == 0:
        pass
    else:
        pass

    return result.returncode


def install_dependencies() -> int:
    """安装依赖项"""

    # 安装开发和测试依赖
    return run_command(
        ["uv", "sync", "--extra", "dev", "--extra", "test"], "安装开发和测试依赖"
    )


def main():
    parser = argparse.ArgumentParser(description="运行测试")
    parser.add_argument("--unit", action="store_true", help="只运行单元测试")
    parser.add_argument("--integration", action="store_true", help="只运行集成测试")
    parser.add_argument("--coverage", action="store_true", help="生成覆盖率报告")
    parser.add_argument("--fast", action="store_true", help="快速测试模式")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--file", "-f", help="运行特定的测试文件")
    parser.add_argument("--test", "-t", help="运行特定的测试函数")
    parser.add_argument("--install", action="store_true", help="安装依赖项")

    args = parser.parse_args()

    # 如果请求安装依赖
    if args.install:
        exit_code = install_dependencies()
        if exit_code == 0:
            pass
        sys.exit(exit_code)

    # 基础 pytest 命令，使用 uv run
    cmd = ["uv", "run", "pytest"]

    # 添加详细输出
    if args.verbose:
        cmd.append("-vv")

    # 选择测试类型
    if args.unit:
        cmd.extend(["-m", "unit"])
        description = "运行单元测试"
    elif args.integration:
        cmd.extend(["-m", "integration"])
        description = "运行集成测试"
    elif args.file:
        cmd.append(f"tests/{args.file}")
        description = f"运行测试文件: {args.file}"
    elif args.test:
        cmd.extend(["-k", args.test])
        description = f"运行特定测试: {args.test}"
    else:
        description = "运行所有测试"

    # 快速模式
    if args.fast:
        cmd.extend(["--durations=10", "-x"])  # 显示最慢的10个测试，第一个失败就停止
        description += " (快速模式)"

    # 覆盖率报告
    if args.coverage:
        cmd.extend(["--cov=billing_sdk", "--cov-report=html", "--cov-report=term"])
        description += " + 覆盖率报告"

    # 运行测试
    exit_code = run_command(cmd, description)

    # 如果生成了覆盖率报告，提示查看
    if args.coverage and exit_code == 0:
        pass

    # 运行其他有用的检查
    if not args.unit and not args.integration and not args.file and not args.test:

        # 检查代码格式
        ruff_code = run_command(
            ["uv", "run", "ruff", "check", "src/", "tests/"], "检查代码格式 (ruff)"
        )

        # 运行类型检查
        mypy_code = run_command(["uv", "run", "mypy", "src/"], "类型检查 (mypy)")

        # 综合退出码
        if any([exit_code, ruff_code, mypy_code]):
            sys.exit(1)
        else:
            pass

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
