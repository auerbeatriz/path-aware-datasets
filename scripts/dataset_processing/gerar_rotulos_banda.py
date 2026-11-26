import argparse
import glob
import os

from scripts.dataset_processing.desempate_rotulos import (
    escolher_rota,
    ler_csv_consolidado_para_rotulo,
    medias_janela_passado,
    novas_estatisticas,
    novo_gerador_aleatorio,
    resumo_estatisticas,
)

# Repository root (this file lives in scripts/dataset_processing/)
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

################################################################################
# Gera um TXT com o ID da rota de maior banda disponível para cada timestamp,
#   a partir do CSV consolidado bandwidth_in_routes_pair-h1-h6.csv (mesmo formato usado por
#   criar_arquivo_rotulos em gerar_relatorio_latencia.py, porém buscando o máximo em vez do mínimo)
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

################################################################################
# Tie-break variant, kept for future use (NOT the current default: every
#   labels_highest_bandwidth*.txt is the plain argmax above, where a tie goes to
#   the lowest pathId). Routes with exactly the same available bandwidth go
#   through the shared rule of desempate_rotulos.py: best mean over the past
#   'janela_segundos' (current instant excluded), then a seeded random choice.
#   Enabled with `--desempate`.
#
def criar_arquivo_rotulos_maior_banda_desempate(diretorio, nome_arquivo_entrada, nome_arquivo_saida,
                                                janela_segundos=10, semente=42):
    caminho_entrada = os.path.join(diretorio, nome_arquivo_entrada)
    if not os.path.exists(caminho_entrada):
        print(f"Arquivo não encontrado: {caminho_entrada}")
        return

    timestamps, linhas_valores = ler_csv_consolidado_para_rotulo(caminho_entrada)
    medias = medias_janela_passado(timestamps, linhas_valores, janela_segundos)
    rng = novo_gerador_aleatorio(semente)
    estatisticas = novas_estatisticas()

    caminho_saida = os.path.join(diretorio, nome_arquivo_saida)
    with open(caminho_saida, 'w') as saida:
        for valores, medias_linha in zip(linhas_valores, medias):
            saida.write(f"{escolher_rota(valores, False, medias_linha, rng, estatisticas)}\n")

    print(f"Arquivo de rotulos criado: {caminho_saida} [{resumo_estatisticas(estatisticas)}]")

def main(desempate=False):
    gerar = criar_arquivo_rotulos_maior_banda_desempate if desempate else criar_arquivo_rotulos_maior_banda

    for pasta in sorted(glob.glob(os.path.join(RAIZ, 'datasets', '*'))):
        if not os.path.isdir(pasta):
            continue
        if os.path.exists(os.path.join(pasta, 'bandwidth_in_routes_pair-h1-h6.csv')):
            gerar(pasta, 'bandwidth_in_routes_pair-h1-h6.csv', 'labels_highest_bandwidth.txt')
        # D3a and D4a: two routes, '_12' suffix
        if os.path.exists(os.path.join(pasta, 'bandwidth_in_routes_pair-h1-h6_12.csv')):
            gerar(pasta, 'bandwidth_in_routes_pair-h1-h6_12.csv', 'labels_highest_bandwidth_12.txt')

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate labels_highest_bandwidth*.txt for every dataset.')
    parser.add_argument('--desempate', action='store_true',
                        help='break exact ties by past-window mean + seeded draw (default: lowest pathId)')
    main(parser.parse_args().desempate)
