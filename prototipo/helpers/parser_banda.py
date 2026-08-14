import csv
import math
import pandas as pd
from datetime import datetime

BWM_NG_COLUNAS = ['unix_timestamp','interface','bytes_out_s','bytes_in_s','bytes_total_s','bytes_in','bytes_out','packets_out_s','packets_in_s','packets_total_s','packets_in','packets_out','errors_out_s','errors_in_s','errors_in','errors_out']

# Converte taxa para Mbps
def toMbps(df):
    dfY = (df * 8.0) / (1 << 20)  ## 1byte x 8bits / 1048576
    return dfY
        
def parseBanda(rota, topologia):
    nomeRota = rota['nome']
    arquivo = f"relatorios/banda_{nomeRota}.csv"

    data = pd.read_csv(arquivo, delimiter=',', usecols=range(len(BWM_NG_COLUNAS)))
    data.columns = BWM_NG_COLUNAS

    # Mantem apenas as linhas das interfaces
    data = data.drop(data[data['interface'] == 'total'].index)

    # Cria coluna com tempo em datetime
    data['datetime'] = pd.to_datetime(data['unix_timestamp'], unit='s')

    # Cria uma colula com a taxa total em Mbps
    data['taxa_total_Mbps'] = toMbps(data['bytes_total_s'])

    # Cria uma coluna com a banda disponível no link
    # todo: obter a capacidade do link a partir da topologia e da interface
    data['banda_disponivel'] = 100 - data['taxa_total_Mbps']
    
    # Salva resultado em um TXT por tabulação (\t)
    colunas_desejadas = ['datetime', 'interface', 'taxa_total_Mbps', 'banda_disponivel']
    data.to_csv(f"relatorios/consolidado/banda_teste_{nomeRota}.txt", sep='\t', columns=colunas_desejadas, index=False)


    # open csv
    # foreach line:
        # parse dateTime 
        # parse bytes_total_s to MB 
        # calcula disponivel (capacidade - bytes_total_mb)
        # add interface
        # append to list
    # end: [{datetime, interface, throuputh, disponivel }]
