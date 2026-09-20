import glob
import json
import os
import sys

import pandas as pd

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(RAIZ, 'prototipo'))

from helpers.parser_banda import (
    PADRAO_ARQUIVO_BANDA,
    capacidadeInterfaces,
    interfacesDoCaminho,
    carregarBandaConsolidada,
    idRotaDoNome,
    lerArquivoBanda,
    parseBandaCaminho,
)

ARQUIVO_BANDA_CONSOLIDADA = 'banda_rotas_h1_h6.csv'

################################################################################
# Lê o arquivo rotas.txt de um cenário e retorna a lista de rotas
#   Formato de cada linha: 'nome: h11-s1-s2-s3-s6-h61'
#
def parseRotas(arquivo):
    rotas = []
    with open(arquivo) as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            nome, caminho_str = linha.split(':', 1)
            caminho = caminho_str.strip().split('-')
            rotas.append({'nome': nome.strip(), 'caminho': caminho})
    return rotas

################################################################################
# Consolida os arquivos de banda por caminho (banda_rota_h1<r>_h6<r>.txt) em
#   um único CSV, no mesmo formato de 'latencia_rotas_h1_h6.csv' (ver
#   consolidar_latencias em main.py), mas garantindo uma leitura por segundo.
#
#   A coleta do bwm-ng ocasionalmente perde um ciclo de amostragem, o que deixa
#   segundos sem leitura em alguma rota (célula vazia) ou em todas as rotas
#   (linha ausente). Aqui a série de cada rota é reindexada para a grade
#   completa de 1 s entre a primeira e a última leitura e os valores ausentes
#   são interpolados linearmente no tempo (mesma estratégia usada no notebook
#   para alinhar banda e latência). Extremidades sem vizinho de um dos lados
#   recebem o valor mais próximo (limit_direction='both').
#
# Parâmetros:
#   diretorio - pasta do cenário, contendo os arquivos banda_rota_*.txt
#   nome_arquivo_saida - nome do CSV de saída
#   rotas - lista com os IDs das rotas a consolidar
# Retorno:
#   Tupla (caminho_arquivo_saida, rotas_encontradas, n_interpolados) ou None
#   se nenhum arquivo for encontrado
#
def consolidarBandaInterpolada(diretorio, nome_arquivo_saida, rotas):
    dados_rotas = {}

    for nome_arquivo in os.listdir(diretorio):
        correspondencia = PADRAO_ARQUIVO_BANDA.match(nome_arquivo)
        if not correspondencia:
            continue

        pathId = int(correspondencia.group(1))
        if pathId not in rotas:
            continue

        bandas = lerArquivoBanda(os.path.join(diretorio, nome_arquivo))
        serie = pd.Series(bandas, dtype=float)
        serie.index = pd.to_datetime(serie.index)
        dados_rotas[pathId] = serie.sort_index()

    if not dados_rotas:
        return None

    rotas_ordenadas = sorted(dados_rotas.keys())

    # Uma coluna por rota, alinhadas pela união dos timestamps observados
    banda = pd.concat(
        {f'h1{r}_h6{r}': dados_rotas[r] for r in rotas_ordenadas}, axis=1, sort=True
    ).sort_index()

    # Grade completa de 1 s entre a primeira e a última leitura
    grade = pd.date_range(banda.index.min(), banda.index.max(), freq='1s')
    banda = banda.reindex(banda.index.union(grade))

    n_interpolados = int(banda.isna().sum().sum())

    banda = (
        banda
        .interpolate(method='time', limit_direction='both')
        .reindex(grade)
    )
    banda.index.name = 'timestamp'

    caminho_saida = os.path.join(diretorio, nome_arquivo_saida)
    banda.to_csv(caminho_saida, date_format='%Y-%m-%d %H:%M:%S')

    return caminho_saida, rotas_ordenadas, n_interpolados

################################################################################
# Gera os relatórios de banda por caminho (banda_<rota>.txt) de um cenário,
#   extraindo os dados do arquivo consolidado banda.bwm, e em seguida o CSV
#   consolidado de todas as rotas (banda_rotas_h1_h6.csv)
#
def gerarRelatoriosBanda(pasta):
    arquivo_bwm = os.path.join(pasta, 'banda.bwm')
    arquivo_config = os.path.join(pasta, 'config.json')
    arquivo_rotas = os.path.join(pasta, 'rotas.txt')

    if not (os.path.isfile(arquivo_bwm) and os.path.isfile(arquivo_config) and os.path.isfile(arquivo_rotas)):
        return

    with open(arquivo_config) as f:
        config = json.load(f)
    links = config['topologia']['links']
    capacidade_por_interface, interface_no_link = capacidadeInterfaces(links)

    rotas = parseRotas(arquivo_rotas)
    data = carregarBandaConsolidada(arquivo_bwm)

    for rota in rotas:
        interfaces = interfacesDoCaminho(rota['caminho'], interface_no_link)
        parseBandaCaminho(rota['nome'], interfaces, data, capacidade_por_interface, pasta_saida=pasta)
        print(f"[{os.path.basename(pasta)}] banda_{rota['nome']}.txt gerado ({len(interfaces)} interfaces)")

    ids_rotas = [idRotaDoNome(rota['nome']) for rota in rotas]
    ids_rotas = [pathId for pathId in ids_rotas if pathId is not None]
    resultado = consolidarBandaInterpolada(pasta, ARQUIVO_BANDA_CONSOLIDADA, ids_rotas)
    if resultado is not None:
        _, rotas_encontradas, n_interpolados = resultado
        print(f"[{os.path.basename(pasta)}] {ARQUIVO_BANDA_CONSOLIDADA} gerado ({len(rotas_encontradas)} rotas, {n_interpolados} valores interpolados)")

def main():
    for pasta in sorted(glob.glob(os.path.join(RAIZ, 'datasets', '*'))):
        if os.path.isdir(pasta):
            gerarRelatoriosBanda(pasta)

if __name__ == '__main__':
    main()
