"""Local credential configuration. Never return credentials to the client."""
import os
import tempfile
import threading
from market import ROOT, DataError, load_key

LOCK = threading.Lock()


def status():
    try:
        load_key()
        configured = True
    except DataError:
        configured = False
    return {'configured': configured, 'managed': bool(os.environ.get('HITHINK_FINANCE_API_KEY', '').strip())}


def save_key(key):
    if not isinstance(key, str) or not key.strip():
        raise DataError('请输入 API Key；空白输入不会覆盖已有配置。')
    key = key.strip()
    if len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 or c in "\"'" for c in key):
        raise DataError('API Key 格式无效，请粘贴完整密钥，不要包含引号或换行。')
    if status()['managed']:
        raise DataError('当前使用启动环境提供的 Key，请先移除环境变量再通过页面配置。')
    with LOCK:
        path = ROOT / '.env.local'
        lines = path.read_text().splitlines() if path.exists() else []
        lines = [line for line in lines if not line.strip().startswith('HITHINK_FINANCE_API_KEY=')]
        lines.append('HITHINK_FINANCE_API_KEY='+key)
        fd, name = tempfile.mkstemp(prefix='.env-', dir=ROOT)
        try:
            with os.fdopen(fd, 'w') as stream:
                stream.write('\n'.join(lines)+'\n')
            os.replace(name, path)
        finally:
            if os.path.exists(name): os.unlink(name)
    return status()
