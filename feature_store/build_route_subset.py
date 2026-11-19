"""Build the feature store of a subset of the paths of a collected dataset.

A subset store holds only some of the routes of an original dataset in
datasets/<SOURCE>/, built from that dataset's own raw capture (banda.bwm,
eventos.txt, rotas.txt, config.json and latencia_rota_*.txt). D3a and D4a are
the cases that motivated it: their wide CSVs are routes h11_h61 and h12_h62 of
D3 and D4, and have no raw capture of their own.

Why filtering the full store is exact. Every step of pipeline.construir works
on one route at a time: the clock alignment depends only on banda.bwm and
eventos.txt; bandwidth is read per interface and aggregated per route; latency
is read per route; the sliding windows, deltas and cross features are computed
within each route. The only step that compares routes is the target,
melhor_rota = argmin of the instant latency, which is recomputed here over the
kept routes only. The result is the same store that pipeline.construir would
produce if the collection had monitored just those routes.

Route indices. pipeline.derivar_alvo numbers the kept routes 1..k in sorted
order of rota_id, so for {h11_h61, h12_h62} the labels stay 1 and 2, as in the
original numbering and in the label files of D3a/D4a. For a subset such as
{h12_h62, h14_h64} the labels become 1 and 2, not 2 and 4. The mapping is
written to subset.json next to the store.

Usage (from the project root):
    python feature_store/build_route_subset.py D3 h11_h61 h12_h62 --name D3a
    python feature_store/build_route_subset.py D4 1 2 --name D4a
    python feature_store/build_route_subset.py --known      # D3a and D4a
"""

import argparse
import json
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, 'feature_store'))

import pipeline as fs  # noqa: E402

DATASETS_ROOT = os.path.join(_ROOT, 'datasets')
STORE_ROOT = os.path.join(_ROOT, 'feature_store', 'data')
REQUIRED_INPUTS = ['banda.bwm', 'eventos.txt', 'rotas.txt', 'config.json']

# Subsets that already exist in datasets/ as wide CSVs only
KNOWN_SUBSETS = {
    'D3a': ('D3', ['h11_h61', 'h12_h62']),
    'D4a': ('D4', ['h11_h61', 'h12_h62']),
}

_ROUTE_NUMBER = re.compile(r'^\d+$')


def normalize_route(token):
    """Accept 'h11_h61', 'rota_h11_h61' or the route number '1'."""
    token = token.strip()
    if _ROUTE_NUMBER.match(token):
        return f'h1{token}_h6{token}'
    return token.removeprefix('rota_')


def default_name(source, routes):
    numbers = [re.sub(r'^h1(\d+)_h6\1$', r'\1', route) for route in routes]
    return f"{source}_r{''.join(numbers)}"


def build_route_subset(source, routes, name=None, datasets_root=DATASETS_ROOT,
                       store_root=STORE_ROOT, persist=True):
    """Build the store of `routes` of dataset `source` and persist it under `name`.

    Returns the same dict as pipeline.construir, restricted to the kept routes,
    plus 'name', 'folder' and 'label_of_route'.
    """
    routes = sorted(dict.fromkeys(normalize_route(r) for r in routes))
    name = name or default_name(source, routes)
    source_folder = os.path.join(datasets_root, source)

    missing = [f for f in REQUIRED_INPUTS if not os.path.exists(os.path.join(source_folder, f))]
    if missing:
        raise FileNotFoundError(f'{source_folder}: missing raw inputs {missing}')

    full = fs.construir(
        pasta_relatorios=source_folder,
        caminho_config=os.path.join(source_folder, 'config.json'),
        arquivo_banda=os.path.join(source_folder, 'banda.bwm'),
        persistir_em_disco=False,
    )

    available = sorted(full['topologia']['rotas'])
    unknown = sorted(set(routes) - set(available))
    if unknown:
        raise ValueError(f'{source}: unknown route(s) {unknown}; available: {available}')
    if len(routes) < 2:
        raise ValueError('a subset needs at least two routes: the target compares them')

    def keep(frame):
        return frame[frame.rota_id.isin(routes)].reset_index(drop=True)

    # The target is the only cross-route quantity, so it is recomputed over the
    #   kept routes; every other column is per route and is kept as it is
    #   (the bandwidth target too: over all routes it could name a dropped one)
    view = keep(full['view']).drop(columns=['melhor_rota', fs.COLUNA_ALVO_BANDA])
    view = fs.derivar_alvo_banda(fs.derivar_alvo(view))
    result = {
        **full,
        'fg_latencia': keep(full['fg_latencia']),
        'fg_banda_interface': keep(full['fg_banda_interface']),
        'fg_banda_rota': keep(full['fg_banda_rota']),
        'dim_rota': keep(full['dim_rota']),
        'view': view,
        'name': name,
        'label_of_route': {route: i + 1 for i, route in enumerate(routes)},
    }
    result['topologia'] = {**full['topologia'],
                           'rotas': {r: full['topologia']['rotas'][r] for r in routes}}

    folder = os.path.join(store_root, name)
    result['folder'] = folder
    if persist:
        fs.exportar_csv(result['fg_latencia'], result['fg_banda_interface'],
                        result['fg_banda_rota'], view, result['dim_rota'], folder)
        metadata = {
            'source': source,
            'routes': routes,
            'label_of_route': result['label_of_route'],
            'built_by': 'feature_store/build_route_subset.py',
            'alignment_offset_s': int(full['alinhamento']['offset_s']),
        }
        with open(os.path.join(folder, 'subset.json'), 'w', encoding='utf-8') as file:
            json.dump(metadata, file, indent=2)
            file.write('\n')

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Build the feature store of a subset of the routes of a dataset.')
    parser.add_argument('source', nargs='?', help='original dataset, e.g. D3')
    parser.add_argument('routes', nargs='*', help="routes to keep: 'h11_h61' or route number '1'")
    parser.add_argument('--name', help='name of the store folder (default: <source>_r<numbers>)')
    parser.add_argument('--known', action='store_true',
                        help=f'build every predefined subset: {sorted(KNOWN_SUBSETS)}')
    parser.add_argument('--datasets-root', default=DATASETS_ROOT)
    parser.add_argument('--store-root', default=STORE_ROOT)
    args = parser.parse_args(argv)

    jobs = []
    if args.known:
        jobs += [(source, routes, name) for name, (source, routes) in KNOWN_SUBSETS.items()]
    if args.source:
        jobs.append((args.source, args.routes, args.name))
    if not jobs:
        parser.error('give a source dataset and its routes, or --known')

    for source, routes, name in jobs:
        result = build_route_subset(source, routes, name, args.datasets_root, args.store_root)
        view = result['view']
        labels = view.groupby('ts_epoch').melhor_rota.first().dropna().astype(int)
        shares = (labels.value_counts(normalize=True).sort_index() * 100).round(2).to_dict()
        print(f"{result['name']}: {source} routes {sorted(result['label_of_route'])} -> "
              f"{result['folder']} | {view.ts_epoch.nunique()} instants | "
              f"label share (%) {shares}")


if __name__ == '__main__':
    main()
