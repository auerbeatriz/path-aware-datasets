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
