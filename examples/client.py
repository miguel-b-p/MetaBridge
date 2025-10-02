"""Client example consuming a MetaBridge daemon service."""
from __future__ import annotations


# Importa o serviço para garantir que ele está rodando em background.
import service_daemon
import metabridge as syn

if __name__ == "__main__":
    client = syn.connect("demo-service", argumento='Olá')
    print(client.teste())
    print(client.get("mundo!"))
    print(client.soma(10, 20))