import csv
import math
import pandas as pd
from datetime import datetime

BWM_NG_COLUNAS = ['unix_timestamp','interface','bytes_out_s','bytes_in_s','bytes_total_s','bytes_in','bytes_out','packets_out_s','packets_in_s','packets_total_s','packets_in','packets_out','errors_out_s','errors_in_s','errors_in','errors_out']

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

    # Cria coluna com tempo em datetime
    data['datetime'] = pd.to_datetime(data['unix_timestamp'], unit='s')

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

    data['datetime'] = pd.to_datetime(data['unix_timestamp'], unit='s')
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
