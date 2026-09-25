"""Gera os datasets consolidados de latência e de banda de cada cenário.

Este script é o ponto de entrada único para produzir os CSVs consolidados a
partir dos relatórios por rota já existentes em cada pasta de cenário
(`latencia_rota_h1<r>_h6<r>.txt` e `banda_rota_h1<r>_h6<r>.txt`). A leitura
desses arquivos e a geração dos rótulos reaproveitam as funções de
`gerar_relatorio_latencia.py` e `gerar_relatorio_banda_rotas.py`; aqui é
adicionada apenas a parte que não existe nesses scripts: colocar as duas
métricas na mesma grade de 1 s e juntá-las em formato largo.

Saídas disponíveis (argumento posicional, uma ou mais):

    latencia  Apenas o dataset de latência (`latencia_rotas_h1_h6.csv`).
    banda     Apenas o dataset de banda (`banda_rotas_h1_h6.csv`).
    ambas     As duas métricas em arquivos separados, interpoladas na mesma
              grade de timestamps (ver `alinhar`).
    wide      Latência e banda juntas em um único CSV em formato largo
              (`latencia_banda_wide.csv`), uma linha por instante e uma coluna
              por par (métrica, rota), no mesmo padrão `metrica__rota` usado
              por `construir_wide` em `feature_store/pipeline.py`.
    tudo      Equivale a `ambas wide`.

Em todas as saídas cada série é reindexada para a grade completa de 1 s e os
valores ausentes são interpolados linearmente no tempo, de modo que o CSV nunca
tenha segundos faltando nem células vazias.

Exemplos:

    # Só latência, de todos os cenários, em datasets_gerados/<cenario>/
    python3 main.py latencia

    # As duas métricas alinhadas, apenas de D1 e D2
    python3 main.py ambas --datasets D1 D2

    # Formato largo de D4, sobrescrevendo a saída anterior
    python3 main.py wide --datasets D4 --sobrescrever

    # Regenera os relatórios por rota a partir de banda.bwm antes de consolidar
    #   (atenção: isso reescreve arquivos dentro da pasta do cenário)
    python3 main.py banda --datasets D1 --regerar-banda
"""

import argparse
import glob
import os
import sys
import tempfile

import pandas as pd

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

import gerar_relatorio_banda_rotas as relatorio_banda
import gerar_relatorio_latencia as relatorio_latencia

PASTA_DATASETS = os.path.join(RAIZ, 'datasets')
DESTINO_PADRAO = os.path.join(RAIZ, 'datasets_gerados')

ARQUIVO_LATENCIA = 'latencia_rotas_h1_h6.csv'
ARQUIVO_BANDA = relatorio_banda.ARQUIVO_BANDA_CONSOLIDADA
ARQUIVO_ROTULOS = 'rotulos_h1_h6.txt'
ARQUIVO_WIDE = 'latencia_banda_wide.csv'

ROTAS_PADRAO = [1, 2, 3, 4]

# Nomes das métricas no formato largo, com a unidade embutida, seguindo a
#   convenção de `feature_store/pipeline.py` (latencia_ms, gargalo_Mbps)
METRICA_LATENCIA = 'latencia_ms'
METRICA_BANDA = 'banda_Mbps'

FORMATO_TIMESTAMP = '%Y-%m-%d %H:%M:%S'


################################################################################
# Nome da coluna de uma rota no CSV consolidado, ex: 1 -> 'h11_h61'
#
def nomeColuna(id_rota):
    return f'h1{id_rota}_h6{id_rota}'


################################################################################
# Carrega os relatórios por rota de uma métrica e devolve um DataFrame com
#   índice de tempo e uma coluna por rota
#
#   A leitura de cada arquivo usa o parser já existente do script da métrica
#   (ler_arquivo_latencia / lerArquivoBanda), que descarta leituras marcadas
#   como 'None' (ex: os primeiros segundos antes da primeira resposta de ping).
#
# Parâmetros:
#   pasta - pasta do cenário
#   rotas - lista com os IDs das rotas a carregar
#   metrica - 'latencia' ou 'banda'
# Retorno:
#   DataFrame ordenado pelo tempo, ou None se nenhum arquivo for encontrado
#
def carregarSerie(pasta, rotas, metrica):
    if metrica == 'latencia':
        modelo, leitor = 'latencia_rota_{}.txt', relatorio_latencia.ler_arquivo_latencia
    else:
        modelo, leitor = 'banda_rota_{}.txt', relatorio_banda.lerArquivoBanda

    colunas = {}
    for id_rota in sorted(rotas):
        coluna = nomeColuna(id_rota)
        caminho = os.path.join(pasta, modelo.format(coluna))
        if not os.path.isfile(caminho):
            continue

        serie = pd.Series(leitor(caminho), dtype=float)
        serie.index = pd.to_datetime(serie.index)
        colunas[coluna] = serie.sort_index()

    if not colunas:
        return None

    return pd.concat(
        colunas.values(), axis=1, keys=colunas.keys(), sort=True
    ).sort_index()


################################################################################
# Reindexa um DataFrame para uma grade de tempo e interpola os valores que
#   faltam, linearmente no tempo
#
#   Mesma estratégia usada em consolidarBandaInterpolada e na célula de
#   alinhamento do notebook: a união entre o índice original e a grade preserva
#   as leituras fora da grade como âncoras da interpolação, e o reindex final
#   mantém apenas os instantes da grade. limit_direction='both' repete o valor
#   mais próximo nas extremidades sem vizinho de um dos lados.
#
# Parâmetros:
#   quadro - DataFrame com índice de tempo
#   grade - DatetimeIndex de destino
# Retorno:
#   Tupla (DataFrame na grade, número de valores interpolados)
#
def interpolarParaGrade(quadro, grade):
    unido = quadro.reindex(quadro.index.union(grade))
    n_interpolados = int(unido.isna().sum().sum())

    resultado = (
        unido
        .interpolate(method='time', limit_direction='both')
        .reindex(grade)
    )
    resultado.index.name = 'timestamp'
    return resultado, n_interpolados


################################################################################
# Grade completa de 1 s que cobre todo o intervalo de um DataFrame
#
def gradeCompleta(quadro):
    return pd.date_range(quadro.index.min(), quadro.index.max(), freq='1s')


################################################################################
# Coloca latência e banda na mesma grade de 1 s
#
#   As duas métricas são coletadas por processos independentes, então seus
#   instantes não coincidem: a latência costuma começar um segundo depois da
#   banda (as primeiras leituras do ping vêm como 'None' e são descartadas) e,
#   em alguns cenários, terminar um segundo depois dela. A grade usada é a
#   interseção dos dois intervalos, de modo que nenhum valor seja extrapolado
#   para fora do período realmente medido por uma das métricas.
#
# Parâmetros:
#   latencia - DataFrame de latência (ver carregarSerie)
#   banda - DataFrame de banda (ver carregarSerie)
# Retorno:
#   Tupla (latencia_alinhada, banda_alinhada, grade, interpolados_latencia,
#   interpolados_banda)
#
def alinhar(latencia, banda):
    inicio = max(latencia.index.min(), banda.index.min())
    fim = min(latencia.index.max(), banda.index.max())

    if inicio > fim:
        raise ValueError(
            'latência e banda não se sobrepõem no tempo: '
            f'latência {latencia.index.min()}..{latencia.index.max()}, '
            f'banda {banda.index.min()}..{banda.index.max()}'
        )

    grade = pd.date_range(inicio, fim, freq='1s')
    latencia_alinhada, n_latencia = interpolarParaGrade(latencia, grade)
    banda_alinhada, n_banda = interpolarParaGrade(banda, grade)

    return latencia_alinhada, banda_alinhada, grade, n_latencia, n_banda


################################################################################
# Junta latência e banda em um único DataFrame em formato largo
#
#   Uma linha por instante e uma coluna por par (métrica, rota), nomeada
#   'metrica__rota' (ex: 'latencia_ms__h11_h61'), como em construir_wide de
#   feature_store/pipeline.py. Esse layout é o necessário para que um modelo
#   compare as rotas entre si no mesmo instante.
#
# Parâmetros:
#   latencia - DataFrame de latência já alinhado
#   banda - DataFrame de banda já alinhado
#   rotulos - lista/serie com o ID da melhor rota de cada instante, ou None
# Retorno:
#   DataFrame com a coluna 'timestamp' e, se houver rótulos, 'melhor_rota'
#
def construirWide(latencia, banda, rotulos=None):
    if not latencia.index.equals(banda.index):
        raise ValueError('latência e banda precisam estar na mesma grade de tempo')

    largo = pd.concat(
        [latencia, banda], axis=1, keys=[METRICA_LATENCIA, METRICA_BANDA]
    )
    largo.columns = [f'{metrica}__{rota}' for metrica, rota in largo.columns]

    # Ordena as colunas por métrica e, dentro de cada métrica, por rota
    ordem = [
        f'{metrica}__{coluna}'
        for metrica in (METRICA_LATENCIA, METRICA_BANDA)
        for coluna in latencia.columns
    ]
    largo = largo[ordem]

    if rotulos is not None:
        largo['melhor_rota'] = pd.Series(list(rotulos), index=largo.index)

    return largo.reset_index()


################################################################################
# Grava um DataFrame indexado pelo tempo como CSV consolidado
#
def escreverCsv(quadro, caminho):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    if quadro.index.name == 'timestamp':
        quadro.to_csv(caminho, date_format=FORMATO_TIMESTAMP)
    else:
        quadro.to_csv(caminho, index=False, date_format=FORMATO_TIMESTAMP)
    return caminho


################################################################################
# Lê o arquivo de rótulos gerado por criar_arquivo_rotulos
#
def lerRotulos(caminho):
    with open(caminho) as arquivo:
        return [int(linha) for linha in arquivo if linha.strip()]


################################################################################
# Resolve quais saídas devem ser produzidas a partir dos nomes pedidos
#
# Retorno:
#   Tupla (gerar_latencia, gerar_banda, alinhar_metricas, gerar_wide)
#
def resolverSaidas(saidas):
    pedidas = set(saidas)
    if 'tudo' in pedidas:
        pedidas |= {'ambas', 'wide'}

    gerar_wide = 'wide' in pedidas
    gerar_latencia = bool(pedidas & {'latencia', 'ambas'})
    gerar_banda = bool(pedidas & {'banda', 'ambas'})

    # O formato largo exige as duas métricas na mesma grade, mesmo que os CSVs
    #   separados não tenham sido pedidos
    alinhar_metricas = gerar_wide or 'ambas' in pedidas

    return gerar_latencia, gerar_banda, alinhar_metricas, gerar_wide


################################################################################
# Gera as saídas pedidas para um cenário
#
# Parâmetros:
#   pasta - pasta do cenário (entrada)
#   destino - pasta onde os arquivos serão gravados
#   saidas - lista de saídas pedidas (ver resolverSaidas)
#   rotas - lista com os IDs das rotas
#   rotulos - se True, gera também o arquivo de rótulos quando houver latência
#   sobrescrever - se False, aborta caso algum arquivo de saída já exista
#   regerar_banda - se True, regenera os relatórios por rota a partir de
#       banda.bwm antes de consolidar (reescreve arquivos na pasta do cenário)
# Retorno:
#   Lista com os caminhos dos arquivos gerados
#
def gerarDataset(pasta, destino, saidas, rotas=ROTAS_PADRAO, rotulos=True,
                 sobrescrever=False, regerar_banda=False):
    nome_cenario = os.path.basename(os.path.normpath(pasta))
    gerar_latencia, gerar_banda, alinhar_metricas, gerar_wide = resolverSaidas(saidas)

    if regerar_banda and (gerar_banda or alinhar_metricas):
        # Reaproveita o script de banda para extrair de banda.bwm os relatórios
        #   por rota (banda_rota_*.txt) antes de consolidá-los
        relatorio_banda.gerarRelatoriosBanda(pasta)

    # --- confere os arquivos de saída antes de escrever qualquer um deles ---
    previstos = []
    if gerar_latencia:
        previstos.append(ARQUIVO_LATENCIA)
        if rotulos:
            previstos.append(ARQUIVO_ROTULOS)
    if gerar_banda:
        previstos.append(ARQUIVO_BANDA)
    if gerar_wide:
        previstos.append(ARQUIVO_WIDE)

    existentes = [
        nome for nome in previstos if os.path.exists(os.path.join(destino, nome))
    ]
    if existentes and not sobrescrever:
        raise FileExistsError(
            f"[{nome_cenario}] já existe em {destino}: {', '.join(existentes)}. "
            'Use --sobrescrever para substituir ou --destino para outra pasta.'
        )

    # --- carrega as séries pedidas ---
    latencia = carregarSerie(pasta, rotas, 'latencia') if (gerar_latencia or gerar_wide) else None
    banda = carregarSerie(pasta, rotas, 'banda') if (gerar_banda or gerar_wide) else None

    if (gerar_latencia or gerar_wide) and latencia is None:
        print(f'[{nome_cenario}] sem relatórios de latência por rota, ignorado')
        return []
    if (gerar_banda or gerar_wide) and banda is None:
        print(f'[{nome_cenario}] sem relatórios de banda por rota, ignorado')
        return []

    # --- define a grade de tempo e interpola ---
    if alinhar_metricas and latencia is not None and banda is not None:
        latencia, banda, grade, n_latencia, n_banda = alinhar(latencia, banda)
        print(f'[{nome_cenario}] grade comum: {grade[0]} .. {grade[-1]} '
              f'({len(grade)} segundos)')
    else:
        grade = None
        n_latencia = n_banda = 0
        if latencia is not None:
            latencia, n_latencia = interpolarParaGrade(latencia, gradeCompleta(latencia))
        if banda is not None:
            banda, n_banda = interpolarParaGrade(banda, gradeCompleta(banda))

    # --- grava ---
    gerados = []

    if gerar_latencia:
        caminho = escreverCsv(latencia, os.path.join(destino, ARQUIVO_LATENCIA))
        gerados.append(caminho)
        print(f'[{nome_cenario}] {ARQUIVO_LATENCIA} gerado '
              f'({len(latencia)} linhas, {len(latencia.columns)} rotas, '
              f'{n_latencia} valores interpolados)')

    if gerar_banda:
        caminho = escreverCsv(banda, os.path.join(destino, ARQUIVO_BANDA))
        gerados.append(caminho)
        print(f'[{nome_cenario}] {ARQUIVO_BANDA} gerado '
              f'({len(banda)} linhas, {len(banda.columns)} rotas, '
              f'{n_banda} valores interpolados)')

    # O rótulo (rota de menor latência em cada instante) é derivado do CSV de
    #   latência pela função já existente no script de latência
    caminho_rotulos = None
    if gerar_latencia and rotulos:
        relatorio_latencia.criar_arquivo_rotulos(destino, ARQUIVO_LATENCIA, ARQUIVO_ROTULOS)
        caminho_rotulos = os.path.join(destino, ARQUIVO_ROTULOS)
        gerados.append(caminho_rotulos)

    if gerar_wide:
        valores_rotulos = None
        if rotulos and caminho_rotulos is not None:
            valores_rotulos = lerRotulos(caminho_rotulos)
        elif rotulos:
            # Formato largo pedido sem o CSV de latência: o rótulo é gerado em
            #   uma pasta temporária, na mesma grade do largo, para não criar
            #   nem apagar nada no destino
            with tempfile.TemporaryDirectory() as temporaria:
                escreverCsv(latencia, os.path.join(temporaria, ARQUIVO_LATENCIA))
                relatorio_latencia.criar_arquivo_rotulos(
                    temporaria, ARQUIVO_LATENCIA, ARQUIVO_ROTULOS
                )
                valores_rotulos = lerRotulos(os.path.join(temporaria, ARQUIVO_ROTULOS))

        largo = construirWide(latencia, banda, valores_rotulos)
        caminho = escreverCsv(largo, os.path.join(destino, ARQUIVO_WIDE))
        gerados.append(caminho)
        print(f'[{nome_cenario}] {ARQUIVO_WIDE} gerado '
              f'({len(largo)} linhas, {len(largo.columns)} colunas)')

    return gerados


################################################################################
# Lista as pastas de cenário a processar
#
def listarCenarios(nomes):
    if nomes:
        return [os.path.join(PASTA_DATASETS, nome) for nome in nomes]
    return [
        pasta for pasta in sorted(glob.glob(os.path.join(PASTA_DATASETS, '*')))
        if os.path.isdir(pasta)
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'saidas', nargs='+',
        choices=['latencia', 'banda', 'ambas', 'wide', 'tudo'],
        help='quais datasets gerar',
    )
    parser.add_argument(
        '--datasets', nargs='+', metavar='CENARIO',
        help='cenários a processar (padrão: todos os de datasets/)',
    )
    parser.add_argument(
        '--rotas', nargs='+', type=int, default=ROTAS_PADRAO, metavar='ID',
        help=f'IDs das rotas a consolidar (padrão: {" ".join(map(str, ROTAS_PADRAO))})',
    )
    parser.add_argument(
        '--destino', default=DESTINO_PADRAO,
        help='pasta de saída; cada cenário vira uma subpasta '
             f'(padrão: {os.path.relpath(DESTINO_PADRAO, RAIZ)}/). '
             'Use --destino datasets para gravar na própria pasta do cenário',
    )
    parser.add_argument(
        '--sem-rotulos', dest='rotulos', action='store_false',
        help='não gera rotulos_h1_h6.txt nem a coluna melhor_rota',
    )
    parser.add_argument(
        '--sobrescrever', action='store_true',
        help='substitui arquivos de saída já existentes',
    )
    parser.add_argument(
        '--regerar-banda', action='store_true',
        help='extrai novamente os relatórios por rota de banda.bwm antes de '
             'consolidar (reescreve arquivos dentro da pasta do cenário)',
    )
    argumentos = parser.parse_args(argv)

    gerados = []
    for pasta in listarCenarios(argumentos.datasets):
        if not os.path.isdir(pasta):
            print(f'Cenário não encontrado: {pasta}')
            continue

        nome_cenario = os.path.basename(os.path.normpath(pasta))
        destino = os.path.join(argumentos.destino, nome_cenario)

        try:
            gerados += gerarDataset(
                pasta, destino, argumentos.saidas,
                rotas=argumentos.rotas,
                rotulos=argumentos.rotulos,
                sobrescrever=argumentos.sobrescrever,
                regerar_banda=argumentos.regerar_banda,
            )
        except FileExistsError as erro:
            # Nenhum arquivo do cenário foi escrito; erro de uso, não de dados
            parser.exit(1, f'{erro}\n')

    print(f'\n{len(gerados)} arquivo(s) gerado(s)')
    return gerados


if __name__ == '__main__':
    main()
