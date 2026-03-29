import os
import re
import pandas as pd
from collections import defaultdict

from plot_latencias import plot_latencias

def ler_arquivo_latencia(caminho_arquivo):
    """Lê um arquivo de latência e retorna um dicionário {timestamp: latencia}."""
    latencias = {}

    with open(caminho_arquivo, 'r') as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue

            partes = linha.split('\t')
            if len(partes) == 2:
                timestamp, valor = partes
                if valor != 'None':
                    latencias[timestamp] = float(valor)

    return latencias

def consolidar_latencias(diretorio, nome_arquivo_saida, rotas):
    """
    Consolida arquivos individuais de latência em um único CSV.

    Parâmetros:
        diretorio:          Diretório contendo os arquivos de latência por rota.
        nome_arquivo_saida: Nome do arquivo CSV de saída.
        rotas:              Lista com os IDs das rotas a consolidar (pode escolher um subconjunto de pathIds).

    Retorno:
        Tupla (caminho_arquivo_saida, rotas_encontradas) ou None se nenhum arquivo for encontrado.
    """
    padrao = re.compile(r'latencia_rota_h1(\d+)_h6\1\.txt')
    dados_rotas = {}

    # Lê cada arquivo que corresponde ao padrão e está na lista de rotas
    for nome_arquivo in os.listdir(diretorio):
        correspondencia = padrao.match(nome_arquivo)
        if not correspondencia:
            continue

        pathId = int(correspondencia.group(1))
        if pathId not in rotas:
            continue

        caminho = os.path.join(diretorio, nome_arquivo)
        dados_rotas[pathId] = ler_arquivo_latencia(caminho)
        print(f"Lido: {nome_arquivo}  ({len(dados_rotas[pathId])} registros)")

    if not dados_rotas:
        print(f"Nenhum arquivo encontrado em: {diretorio}")
        return None

    rotas_ordenadas = sorted(dados_rotas.keys())
    print(f"\nRotas encontradas: {rotas_ordenadas}")

    # União de todos os timestamps presentes nos arquivos
    todos_timestamps = sorted(
        {ts for latencias in dados_rotas.values() for ts in latencias}
    )

    # Escrita do CSV consolidado
    caminho_saida = os.path.join(diretorio, nome_arquivo_saida)
    with open(caminho_saida, 'w') as arquivo_saida:
        cabecalho = 'timestamp,' + ','.join(f'h1{r}_h6{r}' for r in rotas_ordenadas)
        arquivo_saida.write(cabecalho + '\n')

        for timestamp in todos_timestamps:
            valores = []
            for id_rota in rotas_ordenadas:
                latencia = dados_rotas[id_rota].get(timestamp)
                valores.append(str(latencia) if latencia is not None else '')

            # Ignora linhas sem nenhuma latência válida
            if any(v != '' for v in valores):
                arquivo_saida.write(timestamp + ',' + ','.join(valores) + '\n')

    print(f"\nArquivo consolidado criado: {caminho_saida}")
    print(f"Timestamps: {len(todos_timestamps)} | Rotas: {len(rotas_ordenadas)}")

    return caminho_saida, rotas_ordenadas


def criar_arquivo_rotulos(diretorio, nome_arquivo_entrada, nome_arquivo_saida):
    """
    Gera um TXT com o ID da rota de menor latência para cada timestamp.

    Parâmetros:
        diretorio:             Diretório dos arquivos.
        nome_arquivo_entrada:  CSV consolidado de latências.
        nome_arquivo_saida:    Nome do arquivo de rotulos a ser criado.
    """
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

            latencias_str = partes[1:]

            # Encontra o índice da menor latência
            menor_latencia = float('inf')
            id_melhor_rota = None

            for i, valor in enumerate(latencias_str):
                if valor in ('', 'None'):
                    continue
                try:
                    latencia = float(valor)
                    if latencia < menor_latencia:
                        menor_latencia = latencia
                        id_melhor_rota = i + 1  # IDs começam em 1
                except ValueError:
                    continue

            # Usa rota 1 como fallback caso todas as latências sejam inválidas
            saida.write(f"{id_melhor_rota if id_melhor_rota is not None else 1}\n")

    print(f"Arquivo de rotulos criado: {caminho_saida}")

def main():
    diretorio_dataset = "teste"
    dataset           = ""
    rotas             = [1, 2, 3, 4]

    arquivo_latencias = "latencia_rotas_h1_h6.csv"
    arquivo_rotulos    = "rotulos_h1_h6.txt"
    arquivo_grafico     = "grafico_latencia.png"
    caminho_dataset   = os.path.join(diretorio_dataset, dataset)

    # consolidar_latencias(caminho_dataset, arquivo_latencias, rotas)
    # criar_arquivo_rotulos(caminho_dataset, arquivo_latencias, arquivo_rotulos)

    leituras = pd.read_csv(f'{caminho_dataset}/{arquivo_latencias}')

    datetimes = leituras.iloc[:, 0].values
    latencias = leituras.iloc[:, 1:].values

    # Usados para consolidar latências em um intervalo específico
    begin = 0
    end = len(latencias)

    # Exibe o gráfico de latências
    plot_latencias(datetimes[begin:end], latencias[begin:end], f'{caminho_dataset}/{arquivo_grafico}', rotas, True)


if __name__ == "__main__":
    main()