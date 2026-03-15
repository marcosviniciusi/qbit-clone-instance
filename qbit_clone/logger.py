"""
Logger com buffer para qBittorrent Clone Tool

Acumula todos os logs em memória durante a execução.
Ao final, faz flush para:
- Console (print)
- Arquivo de log (erros)
- OpenTelemetry (OTLP) se configurado
"""

import os
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import IntEnum


class LogLevel(IntEnum):
    ERROR = 0
    INFO = 1
    DEBUG = 2


@dataclass
class LogEntry:
    timestamp: datetime
    message: str
    level: LogLevel
    attributes: dict = field(default_factory=dict)


class BufferedLogger:
    """Logger que acumula entries e exporta ao final"""

    def __init__(self, verbose: int = 1, log_file: str = None):
        self.verbose = verbose
        self.log_file = log_file
        self._buffer: list[LogEntry] = []
        self._otel_endpoint = os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')
        self._otel_service = os.environ.get('OTEL_SERVICE_NAME', 'qbit-clone')

    def log(self, msg: str, level: int = 1, **attributes):
        """Adiciona log ao buffer e imprime se verbose permite"""
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            message=msg,
            level=LogLevel(min(level, LogLevel.DEBUG)),
            attributes=attributes,
        )
        self._buffer.append(entry)

        if self.verbose >= level:
            print(msg)

    def error(self, msg: str, **attributes):
        """Log de erro (sempre visível + vai pro arquivo)"""
        self.log(msg, level=LogLevel.ERROR, **attributes)

    def info(self, msg: str, **attributes):
        """Log informativo"""
        self.log(msg, level=LogLevel.INFO, **attributes)

    def debug(self, msg: str, **attributes):
        """Log de debug"""
        self.log(msg, level=LogLevel.DEBUG, **attributes)

    def flush(self):
        """
        Exporta todo o buffer acumulado:
        1. Erros → arquivo de log
        2. Tudo → OTel (se configurado)
        """
        self._flush_error_file()

        if self._otel_endpoint:
            self._flush_otel()

        self._buffer.clear()

    def _flush_error_file(self):
        """Escreve erros no arquivo de log"""
        if not self.log_file:
            return

        errors = [e for e in self._buffer if e.level == LogLevel.ERROR]
        if not errors:
            return

        try:
            Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, 'a') as f:
                for entry in errors:
                    f.write(f"[{entry.timestamp.isoformat()}] {entry.message}\n")
        except Exception:
            pass

    def _flush_otel(self):
        """Envia logs para OpenTelemetry via OTLP/HTTP"""
        try:
            import json
            import urllib.request

            resource_attrs = [
                {"key": "service.name", "value": {"stringValue": self._otel_service}},
            ]

            log_records = []
            for entry in self._buffer:
                record = {
                    "timeUnixNano": str(int(entry.timestamp.timestamp() * 1e9)),
                    "severityNumber": self._otel_severity(entry.level),
                    "severityText": entry.level.name,
                    "body": {"stringValue": entry.message},
                    "attributes": [
                        {"key": k, "value": {"stringValue": str(v)}}
                        for k, v in entry.attributes.items()
                    ],
                }
                log_records.append(record)

            payload = {
                "resourceLogs": [{
                    "resource": {"attributes": resource_attrs},
                    "scopeLogs": [{
                        "scope": {"name": "qbit-clone", "version": "5.1.0"},
                        "logRecords": log_records,
                    }],
                }],
            }

            url = f"{self._otel_endpoint.rstrip('/')}/v1/logs"
            data = json.dumps(payload).encode('utf-8')

            headers_env = os.environ.get('OTEL_EXPORTER_OTLP_HEADERS', '')
            headers = {"Content-Type": "application/json"}
            if headers_env:
                for pair in headers_env.split(','):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        headers[k.strip()] = v.strip()

            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            urllib.request.urlopen(req, timeout=10)

        except Exception as e:
            # Falha silenciosa — não interrompe a ferramenta
            try:
                if self.log_file:
                    with open(self.log_file, 'a') as f:
                        f.write(f"[{datetime.now(timezone.utc).isoformat()}] OTel export failed: {e}\n")
            except Exception:
                pass

    @staticmethod
    def _otel_severity(level: LogLevel) -> int:
        """Mapeia LogLevel para OTel SeverityNumber"""
        return {
            LogLevel.ERROR: 17,  # SEVERITY_NUMBER_ERROR
            LogLevel.INFO: 9,    # SEVERITY_NUMBER_INFO
            LogLevel.DEBUG: 5,   # SEVERITY_NUMBER_DEBUG
        }.get(level, 9)


# Instância global — inicializada no entry point
_logger: BufferedLogger | None = None


def init_logger(verbose: int = 1, log_file: str = None) -> BufferedLogger:
    """Inicializa o logger global"""
    global _logger
    _logger = BufferedLogger(verbose=verbose, log_file=log_file)
    return _logger


def get_logger() -> BufferedLogger:
    """Retorna logger global"""
    if _logger is None:
        return init_logger()
    return _logger


def log(msg: str, level: int = 1, **attributes):
    """Atalho para get_logger().log()"""
    get_logger().log(msg, level, **attributes)


def log_error(msg: str, **attributes):
    """Atalho para get_logger().error()"""
    get_logger().error(msg, **attributes)
