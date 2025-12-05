import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pandas import DataFrame, read_csv
import re

arq = 'testes/3/banda.bwm'

colunas = [
    'unix_timestamp','interface','bytes_out_s','bytes_in_s','bytes_total_s',
    'bytes_in','bytes_out','packets_out_s','packets_in_s','packets_total_s',
    'packets_in','packets_out','errors_out_s','errors_in_s','errors_in','errors_out',
    "drops_out_s", "drops_in_s", "drops_total_s", "drops_in", "drops_out"
]

data = pd.read_csv(arq, delimiter=',', usecols=range(21))
data.columns = colunas

# Converte taxa para Mbps
def toMbps(df):
    return (df * 8.0) / (1 << 20)  # bytes→bits, depois /1048576

# Filtra interfaces do tipo s{i}_eth (ex: s1_eth, s2_eth...)
#df_interfaces = data[data['interface'].str.match(r'^s\d+-eth.*$')]]

# data['taxa_total_Mbps'] = toMbps(data['bytes_in'])
# df_interfaces = data[data['interface'].str.match(r'^s6-eth.*$')]

data['taxa_total_Mbps'] = toMbps(data['bytes_out'])
df_interfaces = data[data['interface'].str.match(r'^s6-eth.*$')]



# Obtém lista única de interfaces
interfaces_unicas = df_interfaces['interface'].unique()
interfaces_unicas.sort()
print("Interfaces encontradas:", interfaces_unicas)

# Vetor de cores expandido automaticamente
colors = plt.cm.tab20(np.linspace(0, 1, len(interfaces_unicas)))
markers = ["x", "+", "2", ".", "o", "s", "d", "^", "v", "<", ">"]

plt.rcParams.update({'font.size': 10, 'figure.autolayout': True})
fig, ax = plt.subplots(figsize=(15,7))

# Plota todas as interfaces individuais
for i, iface in enumerate(interfaces_unicas):
    df_iface = df_interfaces[df_interfaces['interface'] == iface].reset_index(drop=True)
    ax.plot(
        df_iface.index,
        df_iface['taxa_total_Mbps'],
        color=colors[i],
        marker=markers[i % len(markers)],
        linestyle='solid',
        label=iface
    )

ax.set_xlim((0, 180))
ax.set_xlabel('Tempo (s)')
ax.set_ylabel('Taxa (Mbps)')
ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.title('Vazão por Interface (apenas s{i}_eth)')

plt.show()
