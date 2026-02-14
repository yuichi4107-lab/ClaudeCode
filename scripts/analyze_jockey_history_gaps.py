from nankan_predictor.storage.repository import Repository


def main():
    repo = Repository()
    from_date = "2023-01-01"
    to_date = "2026-02-12"

    entries = repo.get_entries_in_range(from_date, to_date)
    # filter valid jockey ids
    entries = entries[entries["jockey_id"].notna()]
    total_entries = len(entries)

    # earliest race_date per jockey
    first_dates = entries.groupby("jockey_id")["race_date"].min()

    jockeys_no_prior = set()
    for jockey_id, first_date in first_dates.items():
        stats = repo.get_jockey_stats(jockey_id, before_date=first_date)
        if len(stats) == 0:
            jockeys_no_prior.add(jockey_id)

    num_jockeys = len(first_dates)
    num_jockeys_no_prior = len(jockeys_no_prior)

    entries_with_no_prior = entries[entries["jockey_id"].isin(jockeys_no_prior)]
    pct_entries_no_prior = len(entries_with_no_prior) / total_entries if total_entries else 0

    print(f"Jockeys total: {num_jockeys}")
    print(f"Jockeys with no prior finished entries before their first recorded race: {num_jockeys_no_prior} ({num_jockeys_no_prior/num_jockeys:.1%})")
    print(f"Entries affected: {len(entries_with_no_prior)} / {total_entries} ({pct_entries_no_prior:.1%})")


if __name__ == '__main__':
    main()
