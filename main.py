import parser
import plot_latencias
import pandas as pd


def main():
    # Usados para consolidar latencias de caminhos especificos
    suffix = ''             # ex: _12
    caminhos=[1, 2, 3, 4]

    dir = 'antiga_latencia/60min_iperf'
    arq_latencias = f'latencia_rotas_h1_h6{suffix}.csv'
    arq_labels = f'labels_h1_h6{suffix}.txt'
    arq_grafico = f'{dir}/latencias{suffix}.png'

    parser.consolidate_latencies(dir, arq_latencias, caminhos)
    parser.create_labels_file(dir, arq_latencias, arq_labels)

    leituras = pd.read_csv(f'{dir}/{arq_latencias}')

    datetimes = leituras.iloc[:, 0].values
    latencias = leituras.iloc[:, 1:].values

    # Usados para consolidar latências em um intervalo específico
    begin = 0
    end = len(latencias)

    # begin = 0
    # end = 1000

    # Exibe o gráfico de latências
    plot_latencias.plot_latencias(datetimes[begin:end], latencias[begin:end], arq_grafico, caminhos)



if __name__ == "__main__":
    main()