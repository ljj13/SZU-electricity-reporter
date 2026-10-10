"""部署安全性与文件白名单防泄露回归测试。"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class DeploySecurityTests(unittest.TestCase):
    def test_deploy_ps1_contains_strict_whitelists(self):
        script_path = REPO_ROOT / 'deploy' / 'deploy.ps1'
        if not script_path.exists():
            self.skipTest('deploy.ps1 未安装到当前运行目录（生产单板环境跳过）')
        content = script_path.read_text(encoding='utf-8')

        # 检查白名单定义
        self.assertIn('$rootWhitelist = @(', content)
        self.assertIn('$deployWhitelist = @(', content)
        self.assertIn('$forbiddenPatterns = @(', content)

        # 检查禁止模式
        for forbidden in ('config.json*', 'config.yaml', '*.log*', '*.csv', 'last_error*', 'last_success*'):
            self.assertIn(forbidden, content)

        # 白名单定义区中绝不得包含敏感文件
        root_wl_match = re.search(r'\$rootWhitelist = @\((.*?)\)', content, re.DOTALL)
        self.assertIsNotNone(root_wl_match)
        self.assertNotIn('config.json', root_wl_match.group(1))

        deploy_wl_match = re.search(r'\$deployWhitelist = @\((.*?)\)', content, re.DOTALL)
        self.assertIsNotNone(deploy_wl_match)
        self.assertNotIn('config.yaml', deploy_wl_match.group(1))

    def test_gitignore_covers_all_credentials_and_runtime_artifacts(self):
        gitignore_path = REPO_ROOT / '.gitignore'
        if not gitignore_path.exists():
            self.skipTest('.gitignore 未安装到当前运行目录（生产单板环境跳过）')
        lines = [line.strip() for line in gitignore_path.read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')]

        required_patterns = [
            'config.json',
            'config.json.user',
            'electricity.log*',
            'electricity_history.csv',
            'last_success_date.txt',
            'last_error.txt',
            'last_error.resolved.txt',
            'deploy/config.yaml',
            'deploy/mihomo',
            '.planning/',
        ]
        for pattern in required_patterns:
            self.assertIn(pattern, lines, f"Missing {pattern} in .gitignore")

    def test_board_install_protects_config_and_handles_test_exit_code(self):
        board_script = REPO_ROOT / 'deploy' / 'board-install.sh'
        self.assertTrue(board_script.exists())
        content = board_script.read_text(encoding='utf-8')

        # 必须开启 pipefail
        self.assertIn('set -euo pipefail', content)
        # 必须包含 rollback 机制
        self.assertIn('rollback()', content)
        # 必须检查测试退出码且不得有静默吞错的管道
        self.assertIn('TEST_EXIT=$?', content)
        self.assertIn('[ $TEST_EXIT -ne 0 ]', content)
        # 绝不得直接把 unittest 结果用 pipe 传给 tail
        self.assertNotIn('unittest discover -s tests -t . 2>&1 | tail', content)


if __name__ == '__main__':
    unittest.main()
