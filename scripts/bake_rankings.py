#!/usr/bin/env python3
"""Bake neighborhood ranks from the companion "Every neighborhood, ranked" project.

Reads that project's rankings.json (197 residential NTA2020 areas x 63 metrics)
and emits docs/data/rankings.json holding, per neighborhood, its rank in each
category — the position, not a score. The map joins on NTA2020 code.

Rank logic mirrors computeRanks() in the rankings site exactly: sort descending
by value (rank 1 = highest), competition ranking for ties (1, 2, 2, 4), and a
per-metric ranked count, because a few categories have fewer than 197 values.

Metric metadata (label, topic, format, source, caveat) is copied from the M
table in the rankings site so the two never drift apart in wording.

Run from the project root: python3 scripts/bake_rankings.py
"""
import json, os, re, sys, datetime

SRC_DIR = os.environ.get('RANKINGS_DIR', '/Users/joshgreenman/Experiments/nyc-nta-rankings')
SRC_JSON = os.path.join(SRC_DIR, 'docs', 'rankings.json')
SRC_HTML = os.path.join(SRC_DIR, 'docs', 'index.html')
OUT = 'docs/data/rankings.json'
SITE = 'https://joshgreenman1973.github.io/nyc-nta-rankings/'


def parse_metrics(html):
    """Pull the M table (id, group, label, fmt, source, note) out of the rankings site.

    Rows reference string constants (ACS = "Census ACS 2020-2024") rather than
    repeating the literal, so resolve those first.
    """
    consts = dict(re.findall(r'^const ([A-Z][A-Z0-9_]*) = ("(?:[^"\\]|\\.)*");', html, re.M))
    block = html[html.index('const M = ['):html.index('const BOROS')]
    for name, lit in consts.items():
        block = re.sub(rf'(?<=[,\[])\s*{name}\s*(?=[,\]])', lit, block)
    rows = re.findall(r'^\s*\[(".*?")\],?\s*$', block, re.M)
    out = []
    for r in rows:
        parts = json.loads('[' + r + ']')
        if len(parts) != 6:
            sys.exit(f'unexpected metric row shape: {parts[:2]}')
        mid, group, label, fmt, source, note = parts
        out.append({'id': mid, 'label': label, 'group': group,
                    'fmt': fmt, 'src': source, 'note': note})
    return out


def parse_topcode(html):
    m = re.search(r'const TOPCODE = \{(.*?)\};', html, re.S)
    return {k: int(v) for k, v in re.findall(r'(\w+)\s*:\s*(\d+)', m.group(1))} if m else {}


def main():
    if not os.path.exists(SRC_JSON):
        sys.exit(f'rankings source not found: {SRC_JSON} (set RANKINGS_DIR)')
    src = json.load(open(SRC_JSON))
    html = open(SRC_HTML).read()
    metrics = parse_metrics(html)
    topcode = parse_topcode(html)
    areas = src['areas']
    if not areas:
        sys.exit('rankings source has no areas — refusing to write an empty file')

    ids = [m['id'] for m in metrics]
    missing = [i for i in ids if not any(i in a['values'] for a in areas)]
    if missing:
        sys.exit(f'metrics defined but absent from the data: {missing}')

    # rank each metric: descending by value, competition ties, like the source site
    ranks = {a['code']: [None] * len(ids) for a in areas}
    counts = []
    for col, mid in enumerate(ids):
        vals = sorted((a for a in areas if a['values'].get(mid, {}).get('v') is not None),
                      key=lambda a: a['values'][mid]['v'], reverse=True)
        prev, prev_rank = None, 0
        for i, a in enumerate(vals):
            v = a['values'][mid]['v']
            rank = prev_rank if (prev is not None and v == prev) else i + 1
            ranks[a['code']][col] = rank
            prev, prev_rank = v, rank
        counts.append(len(vals))

    names = {a['code']: a['name'] for a in areas}
    values = {a['code']: [a['values'].get(m, {}).get('v') for m in ids] for a in areas}

    out = {
        'built': datetime.date.today().isoformat(),
        'source_built': src.get('built'),
        'site': SITE,
        'areas': len(areas),
        'metrics': [[m['id'], m['label'], m['group'], m['fmt'], m['src'], m['note']] for m in metrics],
        'n': counts,
        'topcode': topcode,
        'names': names,
        'ranks': ranks,
        'values': values,
    }
    json.dump(out, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
    kb = os.path.getsize(OUT) / 1024
    print(f'{len(areas)} neighborhoods x {len(ids)} categories -> {OUT} ({kb:.0f} KB)')
    print(f'source built {src.get("built")}; categories ranked over '
          f'{min(counts)}-{max(counts)} neighborhoods')


if __name__ == '__main__':
    main()
