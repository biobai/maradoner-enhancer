"""Run independently rebuilt donor-exclusion configurations, never inflate n."""
import argparse
from pathlib import Path
import pandas as pd
from me.io import config, read_table, write_table, write_json
from me.validate import load_inputs
from me.pipeline import pipeline


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--configs', nargs='+', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    configs = [config(x) for x in args.configs]
    if any(not c.get('heldout_donor') for c in configs):
        raise ValueError('Every fold requires heldout_donor and rebuilt links')
    if len({c['output'] for c in configs}) != len(configs):
        raise ValueError('Fold output paths must be distinct')
    if len({c['heldout_donor'] for c in configs}) != len(configs):
        raise ValueError('Duplicate held-out donors')
    for c in configs:
        load_inputs(c)
    tables = []
    out = Path(args.output)
    write_json({'status':'running', 'folds':args.configs}, out/'status.json')
    try:
        for c in configs:
            pipeline(c)
            x = read_table(Path(c['output'])/'evaluate/condition_summary.tsv')
            x['heldout_build_donor'] = c['heldout_donor']
            x['role'] = 'robustness_not_independent_biological_replicate'
            tables.append(x)
        write_table(pd.concat(tables,ignore_index=True), out/'fold_metrics.tsv')
        write_json({'status':'success','folds':args.configs,'inferential_pooling':False}, out/'status.json')
    except Exception as e:
        (out/'fold_metrics.tsv').unlink(missing_ok=True)
        write_json({'status':'failed','error':str(e)},out/'status.json')
        raise


if __name__ == '__main__':
    main()
