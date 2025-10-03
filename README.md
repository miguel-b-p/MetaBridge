# MetaBridge

**Comunicação de Alta Performance Entre Processos em Python**

O MetaBridge é uma solução elegante e eficiente para comunicação entre processos em Python. Crie "pontes" de serviço em memória que permitem que diferentes componentes da sua aplicação - rodando em processos separados - se comuniquem com velocidade excepcional através de uma API intuitiva e declarativa.

-----

## Índice

- [O que é o MetaBridge?](#o-que-é-o-metabridge)
- [Por que escolher o MetaBridge?](#por-que-escolher-o-metabridge)
- [Como funciona?](#como-funciona)
- [Instalação](#instalação)
- [Guia de Uso](#guia-de-uso)
  - [1. Definindo um Serviço](#1-definindo-um-serviço)
  - [2. Usando o Serviço (Forma Recomendada)](#2-usando-o-serviço-forma-recomendada)
  - [3. Uso Avançado: Expondo o Serviço na Rede](#3-uso-avançado-expondo-o-serviço-na-rede)
- [API Principal](#api-principal)
- [Contribuindo](#contribuindo)
- [Licença](#licença)

-----

## O que é o MetaBridge?

Imagine que você precisa executar uma tarefa computacionalmente intensiva - como processamento de dados, inferência de IA, ou operações em background - mas não quer travar sua aplicação principal. Como fazer essa comunicação de forma eficiente e transparente?

É aqui que o MetaBridge brilha. Ele permite que você defina funções e classes em um processo e as utilize de qualquer outro processo como se fossem locais, utilizando um padrão otimizado de **Chamada de Procedimento Remoto (RPC)** para comunicação local.

**Perfeito para:**

- Arquiteturas de microserviços em ambiente local
- Workers em background
- Comunicação entre interfaces gráficas e backends
- Qualquer cenário que exija comunicação inter-processos (IPC) de baixa latência

-----

## Por que escolher o MetaBridge?

| Recurso | Benefício |
| :--- | :--- |
| 🚀 **Desempenho Excepcional** | A arquitetura é focada em latência mínima e alto throughput, combinando várias otimizações:<br>  - **Sockets TCP & Pooling:** Comunicação direta via sockets TCP com um pool de conexões thread-safe para reutilização e agilidade.<br>  - **Serialização com `msgpack`:** Protocolo binário rápido e compacto, muito superior ao JSON/HTTP para IPC.<br>  - **Cache LRU O(1):** O servidor utiliza um cache LRU (Least Recently Used) de altíssima performance (`O(1)`) para instâncias de serviço, garantindo que chamadas repetidas para os mesmos objetos sejam atendidas instantaneamente, sem gargalos. |
| ✨ **API Intuitiva e Elegante** | Defina seus serviços usando classes Python e decoradores simples como `@meta.meu_endpoint`. Código limpo, organizado e fácil de manter. |
| 🏃‍♂️ **Execução em Background** | Serviços rodam como processos *daemon* independentes, liberando sua aplicação principal para outras tarefas. |
| 🌐 **Descoberta Automática** | Esqueça configurações complexas de portas e endereços. Os serviços são registrados por nome e descobertos automaticamente. |
| 🔄 **Concorrência Nativa** | O servidor gerencia múltiplas requisições simultaneamente através de um pool de threads, sem complicações adicionais. |

-----

## Como funciona?

O MetaBridge combina tecnologias Python de alto desempenho em uma arquitetura coesa:

1.  **Servidor TCP Otimizado**: Cada serviço criado com `@create(...).daemon()` opera em um processo dedicado com um servidor de socket TCP de alta eficiência.
2.  **Registro Centralizado**: Um registro compartilhado entre processos (via `multiprocessing.Manager`) mantém o mapeamento de todos os serviços ativos e suas localizações.
3.  **Cliente Inteligente**: Ao conectar com `metabridge.connect("nome-do-servico")`, o cliente consulta o registro, localiza o serviço e estabelece uma conexão TCP, criando um proxy transparente.
4.  **Comunicação Eficiente**: Chamadas de método no cliente são serializadas com **`msgpack`**, transmitidas via socket, executadas no servidor e os resultados retornam pelo mesmo canal - tudo de forma transparente.

Esta arquitetura elimina a sobrecarga de protocolos mais pesados como HTTP, proporcionando uma experiência de comunicação quase tão rápida quanto uma chamada de função local.

-----

## Instalação

```bash
git clone https://github.com/miguel-b-p/MetaBridge.git
cd MetaBridge
pip install -e .
```

-----

## Guia de Uso

Descubra como é simples integrar o MetaBridge em seus projetos com este exemplo prático.

### 1. Definindo um Serviço

Crie um arquivo para seu serviço (ex: `service_daemon.py`). Use decoradores intuitivos para definir o serviço e seus endpoints.

```python
# service_daemon.py
import asyncio
import metabridge as meta

# 1. Crie um serviço e configure para execução em background
@meta.create("demo-service").daemon()
class Service:
    """
    Nossa classe de serviço que agrupa endpoints relacionados.
    O construtor aceita argumentos fornecidos pelo cliente durante a conexão.
    """
    def __init__(self, argumento: str) -> None:
        self.argumento = argumento

    # 2. Exponha métodos com decoradores claros e objetivos
    @meta.teste  # Define um endpoint chamado 'teste'
    def home(self) -> str:
        return "Mensagem da home do serviço!"

    @meta.function  # Usa o nome da função como nome do endpoint
    def get(self, outro_argumento: str) -> str:
        return f"{self.argumento} {outro_argumento}"

    @meta.function  # Suporte completo para funções assíncronas
    async def soma(self, a: int, b: int) -> str:
        # Operações async são executadas corretamente
        await asyncio.sleep(0.01)
        return f"A soma é: {a + b}"

# 3. Inicie o serviço em background
# O serviço é automaticamente inicializado quando o módulo é importado
handle = meta.run()

# Código opcional para manter o processo principal ativo
if __name__ == "__main__":
    print(f"Serviço 'demo-service' executando em background (PID {handle.pid}). Pressione Ctrl+C para finalizar.")
    try:
        handle.join()  # Aguarda a finalização do serviço
    except KeyboardInterrupt:
        handle.stop()
        print("Serviço finalizado com sucesso.")
```

### 2. Usando o Serviço (Forma Recomendada)

Em sua aplicação principal, conecte-se ao serviço usando um bloco `with`. Isso garante que a conexão seja fechada de forma segura e automática.

```python
# client.py
import metabridge as meta

# 1. Importe o módulo do serviço para garantir sua inicialização
import service_daemon

if __name__ == "__main__":
    print("Conectando ao serviço 'demo-service'...")
    
    # 2. Use 'with' para garantir que a conexão e seus recursos sejam liberados
    with meta.connect("demo-service", argumento="Olá,") as client:
        # 3. Execute métodos remotos como se fossem locais
        print(f"Resposta do endpoint 'teste()': {client.teste()}")
        print(f"Resposta do endpoint 'get('mundo!')': {client.get('mundo!')}")
        print(f"Resposta do endpoint 'soma(10, 20)': {client.soma(10, 20)}")
    
    print("Cliente finalizado. A conexão foi fechada.")
```

**Executando a aplicação:**

```bash
python client.py
```

**Resultado esperado:**

```
Conectando ao serviço 'demo-service'...
Resposta do endpoint 'teste()': Mensagem da home do serviço!
Resposta do endpoint 'get('mundo!')': Olá, mundo!
Resposta do endpoint 'soma(10, 20)': A soma é: 30
Cliente finalizado. A conexão foi fechada.
```

### 3. Uso Avançado: Expondo o Serviço na Rede

Por padrão, os serviços são acessíveis apenas localmente (`127.0.0.1`). Para expor um serviço na sua rede local (permitindo que outras máquinas se conectem), você pode especificar o host `0.0.0.0`.

```python
# public_service.py
import metabridge as meta

# O serviço escutará em todas as interfaces de rede
@meta.create("public-service", host="0.0.0.0").daemon()
class PublicAPI:
    @meta.function
    def status(self):
        return "Serviço público está operacional!"

meta.run()
```

> **Atenção**: Expor um serviço na rede tem implicações de segurança. Certifique-se de que sua rede é confiável e que apenas clientes autorizados possam se conectar ao serviço.

-----

## API Principal

| Função / Decorador | Propósito |
| :--- | :--- |
| `metabridge.create(name, host=None)` | Cria a definição de um serviço. Opcionalmente, especifica um `host` para o servidor (padrão: '127.0.0.1'). |
| `.daemon()` | Especifica que o serviço deve ser executado como um processo daemon. |
| `metabridge.run()` | Inicia o serviço mais recentemente definido em background, retornando um `DaemonHandle` para controle. |
| `metabridge.connect(name, ...)` | Conecta a um serviço ativo, retornando um cliente proxy. Recomenda-se usar em um bloco `with`. |
| `@metabridge.endpoint(name)` | Decorador base para expor métodos de classe com nomes personalizados. |
| `@metabridge.[nome_do_endpoint]` | Atalho dinâmico para `@endpoint("nome_do_endpoint")`. Ex: `@meta.teste`. |
| `@metabridge.function` | Decorador que utiliza o nome da própria função como nome do endpoint. |

-----

## Contribuindo

Valorizamos sua contribuição! Se encontrou um bug, tem uma ideia de melhoria ou deseja adicionar funcionalidades, sinta-se à vontade para abrir uma *issue* ou enviar um *pull request*.

-----

## Licença

Este projeto está licenciado sob a **Apache License 2.0**. Consulte o arquivo [LICENSE](LICENSE) para detalhes completos.

-----