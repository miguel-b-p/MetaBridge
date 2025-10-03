"""Client example consuming a MetaBridge daemon service."""
from __future__ import annotations

import metabridge as meta

import service_daemon

# Importa o serviço para garantir que ele está rodando em background.

if __name__ == "__main__":
    client = meta.connect("demo-service", argumento='Olá')
    print(client.teste())
    print(client.get("mundo!"))
    print(client.soma(10, 20))
