"""Optimize betting strategy: grid-search over top_n and probability thresholds.

Usage: python scripts/optimize_strategy.py --from-date 2023-01-01 --model-name nankan_v1
"""
import argparse
import itertools
import pandas as pd

from nankan_predictor.storage.repository import Repository
from nankan_predictor.features.builder import FeatureBuilder
from nankan_predictor.model.predictor import ModelPredictor


def simulate(predictions_df: pd.DataFrame, repo: Repository) -> dict:
    bets = []
    for _, row in predictions_df.iterrows():
        race_id = row['race_id']
        first = int(row['first_horse_number'])
        second = int(row['second_horse_number'])
        payout = repo.get_exacta_payout(race_id, first, second)
        hit = payout is not None and payout > 0
        bets.append({'race_id': race_id, 'hit': hit, 'payout': payout / 100.0 if hit else 0.0})
    df = pd.DataFrame(bets)
    invested = len(df)
    returned = df['payout'].sum()
    hits = int(df['hit'].sum())
    return {
        'total_races': invested,
        'hits': hits,
        'hit_rate': hits / invested if invested else 0.0,
        'total_invested': invested,
        'total_returned': returned,
        'roi': (returned - invested) / invested if invested else 0.0,
    }


def build_predictions_for_config(repo, builder, predictor, entries_df, top_n):
    all_combos = []
    for race_id, group in entries_df.groupby('race_id'):
        X_race = builder.build_prediction_rows(race_id, group.to_dict('records'), group.iloc[0].to_dict())
        combos = predictor.predict_exacta(X_race, top_n=top_n)
        combos['race_id'] = race_id
        all_combos.append(combos)
    if not all_combos:
        return pd.DataFrame()
    return pd.concat(all_combos, ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-date', required=True)
    parser.add_argument('--model-name', default='nankan_v1')
    args = parser.parse_args()

    repo = Repository()
    builder = FeatureBuilder(repo)
    predictor = ModelPredictor(args.model_name)

    from_date = args.from_date
    to_date = pd.Timestamp.now().strftime('%Y-%m-%d')

    entries_df = repo.get_entries_in_range(from_date, to_date)
    if len(entries_df) == 0:
        print('No evaluation data')
        return

    top_ns = [1, 3, 5, 10]
    thresholds = [0.0, 0.0005, 0.001, 0.0025, 0.005, 0.01]

    results = []
    # Precompute predictions per top_n
    pred_cache = {}
    for top_n in top_ns:
        print(f'Building predictions for top_n={top_n} ...')
        pred_cache[top_n] = build_predictions_for_config(repo, builder, predictor, entries_df, top_n)

    for top_n, thresh in itertools.product(top_ns, thresholds):
        preds = pred_cache[top_n]
        if preds.empty:
            continue
        # filter by threshold
        selected = preds[preds['exacta_prob'] >= thresh]
        if len(selected) == 0:
            # no bets
            metric = {'total_races': 0, 'roi': 0.0, 'hits': 0}
        else:
            metric = simulate(selected, repo)
        metric.update({'top_n': top_n, 'threshold': thresh, 'bets': len(selected)})
        results.append(metric)

    df = pd.DataFrame(results)
    df = df.sort_values('roi', ascending=False).reset_index(drop=True)
    print('\nBest strategies:')
    print(df.head(10).to_string(index=False))


if __name__ == '__main__':
    main()
