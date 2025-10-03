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