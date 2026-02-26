#!/usr/bin/env python
# encoding: utf-8
"""
运行所有测试的入口脚本
"""
import sys
import os
import subprocess
import argparse

# 添加项目根目录到路径
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)


def check_server():
    """检查服务器是否运行"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', 8000))
    sock.close()
    return result == 0


def run_tests(test_type='all', verbose=True):
    """运行测试"""
    test_dir = os.path.dirname(os.path.abspath(__file__))

    # 测试文件映射
    test_files = {
        'device': 'test_device_detector.py',
        'api': 'test_api_endpoints.py',
        'screenshot': 'test_screenshot.py',
        'touch': 'test_touch_commands.py',
        'performance': 'test_performance.py',
        'integration': 'test_integration.py',
    }

    # 构建 pytest 参数
    pytest_args = ['-v'] if verbose else []
    pytest_args.extend(['-s'])  # 显示 print 输出

    if test_type == 'all':
        # 运行所有测试
        pytest_args.append(test_dir)
    elif test_type in test_files:
        # 运行特定测试
        pytest_args.append(os.path.join(test_dir, test_files[test_type]))
    else:
        print(f"Unknown test type: {test_type}")
        print(f"Available: {', '.join(['all'] + list(test_files.keys()))}")
        return 1

    # 运行 pytest
    import pytest
    return pytest.main(pytest_args)


def main():
    parser = argparse.ArgumentParser(description='CloudControl Test Runner')
    parser.add_argument(
        'type',
        nargs='?',
        default='all',
        help='Test type: all, device, api, screenshot, touch, performance, integration'
    )
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='Quiet mode'
    )
    parser.add_argument(
        '--no-server-check',
        action='store_true',
        help='Skip server check'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("CloudControl Test Suite")
    print("=" * 60)

    # 检查服务器
    if not args.no_server_check:
        if not check_server():
            print("\n警告: 服务器未运行在 localhost:8000")
            print("请先启动服务器: python main.py")
            print("\n继续运行可能导致部分测试跳过...")
            response = input("是否继续? (y/N): ")
            if response.lower() != 'y':
                return 1

    print(f"\n运行测试: {args.type}")
    print("-" * 60)

    return run_tests(args.type, not args.quiet)


if __name__ == '__main__':
    sys.exit(main())
