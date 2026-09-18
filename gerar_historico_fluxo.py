import csv
import glob
import os

from desempate_rotulos import (
    escolher_rota,
    medias_janela_passado,
    novas_estatisticas,
    novo_gerador_aleatorio,
    parse_timestamp,
    parse_valor,
    resumo_estatisticas,
)

RAIZ = os.path.dirname(os.path.abspath(__file__))

################################################################################
# Lê um CSV consolidado (latencia_rotas_h1_h6.csv ou banda_rotas_h1_h6.csv) e
#   retorna (nomes_das_rotas, {timestamp: [valores_por_rota]})
#
def ler_csv_consolidado(caminho_arquivo):
    with open(caminho_arquivo, 'r', newline='') as arquivo:
        leitor = csv.reader(arquivo)
        cabecalho = next(leitor)
        rotas = cabecalho[1:]
        dados = {linha[0]: linha[1:] for linha in leitor if linha}
    return rotas, dados

################################################################################
# Consolida os CSVs de latencia e banda de um dataset em um único arquivo
#   historico_telemetria_h1_h6.csv, unindo pela coluna de timestamp
#
def consolidar_historico_telemetria(diretorio, arquivo_latencia, arquivo_banda, arquivo_saida):
    caminho_latencia = os.path.join(diretorio, arquivo_latencia)
    caminho_banda = os.path.join(diretorio, arquivo_banda)

    if not (os.path.isfile(caminho_latencia) and os.path.isfile(caminho_banda)):
        print(f"Arquivos de latência/banda não encontrados em: {diretorio}")
        return None

    rotas_latencia, dados_latencia = ler_csv_consolidado(caminho_latencia)
    rotas_banda, dados_banda = ler_csv_consolidado(caminho_banda)

    timestamps = sorted(set(dados_latencia) & set(dados_banda))

    caminho_saida = os.path.join(diretorio, arquivo_saida)
    with open(caminho_saida, 'w', newline='') as saida:
        escritor = csv.writer(saida)
        escritor.writerow(
            ['timestamp']
            + [f'latencia_{rota}' for rota in rotas_latencia]
            + [f'banda_{rota}' for rota in rotas_banda]
        )

        for timestamp in timestamps:
            escritor.writerow([timestamp] + dados_latencia[timestamp] + dados_banda[timestamp])

    print(f"Histórico de telemetria criado: {caminho_saida} ({len(timestamps)} linhas)")
    return caminho_saida

################################################################################
# Duplica as linhas de um dataset consolidado uma vez para cada categoria de
#   fluxo, marcando cada cópia com a categoria na última coluna. O cabeçalho
#   não é duplicado, apenas as linhas de dados. Função genérica: aceita
#   quantas categorias forem passadas em 'categorias'.
#
def duplicar_dataset_por_categoria(diretorio, arquivo, categorias):
    caminho_arquivo = os.path.join(diretorio, arquivo)
    if not os.path.isfile(caminho_arquivo):
        print(f"Arquivo não encontrado: {caminho_arquivo}")
        return None

    with open(caminho_arquivo, 'r', newline='') as entrada:
        leitor = csv.reader(entrada)
        cabecalho = next(leitor)
        linhas = [linha for linha in leitor if linha]

    with open(caminho_arquivo, 'w', newline='') as saida:
        escritor = csv.writer(saida)
        escritor.writerow(cabecalho + ['categoria'])

        for categoria in categorias:
            for linha in linhas:
                escritor.writerow(linha + [categoria])

    total_linhas = len(linhas) * len(categorias)
    print(f"Dataset duplicado em {len(categorias)} categoria(s): {caminho_arquivo} ({total_linhas} linhas)")
    return caminho_arquivo

################################################################################
# Funções objetivo por categoria de fluxo: recebem os valores de latencia e
#   banda de cada rota no instante (floats ou None, na mesma ordem), as médias
#   de cada coluna na janela passada (usadas só para desempate), o gerador
#   aleatório e o dicionário de estatísticas, e retornam o ID (1-indexado) da
#   melhor rota. Novas categorias podem ser adicionadas escrevendo uma nova
#   função objetivo (mesma assinatura) e registrando-a em CATEGORIAS_FLUXO.
#
# Desempate (ver desempate_rotulos.py): entre as rotas com exatamente o melhor
#   valor do instante, vence a de melhor média nos 'janela_segundos'
#   anteriores; persistindo o empate, sorteio com semente fixa.
#
def objetivo_menor_latencia(latencias, bandas, medias_latencia, medias_banda, rng, estatisticas):
    return escolher_rota(latencias, True, medias_latencia, rng, estatisticas)

def objetivo_maior_banda(latencias, bandas, medias_latencia, medias_banda, rng, estatisticas):
    return escolher_rota(bandas, False, medias_banda, rng, estatisticas)

# Registro de categorias de fluxo -> função objetivo usada para escolher a
#   melhor rota. Adicione novas entradas aqui para suportar novas categorias.
CATEGORIAS_FLUXO = {
    'mice': objetivo_menor_latencia,
    'elephant': objetivo_maior_banda,
}

################################################################################
# Gera um TXT com o ID da rota escolhida para cada linha do dataset
#   categorizado, usando a função objetivo correspondente à categoria do
#   fluxo (última coluna do CSV de entrada). As médias da janela passada são
#   calculadas separadamente por categoria, porque o arquivo traz todas as
#   linhas de uma categoria seguidas das da outra (cada bloco é cronológico).
#
def criar_arquivo_rotulos_por_fluxo(diretorio, arquivo_entrada, arquivo_saida, funcoes_objetivo,
                                    janela_segundos=10, semente=42):
    caminho_entrada = os.path.join(diretorio, arquivo_entrada)
    if not os.path.isfile(caminho_entrada):
        print(f"Arquivo não encontrado: {caminho_entrada}")
        return

    caminho_saida = os.path.join(diretorio, arquivo_saida)

    with open(caminho_entrada, 'r', newline='') as entrada:
        leitor = csv.reader(entrada)
        cabecalho = next(leitor)
        linhas = [linha for linha in leitor if linha]

    indices_latencia = [i for i, nome in enumerate(cabecalho) if nome.startswith('latencia_')]
    indices_banda = [i for i, nome in enumerate(cabecalho) if nome.startswith('banda_')]
    indices_metricas = indices_latencia + indices_banda
    num_latencias = len(indices_latencia)

    timestamps = [parse_timestamp(linha[0]) for linha in linhas]
    metricas = [[parse_valor(linha[i]) for i in indices_metricas] for linha in linhas]
    categorias = [linha[-1].strip() for linha in linhas]

    # Médias da janela passada por categoria, devolvidas na ordem original das linhas
    medias_por_linha = [None] * len(linhas)
    for categoria in dict.fromkeys(categorias):
        posicoes = [i for i, c in enumerate(categorias) if c == categoria]
        medias_categoria = medias_janela_passado(
            [timestamps[i] for i in posicoes], [metricas[i] for i in posicoes], janela_segundos
        )
        for posicao, medias in zip(posicoes, medias_categoria):
            medias_por_linha[posicao] = medias

    rng = novo_gerador_aleatorio(semente)
    estatisticas = novas_estatisticas()

    with open(caminho_saida, 'w') as saida:
        for categoria, valores, medias in zip(categorias, metricas, medias_por_linha):
            latencias, bandas = valores[:num_latencias], valores[num_latencias:]
            medias_latencia, medias_banda = medias[:num_latencias], medias[num_latencias:]

            funcao_objetivo = funcoes_objetivo[categoria]
            saida.write(f"{funcao_objetivo(latencias, bandas, medias_latencia, medias_banda, rng, estatisticas)}\n")

    print(f"Arquivo de rotulos por fluxo criado: {caminho_saida} [{resumo_estatisticas(estatisticas)}]")

def main():
    arquivo_latencia = "latencia_rotas_h1_h6.csv"
    arquivo_banda = "banda_rotas_h1_h6.csv"
    arquivo_historico = "historico_telemetria_h1_h6.csv"
    arquivo_rotulos = "rotulos_por_fluxo.txt"
    categorias = list(CATEGORIAS_FLUXO.keys())

    for pasta in sorted(glob.glob(os.path.join(RAIZ, 'datasets', '*'))):
        if not os.path.isdir(pasta):
            continue

        if consolidar_historico_telemetria(pasta, arquivo_latencia, arquivo_banda, arquivo_historico) is None:
            continue

        duplicar_dataset_por_categoria(pasta, arquivo_historico, categorias)
        criar_arquivo_rotulos_por_fluxo(pasta, arquivo_historico, arquivo_rotulos, CATEGORIAS_FLUXO)

if __name__ == "__main__":
    main()
