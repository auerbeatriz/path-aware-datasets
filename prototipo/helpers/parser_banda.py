import csv
import math
import os
import re
import pandas as pd
from datetime import datetime

BWM_NG_COLUNAS = ['unix_timestamp','interface','bytes_out_s','bytes_in_s','bytes_total_s','bytes_in','bytes_out','packets_out_s','packets_in_s','packets_total_s','packets_in','packets_out','errors_out_s','errors_in_s','errors_in','errors_out']

PADRAO_NOME_ROTA = re.compile(r'rota_h1(\d+)_h6\1')
PADRAO_ARQUIVO_BANDA = re.compile(r'banda_rota_h1(\d+)_h6\1\.txt')

# Converte taxa para Mbps
def toMbps(df):
    dfY = (df * 8.0) / (1 << 20)  ## 1byte x 8bits / 1048576
    return dfY
        
def parseBanda(rota, topologia, capacidade_por_interface):
    nomeRota = rota['nome']
    arquivo = f"relatorios/banda_raw_{nomeRota}.csv"

    data = pd.read_csv(arquivo, delimiter=',', usecols=range(len(BWM_NG_COLUNAS)))
    data.columns = BWM_NG_COLUNAS

    # Mantem apenas as linhas das interfaces
    data = data.drop(data[data['interface'] == 'total'].index)

    # Cria coluna com tempo em datetime, no horário local (mesma convenção usada
    #   em arquivosSalvar/relatorios.py, que usa datetime.fromtimestamp). Usar
    #   pd.to_datetime(..., unit='s') geraria o horário em UTC, ficando
    #   defasado do horário local usado nos demais relatórios (ex: latência).
    data['datetime'] = data['unix_timestamp'].apply(datetime.fromtimestamp)

    # Cria uma colula com a taxa total em Mbps
    data['taxa_total_Mbps'] = toMbps(data['bytes_total_s'])

    data['banda_disponivel'] = (
        data['interface'].map(capacidade_por_interface) - data['taxa_total_Mbps']
    )
    
    # Salva resultado em um TXT por tabulação (\t)
    colunas_desejadas = ['datetime', 'interface', 'taxa_total_Mbps', 'banda_disponivel']
    data.to_csv(f"relatorios/banda_tratada_{nomeRota}.csv", columns=colunas_desejadas, index=False)

    # Agrupa por segundo e mantem apenas o gargalo (menor banda disponivel entre as interfaces da rota) em cada segundo
    data['datahora'] = data['datetime'].dt.floor('s')
    gargalo = data.groupby('datahora')['banda_disponivel'].min().reset_index()
    gargalo.columns = ['datahora', 'banda']

    gargalo.to_csv(f"relatorios/banda_{nomeRota}.txt", sep="\t", index=False, header=False)

    # with open(f"relatorios/banda_{nomeRota}.csv", 'w') as f:
    #     f.write('# datahora min(banda_disponivel)\n')
    #     gargalo.to_csv(f, index=False, header=False)

################################################################################
# Constrói, a partir da lista de links da topologia, a capacidade de cada
#   interface e o nome da interface usada em cada sentido de cada link.
#   Reproduz a numeração de portas do Mininet: cada ponto (switch/host) tem
#   seu próprio contador de porta, incrementado na ordem em que aparece na
#   lista de links.
#
# Parâmetros:
#   links - lista de links da topologia (topologia['links'] do config.json)
# Retorno:
#   (capacidade_por_interface, interface_no_link)
#   capacidade_por_interface - dict {'ponto-ethN': capacidade}
#   interface_no_link - dict {(pontoA, pontoB): 'pontoA-ethN'} com a
#       interface do lado de pontoA voltada para pontoB
#
def capacidadeInterfaces(links):
    proxima_porta = {}
    capacidade_por_interface = {}
    interface_no_link = {}
    for link in links:
        capacidade = float(link.get('banda'))
        pontoA, pontoB = link['pontos']
        portaA = proxima_porta.get(pontoA, 0) + 1
        proxima_porta[pontoA] = portaA
        portaB = proxima_porta.get(pontoB, 0) + 1
        proxima_porta[pontoB] = portaB
        capacidade_por_interface[f'{pontoA}-eth{portaA}'] = capacidade
        capacidade_por_interface[f'{pontoB}-eth{portaB}'] = capacidade
        interface_no_link[(pontoA, pontoB)] = f'{pontoA}-eth{portaA}'
        interface_no_link[(pontoB, pontoA)] = f'{pontoB}-eth{portaB}'
    return capacidade_por_interface, interface_no_link

################################################################################
# Resolve as interfaces (dos switches) usadas pelos saltos de um caminho
#   Ignora o primeiro e o último elemento do caminho (host de origem e de
#   destino), da mesma forma que procAgenteTelemetriaBanda em telemetria.py
#
# Parâmetros:
#   caminho - lista de nomes do caminho, ex: ['h11','s1','s2','s3','s6','h61']
#   interface_no_link - dict retornado por capacidadeInterfaces
# Retorno:
#   lista de nomes de interface, uma por salto entre switches
#
def interfacesDoCaminho(caminho, interface_no_link):
    switches = caminho[1:-1]
    interfaces = []
    for indice in range(len(switches) - 1):
        par = (switches[indice], switches[indice + 1])
        interfaces.append(interface_no_link[par])
    return interfaces

################################################################################
# Carrega o arquivo consolidado de banda (banda.bwm), contendo a telemetria
#   de bwm-ng de todas as interfaces do experimento
#
# Parâmetros:
#   arquivo - caminho do arquivo banda.bwm
# Retorno:
#   DataFrame com as colunas do bwm-ng mais 'datetime' e 'taxa_total_Mbps'
#
def carregarBandaConsolidada(arquivo):
    data = pd.read_csv(
        arquivo, delimiter=',', header=None, usecols=range(len(BWM_NG_COLUNAS))
    )
    data.columns = BWM_NG_COLUNAS

    # Mantem apenas as linhas das interfaces
    data = data.drop(data[data['interface'] == 'total'].index)

    # Horário local, mesma convenção do restante do código (ver parseBanda)
    data['datetime'] = data['unix_timestamp'].apply(datetime.fromtimestamp)
    data['taxa_total_Mbps'] = toMbps(data['bytes_total_s'])
    return data

################################################################################
# Extrai, do arquivo consolidado de banda, o relatório de banda disponível
#   de um caminho específico (gargalo entre as interfaces do caminho)
#
# Parâmetros:
#   nome - nome da rota (ex: 'rota_h11_h61')
#   interfaces - lista de interfaces do caminho (ver interfacesDoCaminho)
#   data - DataFrame retornado por carregarBandaConsolidada
#   capacidade_por_interface - dict retornado por capacidadeInterfaces
#   pasta_saida - pasta onde os relatórios serão salvos
# Retorno:
#   None
#
def parseBandaCaminho(nome, interfaces, data, capacidade_por_interface, pasta_saida='relatorios'):
    dados_rota = data[data['interface'].isin(interfaces)].copy()

    dados_rota['banda_disponivel'] = (
        dados_rota['interface'].map(capacidade_por_interface) - dados_rota['taxa_total_Mbps']
    )

    # Salva resultado em um TXT por tabulação (\t)
    colunas_desejadas = ['datetime', 'interface', 'taxa_total_Mbps', 'banda_disponivel']
    dados_rota.to_csv(f"{pasta_saida}/banda_tratada_{nome}.csv", columns=colunas_desejadas, index=False)

    # Agrupa por segundo e mantem apenas o gargalo (menor banda disponivel entre as interfaces da rota) em cada segundo
    dados_rota['datahora'] = dados_rota['datetime'].dt.floor('s')
    gargalo = dados_rota.groupby('datahora')['banda_disponivel'].min().reset_index()
    gargalo.columns = ['datahora', 'banda']

    gargalo.to_csv(f"{pasta_saida}/banda_{nome}.txt", sep="\t", index=False, header=False)

################################################################################
# Extrai o id (r) de um nome de rota no formato 'rota_h1<r>_h6<r>'
#
# Parâmetros:
#   nome - nome da rota, ex: 'rota_h11_h61'
# Retorno:
#   int com o id da rota, ou None se o nome não seguir o padrão
#
def idRotaDoNome(nome):
    correspondencia = PADRAO_NOME_ROTA.match(nome)
    return int(correspondencia.group(1)) if correspondencia else None

################################################################################
# Lê um arquivo de banda (linhas 'datahora\tbanda') e retorna um dicionário
#   {timestamp: banda}, no mesmo formato usado para ler arquivos de latência
#
# Parâmetros:
#   caminho_arquivo - caminho do arquivo de banda por caminho (banda_rota_h1<r>_h6<r>.txt)
# Retorno:
#   dict {timestamp: banda}
#
def lerArquivoBanda(caminho_arquivo):
    bandas = {}

    with open(caminho_arquivo, 'r') as arquivo:
        for linha in arquivo:
            linha = linha.strip()
            if not linha:
                continue

            partes = linha.split('\t')
            if len(partes) == 2:
                timestamp, valor = partes
                if valor != 'None':
                    bandas[timestamp] = float(valor)

    return bandas

################################################################################
# Consolida os arquivos individuais de banda disponível por caminho
#   (banda_rota_h1<r>_h6<r>.txt) em um único CSV, seguindo o mesmo formato
#   usado para consolidar as latências em 'latencia_rotas_h1_h6.csv'
#
# Parâmetros:
#   diretorio - diretório contendo os arquivos de banda por rota
#   nome_arquivo_saida - nome do arquivo CSV de saída
#   rotas - lista com os IDs das rotas a consolidar
# Retorno:
#   Tupla (caminho_arquivo_saida, rotas_encontradas) ou None se nenhum arquivo for encontrado
#
def consolidarBanda(diretorio, nome_arquivo_saida, rotas):
    dados_rotas = {}

    for nome_arquivo in os.listdir(diretorio):
        correspondencia = PADRAO_ARQUIVO_BANDA.match(nome_arquivo)
        if not correspondencia:
            continue

        pathId = int(correspondencia.group(1))
        if pathId not in rotas:
            continue

        caminho = os.path.join(diretorio, nome_arquivo)
        dados_rotas[pathId] = lerArquivoBanda(caminho)

    if not dados_rotas:
        return None

    rotas_ordenadas = sorted(dados_rotas.keys())

    # União de todos os timestamps presentes nos arquivos
    todos_timestamps = sorted(
        {ts for bandas in dados_rotas.values() for ts in bandas}
    )

    # Escrita do CSV consolidado
    caminho_saida = os.path.join(diretorio, nome_arquivo_saida)
    with open(caminho_saida, 'w') as arquivo_saida:
        cabecalho = 'timestamp,' + ','.join(f'h1{r}_h6{r}' for r in rotas_ordenadas)
        arquivo_saida.write(cabecalho + '\n')

        for timestamp in todos_timestamps:
            valores = []
            for id_rota in rotas_ordenadas:
                banda = dados_rotas[id_rota].get(timestamp)
                valores.append(str(banda) if banda is not None else '')

            # Ignora linhas sem nenhuma banda válida
            if any(v != '' for v in valores):
                arquivo_saida.write(timestamp + ',' + ','.join(valores) + '\n')

    return caminho_saida, rotas_ordenadas
