"""Example showing how to run a MetaBridge service in daemon mode."""
from __future__ import annotations


import asyncio
import metabridge as syn

@syn.create("demo-service").daemon()
class Service:
    """Namespace grouping the service endpoints."""

    def __init__(self, argumento: str) -> None:
        self.argumento = argumento

    @syn.teste
    def home(self) -> str:
        return "Mensagem da home"

    @syn.get
    def get(self, outro_argumento: str) -> str:
        return self.argumento + " " + outro_argumento

    @syn.function
    async def soma(self, a: int, b: int) -> str:
        await asyncio.sleep(0.01)
        return "A soma é: " + str(a + b)

# Ao importar este módulo o serviço já é iniciado em background.
handle = syn.run()

if __name__ == "__main__":
    print(f"Serviço 'demo-service' rodando em background (PID {handle.pid}). Pressione Ctrl+C para encerrar.")
    try:
        handle.join()
    except KeyboardInterrupt:
        handle.stop()
        print("Serviço encerrado.")