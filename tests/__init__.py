"""测试包：把运行目录重定向到临时目录，避免污染板上的生产状态与日志。"""

import os
import tempfile

os.environ.setdefault('SZU_REPORTER_DIR', tempfile.mkdtemp(prefix='szu-reporter-tests-'))
