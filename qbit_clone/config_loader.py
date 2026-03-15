"""
Carregamento centralizado do config.py

Busca config.py na seguinte ordem:
1. Variável de ambiente QBIT_CLONE_CONFIG (path completo)
2. /etc/qbit-clone/config.py (padrão produção)
3. ./config.py (desenvolvimento)
"""

import sys
import importlib.util
from pathlib import Path

_config = None

CONFIG_SEARCH_PATHS = [
    '/etc/qbit-clone/config.py',
    Path(__file__).resolve().parent.parent / 'config.py',
]


def load_config():
    """Carrega config.py uma única vez e retorna o módulo"""
    global _config

    if _config is not None:
        return _config

    import os
    env_path = os.environ.get('QBIT_CLONE_CONFIG')
    if env_path:
        config_path = Path(env_path)
    else:
        config_path = None
        for candidate in CONFIG_SEARCH_PATHS:
            candidate = Path(candidate)
            if candidate.is_file():
                config_path = candidate
                break

    if config_path is None or not config_path.is_file():
        print("❌ ERRO: config.py não encontrado!")
        print("   Locais verificados:")
        if env_path:
            print(f"   - {env_path} (QBIT_CLONE_CONFIG)")
        for p in CONFIG_SEARCH_PATHS:
            print(f"   - {p}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("config", str(config_path))
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)

    _config = config
    return _config


def get_config():
    """Retorna config já carregado (load_config deve ser chamado antes)"""
    if _config is None:
        return load_config()
    return _config
