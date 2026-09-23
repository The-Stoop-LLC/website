"""Group the contact sheets into one review packet per client."""
import json, os, sys, collections
sys.path.insert(0, os.path.dirname(__file__))
from classify import R, byid, anc_names, rel_path, is_raw_video, raw_folder, finished_groups, dedupe_key

INV = '/home/user/website/_inventory'
OUT = os.path.join(os.path.dirname(__file__), 'packets')
CLIENT = {
    'Iron 24 - Corporate': 'Iron 24', 'Iron 24 - Influencers': 'Iron 24', 'Iron 24 - SAM': 'Iron 24',
    'Iron 24': 'Iron 24', 'CASE SPECIFIC MEAL PREP': 'CSMP', 'DR. TEA': 'Dr. Tea',
    'X SHADYSIDE': 'X Shadyside', 'Union Trust Building': 'Union Trust Building', 'SXP': 'SXP',
    'Sylvan Gardens': 'Sylvan Gardens', 'Photos 2021': 'Sylvan Gardens', 'MFPAA': 'MFPAA',
    'Take a Nurse': 'Take a Nurse', 'Castle Rock Tax Services': 'Castle Rock Tax Services',
    'Chad Isaiah Photography': 'Chad Isaiah Photography',
}


def client_of(r):
    n = anc_names(r) + ([r['name']] if r['kind'] == 'folder' else [])
    for part in n:
        if part in CLIENT:
            return CLIENT[part]
    return 'Other'


def site_use(r):
    pages = sorted({p for p in r['on_site'] if p.endswith('.html')} | set(r['in_gallery']))
    if 'scripts/hero_loop.json' in r['on_site']:
        pages.append('homepage hero loop')
    return pages


def main():
    index = json.load(open(f'{INV}/sheets/index.json'))
    groups = finished_groups()
    rep = {g[0]['id']: g for g in groups.values()}
    packets = collections.defaultdict(lambda: {'videos': [], 'mosaics': [], 'raw_video_folders': []})
    for vid, res in index['videos'].items():
        g = rep.get(vid, [byid[vid]])
        r = g[0]
        packets[client_of(r)]['videos'].append({
            'id': vid, 'name': r['name'], 'folder': rel_path(r), 'dur': r['dur'], 'w': r['w'], 'h': r['h'],
            'sheet': (f"{INV}/{res['sheet']}" if 'sheet' in res else None), 'error': res.get('error'),
            'frame_times': res.get('times'),
            'variants': [{'id': x['id'], 'name': x['name'], 'folder': rel_path(x)} for x in g[1:]],
            'on_site': sorted({p for x in g for p in site_use(x)}),
        })
    for fid, sheets in index['mosaics'].items():
        f = byid[fid]
        kids = [r for r in R if r['parent'] == fid and r['kind'] in ('image', 'video')]
        entry = {
            'folder_id': fid, 'folder': rel_path(f) + '/' + f['name'],
            'raw': all(raw_folder(k) or (k['kind'] == 'video' and is_raw_video(k)) for k in kids),
            'items_in_folder': len(kids),
            'on_site': sorted({p for k in kids for p in site_use(k)}),
            'sheets': [{'path': f"{INV}/{s['sheet']}",
                        'cells': [{'n': c['n'], 'id': c['id'], 'name': c['name'], 'kind': c['kind'],
                                   'on_site': bool(site_use(byid[c['id']]))} for c in s['cells']]}
                       for s in sheets],
        }
        packets[client_of(f)]['mosaics'].append(entry)
    os.makedirs(OUT, exist_ok=True)
    for c, p in packets.items():
        p['videos'].sort(key=lambda v: v['folder'])
        p['mosaics'].sort(key=lambda m: m['folder'])
        name = c.lower().replace(' ', '-').replace('.', '')
        json.dump(p, open(f'{OUT}/{name}.json', 'w'), indent=1)
        n_sheets = sum(len(m['sheets']) for m in p['mosaics'])
        print(f"{c:28s} videos {len(p['videos']):3d} (errors {sum(1 for v in p['videos'] if v['error'])})"
              f"  mosaic folders {len(p['mosaics']):3d} sheets {n_sheets:3d}")


if __name__ == '__main__':
    main()
