"""
Módulo de filtros de torrents do qBittorrent Clone Tool
"""

import sys

sys.path.insert(0, '/etc/qbit-clone')

try:
    import config
except ImportError:
    print("❌ ERRO: /etc/qbit-clone/config.py não encontrado!")
    sys.exit(1)


def apply_filters(torrent) -> tuple:
    """Aplica filtros configurados"""
    if config.ONLY_SEEDING_STATE:
        if torrent.state not in config.VALID_SEEDING_STATES:
            return False, f"Estado {torrent.state} inválido"

    if config.FILTER_CATEGORIES:
        if torrent.category not in config.FILTER_CATEGORIES:
            return False, f"Categoria filtrada"

    if config.MIN_SIZE_GB:
        if torrent.size / (1024**3) < config.MIN_SIZE_GB:
            return False, "Tamanho menor que mínimo"

    if config.MIN_RATIO and torrent.ratio < config.MIN_RATIO:
        return False, "Ratio menor que mínimo"

    if config.MIN_UPLOAD_GB:
        if torrent.uploaded / (1024**3) < config.MIN_UPLOAD_GB:
            return False, "Upload menor que mínimo"

    return True, "OK"
