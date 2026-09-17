import glob
import os

RAIZ = os.path.dirname(os.path.abspath(__file__))

################################################################################
# Gera um TXT com o ID da rota de maior banda disponível para cada timestamp,
#   a partir do CSV consolidado banda_rotas_h1_h6.csv (mesmo formato usado por
#   criar_arquivo_rotulos em main.py, porém buscando o máximo em vez do mínimo)
#
def criar_arquivo_rotulos_maior_banda(diretorio, nome_arquivo_entrada, nome_arquivo_saida):
    caminho_entrada = os.path.join(diretorio, nome_arquivo_entrada)
    if not os.path.exists(caminho_entrada):
        print(f"Arquivo não encontrado: {caminho_entrada}")
        return

    caminho_saida = os.path.join(diretorio, nome_arquivo_saida)

    with open(caminho_entrada, 'r') as entrada, open(caminho_saida, 'w') as saida:
        entrada.readline()  # Descarta cabeçalho

        for linha in entrada:
            linha = linha.strip()
            if not linha:
                continue

            partes = linha.split(',')
            if len(partes) < 2:
                continue

            bandas_str = partes[1:]

            # Encontra o índice da maior banda disponível
            maior_banda = float('-inf')
            id_melhor_rota = None

            for i, valor in enumerate(bandas_str):
                if valor in ('', 'None'):
                    continue
                try:
                    banda = float(valor)
                    if banda > maior_banda:
                        maior_banda = banda
                        id_melhor_rota = i + 1  # IDs começam em 1
                except ValueError:
                    continue

            # Usa rota 1 como fallback caso todas as bandas sejam inválidas
            saida.write(f"{id_melhor_rota if id_melhor_rota is not None else 1}\n")

    print(f"Arquivo de rotulos criado: {caminho_saida}")

def main():
    arquivo_banda   = "banda_rotas_h1_h6.csv"
    arquivo_rotulos = "rotulos_maior_banda.txt"

    for pasta in sorted(glob.glob(os.path.join(RAIZ, 'datasets', '*'))):
        if os.path.isdir(pasta):
            criar_arquivo_rotulos_maior_banda(pasta, arquivo_banda, arquivo_rotulos)

if __name__ == "__main__":
    main()
