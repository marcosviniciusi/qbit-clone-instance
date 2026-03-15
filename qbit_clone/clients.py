"""
Módulo de conexão com instâncias qBittorrent
"""

import sys
import urllib3

try:
    from qbittorrentapi import Client
except ImportError:
    print("❌ ERRO: pip install qbittorrent-api")
    sys.exit(1)

from qbit_clone.logger import log, log_error


def build_url(host: str, port: int, use_https: bool) -> str:
    """Monta URL"""
    protocol = 'https' if use_https else 'http'
    return f"{protocol}://{host}:{port}"


def get_clients(config):
    """Conecta nas instâncias. Recebe config como parâmetro."""
    log("🔌 Conectando...", 1)

    if not config.SRC_VERIFY_SSL or not config.DST_VERIFY_SSL:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    try:
        src = Client(
            host=build_url(config.SRC_HOST, config.SRC_PORT, config.SRC_USE_HTTPS),
            username=config.SRC_USER,
            password=config.SRC_PASS,
            VERIFY_WEBUI_CERTIFICATE=config.SRC_VERIFY_SSL,
            REQUESTS_ARGS={'timeout': config.REQUEST_TIMEOUT}
        )

        dst = Client(
            host=build_url(config.DST_HOST, config.DST_PORT, config.DST_USE_HTTPS),
            username=config.DST_USER,
            password=config.DST_PASS,
            VERIFY_WEBUI_CERTIFICATE=config.DST_VERIFY_SSL,
            REQUESTS_ARGS={'timeout': config.REQUEST_TIMEOUT}
        )

        src.auth_log_in()
        dst.auth_log_in()

        log(f"✅ ORIGEM: {config.SRC_HOST}:{config.SRC_PORT} | v{src.app.version}", 1)
        log(f"✅ DESTINO: {config.DST_HOST}:{config.DST_PORT} | v{dst.app.version}", 1)

        return src, dst

    except Exception as e:
        log(f"❌ Erro de autenticação: {e}", 0)
        log_error(f"Auth error: {e}")
        sys.exit(1)
