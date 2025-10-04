# src/metabridge/logger.py
import logging
import sys
from functools import lru_cache
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

_console = Console(file=sys.stderr)


@lru_cache()
def get_logger(name: Optional[str] = "metabridge") -> logging.Logger:
    """
    Configura e retorna um logger com formatação rich.

    Armazena em cache a instância do logger para evitar reconfiguração.
    """
    logger = logging.getLogger(name)
    if logger.hasHandlers():
        return logger

    handler = RichHandler(
        console=_console,
        show_time=True,
        show_level=True,
        show_path=True,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=True,  # Mostra variáveis locais em tracebacks
    )

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # Previne logs duplicados em loggers pais

    return logger