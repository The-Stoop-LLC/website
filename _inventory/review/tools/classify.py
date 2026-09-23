"""Shared classification of the Drive inventory: finished vs raw, dedupe keys."""
import json, re, collections
R = json.load(open(__import__('os').path.join(__import__('os').path.dirname(__file__), '../../files.json')))
byid = {r['id']: r for r in R}
RAW_DIR = re.compile(r"\b(raw|dump|b-?roll|a-?roll|cam [abc]\b|iphone|mike'?s footage|timeline clips|colou?red clips|color graded|all clips|audio|test shoot|lobby activities|time-?lapse|provided by client|provide by client|assets from q|jeanette|mario media|jared photos|photo examples|drone footage examples)", re.I)
CAM_NAME = re.compile(r"^(copy of )?(c\d{4}|dji_|img_|mvi_|mov_\d|dsc|gx\d|gh\d|gopr|a\d{3}_|pxl_|vid_|flow_vid|\d{8}_|mah\d|clip\d|p\d{7}|trim\.|_dsc|raw\b|fx3\d|rpreplay|[0-9a-f]{8}-[0-9a-f]{4}-|[0-9a-f]{32}|\d{6,}_)", re.I)
CLIP_NAME = re.compile(r"(_v\d-\d{4}|^v\d-\d{4}_|\D\d{8}\.\w+$|\ba ?roll\b|\bb ?roll\b|^drone (clip|vertical) \d|color grade|^timeline)", re.I)
def anc_names(r): return [byid[a]['name'] for a in r['ancestors'] if a in byid]
def rel_path(r): return '/'.join(anc_names(r)[2:])
def raw_folder(r): return bool(RAW_DIR.search(rel_path(r)))
def is_raw_video(r):
    return raw_folder(r) or bool(CAM_NAME.match(r['name'])) or bool(CLIP_NAME.search(r['name']))
ASPECT = re.compile(r"[\s_\-]*\(?(?<!\d)(16|9|4|1)\s*x\s*(9|16|5|1|19)(?!\d)\)?", re.I)
VARIANT = re.compile(r"\b(with|no|without|and)\s+(logos?|text|music)\b|\b(logos?|text)\s+(and|no)\s+(logos?|text)\b|\bcopy of\b|\(\d\)|_\d$|\brevised\b|\bfinal\b|\bupdated\b|\bno logos?\b|\bwith logos?\b|\blogo\b", re.I)
def dedupe_key(r):
    stem = re.sub(r"\.\w+$", "", r['name']).lower()
    stem = ASPECT.sub(" ", stem)
    stem = VARIANT.sub(" ", stem)
    stem = re.sub(r"[^a-z0-9]+", " ", stem).strip()
    return stem, round((r['dur'] or 0) / 2)

def finished_groups():
    vids = [r for r in R if r['kind'] == 'video' and not is_raw_video(r)]
    groups = collections.defaultdict(list)
    for r in vids:
        groups[dedupe_key(r)].append(r)
    def rank(r):
        n = r['name'].lower()
        return (0 if re.search(r"16\s*x\s*9", n) else 1, 'copy of' in n, len(r['path']), n)
    return {k: sorted(g, key=rank) for k, g in groups.items()}
