# MetaBridge

**Comunicação de Alta Performance Entre Processos em Python**

MetaBridge é uma biblioteca leve e poderosa para criar "pipes" de serviço em memória, permitindo que diferentes partes de uma aplicação Python (rodando em processos separados) se comuniquem de forma extremamente rápida e com uma API elegante e declarativa.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

---

## Tabela de Conteúdos
- [O que é o MetaBridge?](#o-que-é-o-metabridge)
- [Por que usar o MetaBridge?](#por-que-usar-o-metabridge)
- [Como funciona?](#como-funciona)
- [Instalação](#instalação)
- [Como Usar](#como-usar)
  - [1. Definindo um Serviço](#1-definindo-um-serviço)
  - [2. Consumindo o Serviço](#2-consumindo-o-serviço)
- [API Principal](#api-principal)
- [Contribuição](#contribuição)
- [Licença](#licença)

---

## O que é o MetaBridge?

Imagine que você tem uma tarefa pesada (como processamento de dados, IA, ou um worker) que precisa rodar em um processo separado para não travar sua aplicação principal. Como a sua aplicação principal conversa com esse worker de forma eficiente?

É aí que o MetaBridge entra. Ele permite que você defina funções e classes em um processo e as chame de qualquer outro processo como se fossem locais, usando um padrão de **Chamada de Procedimento Remoto (RPC)** otimizado para comunicação local.

Ele é ideal para:
- Arquiteturas de microserviços locais.
- Workers em background.
- Comunicação entre uma GUI e seu backend.
- Qualquer cenário que exija comunicação inter-processos (IPC) de baixa latência em uma única máquina.

---

## Por que usar o MetaBridge?

| Recurso | Descrição |
| :--- | :--- |
| 🚀 **Desempenho Extremo** | Utiliza sockets TCP de baixo nível e serialização binária com `pickle` (muito mais rápido que JSON/HTTP para IPC), além de pooling de conexões para latência mínima. |
| ✨ **API Simples e Elegante** | Defina seus serviços usando classes e decoradores Python intuitivos como `@syn.meu_endpoint`. A lógica fica limpa, organizada e fácil de entender. |
| 🏃‍♂️ **Execução em Background** | Os serviços rodam como processos *daemon* independentes, não bloqueando sua aplicação principal. |
| 🌐 **Descoberta Automática** | Não se preocupe com portas ou endereços IP. Os serviços são registrados por nome e podem ser encontrados de qualquer lugar do seu projeto. |
| 🔄 **Concorrência Integrada** | O servidor utiliza um pool de threads para lidar com múltiplas requisições de clientes simultaneamente, sem esforço extra. |

---

## Como funciona?

O MetaBridge combina algumas tecnologias eficientes do Python para alcançar seu objetivo:

1.  **Servidor TCP**: Cada serviço criado com `@create(...).daemon()` roda em um processo separado com um servidor de soquete TCP de alta performance.
2.  **Registro de Serviços**: Um registro central, compartilhado entre processos (usando `multiprocessing.Manager`), armazena a localização (host e porta) de cada serviço ativo.
3.  **Cliente Inteligente**: Ao usar `metabridge.connect("nome-do-servico")`, o cliente consulta o registro para encontrar o serviço, estabelece uma conexão TCP e cria um objeto proxy.
4.  **Comunicação Otimizada**: As chamadas de método no objeto do cliente são serializadas com `pickle`, enviadas pelo socket, executadas no servidor e o resultado retorna pelo mesmo caminho. Tudo de forma transparente para o desenvolvedor.

Essa arquitetura evita a sobrecarga de protocolos mais pesados como HTTP, tornando a comunicação quase tão rápida quanto uma chamada de função local.

---

## Instalação

```bash
git clone https://github.com/miguel-b-p/MetaBridge.git
cd MetaBridge
pip install -e .
```

---

## Como Usar

Usar o MetaBridge é incrivelmente simples. Veja um exemplo completo.

### 1. Definindo um Serviço

Crie um arquivo para o seu serviço (ex: `service_daemon.py`). Use decoradores para definir o nome do serviço e quais métodos serão expostos.

```python
# service_daemon.py
import asyncio
import metabridge as syn

# 1. Crie um serviço e marque-o para rodar como daemon
@syn.create("demo-service").daemon()
class Service:
    """
    Uma classe que agrupa os endpoints do nosso serviço.
    O construtor pode receber argumentos passados pelo cliente.
    """
    def __init__(self, argumento: str) -> None:
        self.argumento = argumento

    # 2. Exponha métodos com decoradores simples e diretos
    @syn.teste  # Cria um endpoint chamado 'teste'
    def home(self) -> str:
        return "Mensagem da home do serviço!"

    @syn.function  # Usa o nome da própria função ('get') como nome do endpoint
    def get(self, outro_argumento: str) -> str:
        return f"{self.argumento} {outro_argumento}"

    @syn.function # Usa o nome da própria função ('soma') como nome do endpoint
    async def soma(self, a: int, b: int) -> str:
        # Funções async são suportadas e executadas de forma síncrona
        await asyncio.sleep(0.01)
        return f"A soma é: {a + b}"

# 3. Inicie o serviço em background.
# O serviço começará a rodar assim que este módulo for importado.
handle = syn.run()

# O código abaixo é opcional, apenas para manter o processo principal vivo
if __name__ == "__main__":
    print(f"Serviço 'demo-service' rodando em background (PID {handle.pid}). Pressione Ctrl+C para encerrar.")
    try:
        handle.join()  # Espera o processo do serviço terminar
    except KeyboardInterrupt:
        handle.stop()
        print("Serviço encerrado.")
```

### 2. Consumindo o Serviço

Agora, em outro arquivo (sua aplicação principal, por exemplo), conecte-se e use o serviço.

```python
# client.py

# 1. Importe o módulo do serviço para garantir que ele seja iniciado
import service_daemon
import metabridge as syn

if __name__ == "__main__":
    # 2. Conecte-se ao serviço pelo nome, passando argumentos para o __init__ da classe
    print("Conectando ao 'demo-service'...")
    client = syn.connect("demo-service", argumento="Olá,")

    # 3. Chame os métodos remotos como se fossem locais
    print(f"Resposta de 'teste()': {client.teste()}")
    print(f"Resposta de 'get('mundo!')': {client.get('mundo!')}")
    print(f"Resposta de 'soma(10, 20)': {client.soma(10, 20)}")
```

**Para rodar:**

Abra um terminal e execute o cliente. Como ele importa o `service_daemon`, o serviço iniciará automaticamente em background antes que o cliente tente se conectar.

```bash
python client.py
```

**Saída esperada:**

```
Conectando ao 'demo-service'...
Resposta de 'teste()': Mensagem da home do serviço!
Resposta de 'get('mundo!')': Olá, mundo!
Resposta de 'soma(10, 20)': A soma é: 30
```

---

## API Principal

| Função / Decorador | Descrição |
| :--- | :--- |
| `metabridge.create(name)` | Cria ou obtém a definição de um serviço com o `name` especificado. |
| `.daemon()` | Encadeado após `create()`, especifica que o serviço deve ser preparado para rodar em um processo daemon. |
| `metabridge.run()` | Inicia o serviço definido mais recentemente em um processo daemon e retorna um `DaemonHandle` para controlá-lo. |
| `metabridge.connect(name, ...)` | Conecta-se a um serviço em execução pelo `name` e retorna um cliente proxy. Argumentos adicionais são passados para o `__init__` da classe do serviço. |
| `@metabridge.endpoint(name)` | O decorador base para expor um método de classe com um nome customizado. |
| `@syn.[nome_do_endpoint]` | Atalho dinâmico para `@endpoint("nome_do_endpoint")`. Por exemplo, `@syn.teste` é o mesmo que `@endpoint("teste")`. |
| `@metabridge.function` | Um decorador especial que usa o nome da própria função como o nome do endpoint. É o mesmo que usar `@endpoint()` sem argumentos. |

---

## Contribuição

Contribuições são bem-vindas! Se você encontrar um bug ou tiver uma sugestão de melhoria, sinta-se à vontade para abrir uma *issue* ou um *pull request*.

---

## Licença

Este projeto está licenciado sob a Licença **Apache License, Version 2.0** Veja o arquivo [LICENSE](LICENSE) para mais detalhes.