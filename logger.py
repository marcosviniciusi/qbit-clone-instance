"""
Módulo de logging do qBittorrent Clone Tool
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '/etc/qbit-clone')

try:
    import config
except ImportError:
    print("❌ ERRO: /etc/qbit-clone/config.py não encontrado!")
    sys.exit(1)


def log(msg: str, level: int = 1):
    """Log com nível de verbosidade"""
    if config.VERBOSE >= level:
        print(msg)


def log_error(msg: str):
    """Log de erro em arquivo"""
    try:
        Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_FILE, 'a') as f:
            f.write(f"[{datetime.now()}] {msg}\n")
    except:
        pass
