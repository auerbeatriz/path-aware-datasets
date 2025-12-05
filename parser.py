import os
import re
from datetime import datetime
from collections import defaultdict

def read_latency_file(filepath):
    """Lê um arquivo de latência e retorna um dicionário {timestamp: latencia}"""
    latencies = {}
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split('\t')
            if len(parts) == 2:
                timestamp_str, latency_str = parts
                # Ignora linhas com None
                if latency_str != 'None':
                    latencies[timestamp_str] = float(latency_str)
    
    return latencies

def consolidate_latencies(dirname, output_filename, caminhos):
    """
    Consolida arquivos de latência em um único arquivo
    
    Args:
        dirname: Diretório contendo os arquivos
        caminhos: ID dos caminhos que devem ser consolidados no arquivo final
    """
    # Padrão para extrair o route_label do nome do arquivo
    pattern = re.compile(r'latencia_rota_h1(\d+)_h6\1\.txt')
    
    # Dicionário para armazenar latências: {route_label: {timestamp: latencia}}
    routes_data = {}
    
    # Lê todos os arquivos do diretório
    for filename in os.listdir(dirname):
        match = pattern.match(filename)

        if match:
            route_label = int(match.group(1))

            if route_label in caminhos:
                filepath = os.path.join(dirname, filename)
                
                latencies = read_latency_file(filepath)
                routes_data[route_label] = latencies
                print(f"Lido: {filename} com {len(latencies)} registros")
    
    if not routes_data:
        print(f"Nenhum arquivo encontrado no diretório: {dirname}")
        return
    
    # Ordena as rotas por label
    sorted_routes = sorted(routes_data.keys())
    print(f"\nRotas encontradas: {sorted_routes}")
    
    # Encontra todos os timestamps únicos (união de todos os timestamps)
    all_timestamps = set()
    for latencies in routes_data.values():
        all_timestamps.update(latencies.keys())
    
    # Ordena os timestamps
    sorted_timestamps = sorted(all_timestamps)

    print(output_filename)
    
    # Cria o arquivo consolidado em formato CSV
    output_file = os.path.join(dirname, output_filename)
    with open(output_file, 'w') as f:
        # Escreve cabeçalho
        header = 'timestamp,' + ','.join([f'h1{r}_h6{r}' for r in sorted_routes]) + '\n'
        f.write(header)
        
        for timestamp in sorted_timestamps:
            # Coleta latências de todas as rotas para este timestamp
            latencies = []
            for route_label in sorted_routes:
                latency = routes_data[route_label].get(timestamp, None)
                if latency is not None:
                    latencies.append(str(latency))
                else:
                    latencies.append('')
            
            # Escreve apenas se houver pelo menos uma latência válida
            if any(lat != '' for lat in latencies):
                line = timestamp + ',' + ','.join(latencies) + '\n'
                f.write(line)
    
    print(f"\nArquivo consolidado criado: {output_file}")
    print(f"Total de timestamps: {len(sorted_timestamps)}")
    print(f"Total de rotas: {len(sorted_routes)}")
    
    return output_file, sorted_routes

def create_labels_file(dirname, filename, output_filename):
    """
    Cria arquivo labels_h1_h6.csv com o ID da rota de menor latência para cada timestamp
    """
    latency_file = os.path.join(dirname, filename)
    
    if not os.path.exists(latency_file):
        print(f"Arquivo {latency_file} não encontrado!")
        return
    
    labels_file = os.path.join(dirname, output_filename)
    
    with open(latency_file, 'r') as f_in, open(labels_file, 'w') as f_out:
        # Lê e escreve cabeçalho
        header = f_in.readline().strip()
        
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(',')
            if len(parts) >= 2:
                timestamp = parts[0]
                latencies_str = parts[1:]
                
                # Encontra a rota com menor latência
                min_latency = float('inf')
                min_route_id = None
                
                for i, lat_str in enumerate(latencies_str):
                    if lat_str != '' and lat_str != 'None':
                        try:
                            latency = float(lat_str)
                            if latency < min_latency:
                                min_latency = latency
                                min_route_id = i + 1  # Route IDs começam em 1
                        except ValueError:
                            continue
                
                # Escreve o resultado
                if min_route_id is not None:
                    f_out.write(f"{min_route_id}\n")
                else:
                    # Se todas as latências são None, coloca 1
                    f_out.write(f"1\n")
    
    print(f"\nArquivo de labels criado: {labels_file}")

if __name__ == "__main__":
    dirname = "60min_iperf"
    filename = "teste.csv"
    
    consolidate_latencies(dirname, filename, caminhos=[1,2,3,4])
    create_labels_file(dirname, filename)