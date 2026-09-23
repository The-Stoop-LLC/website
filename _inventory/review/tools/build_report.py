"""Assemble the Drive content map: merge reviews with the inventory, pick the
stills, and write report/index.html plus report/img/*.webp."""
import collections, glob, html, json, os, re, shutil, sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from classify import R, byid, rel_path, is_raw_video, finished_groups  # noqa: E402
from packets import client_of, site_use  # noqa: E402

INV = '/home/user/website/_inventory'
OUT = os.path.join(HERE, 'report')
PICKS_DIR = f'{INV}/picks'
MAX_STILLS = 236
# client-supplied, stock or private material: never recommend it as The Stoop's work
NOT_OURS = re.compile(r'provided? by client|assets from q|jeanette|example content|media release|photo examples|drone footage examples', re.I)

CLIENTS = [
    # name, anchor, case-study page, one line
    ('Union Trust Building', 'utb', None, 'Historic downtown office building. Social media management, 2023 to 2025.'),
    ('Take a Nurse', 'take-a-nurse', 'work/take-a-nurse.html', 'In-home nursing brand. 2026 brand shoot, hero film and identity.'),
    ('Sylvan Gardens', 'sylvan', 'work/sylvan-gardens.html', 'Landscaping and hardscaping. Organic social, project shoots, crew spotlights.'),
    ('Iron 24', 'iron-24', 'work/iron-24.html', 'Gym brand. Corporate content blocks, South Hills franchise, influencers.'),
    ('X Shadyside', 'x-shadyside', 'work/x-shadyside.html', 'Luxury apartments. Influencer ad campaigns, reels, Lucid Juice partnership.'),
    ('MFPAA', 'mfpaa', 'work/mfpaa.html', 'Nonprofit EMS. Subscription and capital donation campaigns.'),
    ('CSMP', 'csmp', 'work/csmp.html', 'Case Specific Meal Prep. Monthly content calendars, 2022 to 2023.'),
    ('Dr. Tea', 'dr-tea', 'work/dr-tea.html', 'Bubble tea shop. Influencer campaign content.'),
    ('SXP', 'sxp', 'work/sxp.html', 'Fitness brand. Website video and social campaign.'),
    ('Chad Isaiah Photography', 'chad-isaiah', None, 'Headshot photographer. Two paid social campaigns.'),
    ('Castle Rock Tax Services', 'castle-rock', None, 'Tax practice. Letterhead design.'),
]
CLIENT_KEY = {  # packets.client_of names -> display names
    'CSMP': 'CSMP', 'Iron 24': 'Iron 24', 'Dr. Tea': 'Dr. Tea', 'SXP': 'SXP', 'Sylvan Gardens': 'Sylvan Gardens',
    'Union Trust Building': 'Union Trust Building', 'X Shadyside': 'X Shadyside', 'MFPAA': 'MFPAA',
    'Take a Nurse': 'Take a Nurse', 'Castle Rock Tax Services': 'Castle Rock Tax Services',
    'Chad Isaiah Photography': 'Chad Isaiah Photography',
}
PLACE_LABEL = {'hero-loop': 'Hero loop', 'case-study': 'Case study', 'gallery': 'Gallery', 'cover': 'Cover image'}
BLOG_TITLES = {
    '15-fitness-influencers-267k-views': '15 Fitness Influencers',
    'anatomy-of-a-47k-nonprofit-campaign': '$47K Nonprofit Campaign',
    'content-production-at-scale-gym': '81 Assets for a Gym Brand',
    'cross-brand-partnerships-guide': 'Cross-Brand Partnerships',
    'how-we-generated-480k-views-for-dr-tea': '480K Views for Dr. Tea',
    'influencer-marketing-roi-guide': 'Influencer ROI Guide',
    'organic-social-growth-landscaping': 'Organic Social for a Landscaper',
    'themed-content-calendar-food-brands': 'Content Calendars for Food Brands',
}
SERVICE_TITLES = {
    'content-development': 'Content Development', 'organic-social': 'Organic Social',
    'influencer-marketing': 'Influencer Marketing', 'influencer-coaching': 'Influencer Coaching',
    'digital-advertising': 'Digital Advertising', 'design-branding': 'Design & Branding',
    'website-design': 'Website Design', 'automation-ops': 'Automation & Ops',
}


def place_label(p):
    if p.startswith('service:'):
        return SERVICE_TITLES.get(p[8:], p[8:])
    if p.startswith('blog:'):
        return 'Blog: ' + BLOG_TITLES.get(p[5:], p[5:])
    return PLACE_LABEL.get(p, p)


def place_group(p):
    return 'service' if p.startswith('service:') else 'blog' if p.startswith('blog:') else p


def esc(s):
    return html.escape(str(s or ''), quote=True)


def load_reviews():
    videos, folders, takeaways = {}, {}, collections.defaultdict(list)
    for f in sorted(glob.glob(f'{HERE}/reviews/*.json')):
        d = json.load(open(f))
        chunk = json.load(open(f"{HERE}/chunks/{os.path.basename(f)}"))
        cv = {v['id']: v for v in chunk['videos']}
        cm = {m['folder_id']: m for m in chunk['mosaics']}
        for v in d.get('videos', []):
            if v.get('id') in cv:
                videos[v['id']] = dict(v, _chunk=cv[v['id']])
        for fo in d.get('folders', []):
            if fo.get('folder_id') in cm:
                cells = {c['id']: c for s in cm[fo['folder_id']]['sheets'] for c in s['cells']}
                fo['best'] = [b for b in fo.get('best', []) if b.get('id') in cells]
                folders[fo['folder_id']] = dict(fo, _chunk=cm[fo['folder_id']])
        if d.get('takeaways'):
            takeaways[os.path.basename(f)[:-5]] = d['takeaways']
    return videos, folders, takeaways


def sheet_crop(item):
    """Fallback still cut from a contact sheet."""
    if item['kind'] == 'video' and item.get('sheet'):
        im = Image.open(item['sheet'])
        W, H = im.size
        cols = 8 if W == 1920 else 4
        rows = 1 if cols == 8 else 2
        cw, ch = W // cols, (H - 34) // rows
        i = item.get('best_frame') or 0
        x, y = (i % cols) * cw, 34 + (i // cols) * ch
        return im.crop((x, y + 22, x + cw, y + ch))
    if item.get('mosaic'):
        path, idx = item['mosaic']
        im = Image.open(path)
        x, y = (idx % 8) * 200, (idx // 8) * 200
        cell = im.crop((x + 2, y + 2, x + 198, y + 198))
        bg = Image.new(cell.mode, cell.size, (24, 24, 24))
        from PIL import ImageChops
        box = ImageChops.difference(cell, bg).convert('L').point(lambda v: 255 if v > 12 else 0).getbbox()
        return cell.crop(box) if box else cell
    return None


def main():
    videos, folders, takeaways = load_reviews()
    groups = finished_groups()
    rep_of = {}
    for g in groups.values():
        for x in g:
            rep_of[x['id']] = g[0]['id']

    # ------------------------------------------------------------ per client
    data = {c[0]: {'name': c[0], 'anchor': c[1], 'page': c[2], 'line': c[3], 'items': [], 'folders': [],
                   'replace': [], 'keep': [], 'stats': collections.Counter(), 'pages': collections.Counter()}
            for c in CLIENTS}
    for r in R:
        c = CLIENT_KEY.get(client_of(r))
        if not c:
            continue
        s = data[c]['stats']
        if r['kind'] == 'folder':
            s['folders'] += 1
            continue
        s['bytes'] += r['size']
        if r['kind'] == 'video':
            s['raw_videos' if is_raw_video(r) else 'finished_videos'] += 1
            s['video_s'] += r['dur'] or 0
        elif r['kind'] == 'image':
            s['images'] += 1
        pages = site_use(r)
        if pages:
            s['on_site'] += 1
            for p in pages:
                data[c]['pages'][p] += 1
    for c in data.values():
        c['stats']['distinct_finished'] = 0
    for g in groups.values():
        c = CLIENT_KEY.get(client_of(g[0]))
        if c:
            data[c]['stats']['distinct_finished'] += 1

    def drive_url(fid):
        return f'https://drive.google.com/file/d/{fid}/view'

    for vid, v in videos.items():
        ch = v['_chunk']
        c = CLIENT_KEY.get(client_of(byid[vid]))
        if not c:
            continue
        times = ch.get('frame_times') or [0]
        bf = v.get('best_frame') if isinstance(v.get('best_frame'), int) and 0 <= v.get('best_frame') < len(times) else len(times) // 2
        item = {
            'id': vid, 'kind': 'video', 'name': ch['name'], 'folder': ch['folder'], 'score': v.get('score') or 0,
            'type': v.get('type'), 'orientation': v.get('orientation'), 'summary': v.get('summary'),
            'placements': v.get('placements') or [], 'hero_moment': v.get('hero_moment'), 'issues': v.get('issues') or [],
            'why': v.get('why'), 'dur': ch.get('dur'), 'on_site': ch.get('on_site') or [], 'sheet': ch.get('sheet'),
            'best_frame': bf, 't': times[bf], 'variants': ch.get('variants') or [], 'url': drive_url(vid),
            'w': ch.get('w'), 'h': ch.get('h'),
        }
        if item['on_site']:
            (data[c]['keep'] if item['score'] >= 4 else data[c]['replace'] if item['score'] <= 2 else []).append(item)
        else:
            data[c]['items'].append(item)
    for fid, fo in folders.items():
        ch = fo['_chunk']
        c = CLIENT_KEY.get(client_of(byid[fid]))
        if not c:
            continue
        kids = [r for r in R if r['parent'] == fid and r['kind'] in ('image', 'video')]
        data[c]['folders'].append({
            'id': fid, 'path': ch['folder'], 'raw': ch['raw'], 'score': fo.get('score') or 0, 'summary': fo.get('summary'),
            'issues': fo.get('issues') or [], 'n_img': sum(k['kind'] == 'image' for k in kids),
            'n_vid': sum(k['kind'] == 'video' for k in kids), 'on_site': sum(bool(site_use(k)) for k in kids),
            'url': f'https://drive.google.com/drive/folders/{fid}',
        })
        cells = {}
        for s in ch['sheets']:
            for i, cell in enumerate(s['cells']):
                cells[cell['id']] = (s['path'], i, cell)
        for b in fo.get('best', []):
            if (b.get('score') or 0) < 4:
                continue
            path, idx, cell = cells[b['id']]
            r = byid[b['id']]
            if cell.get('on_site'):
                continue
            data[c]['items'].append({
                'id': b['id'], 'kind': r['kind'], 'name': r['name'], 'folder': ch['folder'], 'score': b['score'],
                'type': 'clip' if r['kind'] == 'video' else 'photo', 'summary': b.get('why'),
                'placements': b.get('placements') or [], 'issues': [], 'dur': r.get('dur'), 'on_site': [],
                'mosaic': (path, idx), 't': (r.get('dur') or 0) / 2, 'url': drive_url(b['id']), 'raw_folder': ch['raw'],
                'w': r.get('w'), 'h': r.get('h'),
            })
    def same_file(it):  # the same photo copied into several folders
        r = byid[it['id']]
        return re.sub(r'^copy of ', '', r['name'].lower()), r['size']
    on_site_keys = {same_file({'id': r['id']}) for r in R if r['kind'] in ('image', 'video') and site_use(r)}
    for c in data.values():
        c['items'].sort(key=lambda it: (-it['score'], 'hero-loop' not in it['placements'], it['kind'] != 'video', it['name']))
        seen_keys, kept = set(), []
        for it in c['items']:
            k = same_file(it)
            if k in seen_keys or k in on_site_keys or NOT_OURS.search(it['folder']):
                continue
            seen_keys.add(k)
            kept.append(it)
        c['items'] = kept
        c['folders'].sort(key=lambda f: f['path'].lower())
        c['takeaways'] = [t for k, t in sorted(takeaways.items())
                          if k.startswith(c['anchor'].replace('utb', 'union-trust-building').replace('sylvan', 'sylvan-gardens')
                                          .replace('chad-isaiah', 'small').replace('castle-rock', 'small')
                                          .replace('dr-tea', 'small').replace('sxp', 'small'))]

    # ------------------------------------------------------- choose stills
    shown = []
    per_client_cap = {'Union Trust Building': 28, 'Take a Nurse': 20, 'Sylvan Gardens': 36, 'Iron 24': 26,
                      'X Shadyside': 26, 'MFPAA': 18, 'CSMP': 24}
    for c in data.values():
        cap = per_client_cap.get(c['name'], 12)
        ready = [it for it in c['items'] if os.path.exists(f"{PICKS_DIR}/{it['id']}.webp")]
        c['cards'] = ready[:cap]
        picked = {it['id'] for it in c['cards']}
        c['more'] = [it for it in c['items'] if it['id'] not in picked]
        shown += c['cards'] + c['replace'] + c['keep'][:6]
    seen, stills = set(), []
    for it in shown:
        if it['id'] not in seen:
            seen.add(it['id'])
            stills.append(it)
    stills = stills[:MAX_STILLS]
    json.dump([{'id': s['id'], 't': round(s.get('t') or 0, 2)} for s in stills if s['kind'] in ('video', 'image')],
              open(f'{HERE}/picks.json', 'w'))
    still_ids = {s['id'] for s in stills}

    os.makedirs(f'{OUT}/img', exist_ok=True)
    for f in glob.glob(f'{OUT}/img/*'):
        os.remove(f)
    have = 0
    for s in stills:
        dest = f"{OUT}/img/{s['id']}.webp"
        src = f"{PICKS_DIR}/{s['id']}.webp"
        if os.path.exists(src):
            shutil.copy(src, dest)
            have += 1
        else:
            im = sheet_crop(s)
            if im:
                im.convert('RGB').save(dest, 'WEBP', quality=75)
    print(f'stills: {len(stills)} ({have} from Drive, rest cropped from sheets)')

    json.dump({k: {kk: vv for kk, vv in v.items() if kk not in ('stats', 'pages')} | {
        'stats': dict(v['stats']), 'pages': dict(v['pages'])} for k, v in data.items()},
        open(f'{HERE}/report_data.json', 'w'), indent=1, default=str)
    return data, still_ids


if __name__ == '__main__':
    data, still_ids = main()
    for c in data.values():
        print(f"{c['name']:26s} unused 4-5: {len(c['items']):3d}  cards {len(c['cards']):2d}  keep {len(c['keep']):2d}  "
              f"replace {len(c['replace']):2d}  folders {len(c['folders']):3d}")


# ================================================================== render

TOTALS = {'videos': 2618, 'hours': 26.8, 'images': 15025, 'folders': 910, 'tb': 1.07, 'on_site': 131}

FIXES = [  # verified against the sheets where noted; each names the live page
    ('MFPAA', 'work/mfpaa.html', 'Two ads on the case study have typos baked into the video: "DONT" in the 7|60 spot and "THATS" in It\'s Your Job.'),
    ('CSMP', 'work/csmp.html', 'The two CSMP Spotlight videos on the case study are static talking heads (one has grocery bags in frame). The June 2023 4K reels, Hibachi and Mediterranean Chicken Wrap, are stronger replacements.'),
    ('Iron 24', 'services/influencer-marketing.html', 'The Ankle Strap clip on the influencer-marketing page is a mobility demo with no influencer in it. Swap in an X Shadyside influencer reel or Group Edit Jason 1.'),
    ('Sylvan Gardens', 'work/sylvan-gardens.html', 'Three clips on the site (Sylvan Logo on Truck, Spring CleanUp, Team B-Roll) are 540p phone footage. The Friend backyard photos and the 4K drone work are a better face for the page.'),
    ('X Shadyside', 'work/x-shadyside.html', 'Several influencer reels on the page show other brands (TROY on dumbbells; Victoria Sport and Alphalete apparel). Worth a second look before featuring them higher.'),
    ('MFPAA', 'homepage hero loop', 'The hero loop uses the final 60 s spot, which has lower-thirds and stats baked in. The textless "60 Sec (1 minute base)" file is a cleaner source for the same shots.'),
    ('Take a Nurse', 'work/take-a-nurse.html', 'The case study shows only brand design. The June 2026 shoot has a 60 s founder film, a 30 s textless loop and 1,008 retouched photos, none on the page.'),
]
HEADS_UP = [
    'Iron 24: "Cold Plunge With Music.mp4" actually contains the red-light video. There is no cold-plunge cut with music.',
    'CSMP: "Grain Bowl.mp4" is a copy of the tomato soup video, and "Pulled Pork Reel (Scott)" duplicates "No Slack All Hustle".',
    'CSMP template graphics carry typos ("CLIENT TESTIMONAL", "INGREDIANT", "BROCOLLI", "FRIJOLAS") and leftover "INSERT LINK HERE". Keep them off the site.',
    'X Shadyside: the fall promo story reads "your 12 month of membership is FREE" (should be 12th). One Peyton story is a screen recording of a private DM thread.',
    'Castle Rock letterhead still has "(Address Line)" placeholders in the footer.',
    'Rights to check before posting: the CSMP "Mario Media" footage is a third-party test shoot, the best MFPAA fleet photos were shot by the client, and the UTB 2025 cocktail slides are Eddie V\'s own brand assets.',
    'Take a Nurse: "Jason/Touched Photos" is a second copy of "Touched Photos" with different file IDs. Use the main folder.',
    'MFPAA: "Captain Headshots 1.21.26" duplicates "Chief Headshots".',
]
UNREACHABLE = [
    ('85 Crawford Client Testimonial (V1 to V4)', 'Sylvan Gardens', 'Your My Drive, top level. Feb 2025, about 183 MB each.',
     'A finished homeowner testimonial, the only one in the Drive. Move V4 into the Sylvan Gardens folder in the shared drive so it can be embedded and reviewed.'),
    ('Assets for Union Trust', 'Union Trust Building', 'Shared with you from UTB. 1 promo video, 17 social graphics, 14 retouched photos.',
     'The Cabinet of Dr. Caligari event (Oct 2024), the most finished UTB material found. Copy it into the UTB folder before building a case study.'),
    ('Urban Nest', 'Urban Nest (no page)', 'Shared with you. 36 ad artboards, Apr to May 2023.',
     'Finished static ads for a client the site never mentions. Add to Design & Branding or Digital Advertising if the work was The Stoop\'s.'),
    ('Drone Library', 'Unknown project', 'Your My Drive. 9 raw DJI 4K clips and 16 stills, Aug to Sep 2023, 24 GB.',
     'Raw aerials, not reviewed. Worth a look for hero-loop drone shots once the project is known.'),
    ('Putt & Pour and Night Market stories', 'Post-Gazette', 'Shared with you. 3 story videos, Apr 2025.',
     'Event promos. Include only if The Stoop made them.'),
    ('SXP intro videos on work/sxp', 'SXP', 'Link-shared files outside the shared drive.',
     'Already on the site and working. Nothing to do unless the files move.'),
]
REST = [
    ('Your My Drive', [
        ('Contracts', '11 documents'), ('Price Quotes', '25 documents'), ('Meet Recordings', '53 files, 14 call recordings'),
        ('Google Meet', '12 files, 1 recording'), ('Templates', '2 documents'), ('Surveys', '4 files (2 forms)'),
        ('Job Postings', '8 documents'), ('Interns', '2 files'), ('Formative', '4 planning documents'), ('Pitt', '2 documents'),
        ('Point Park', '3 class recordings (raw)'), ('X Shadyside', '1 story video, 4 landing-page design drafts'),
        ('Top-level files', '109 files: email signatures, icons, PDFs (UTB newsletters, Sylvan analytics report, MFPAA concept deck), '
                            'copies of MFPAA spots, the 85 Crawford testimonial'),
        ('Personal', '1,763 files. Personal, not reviewed, not listed here.'),
        ('Interal Thoughts, Highlevel', 'Empty'),
    ]),
    ('Shared with you', [
        ('Brand Assets (Jack), All Docs', 'Formative Unites brand kit and business documents'),
        ('SXP, SxpContent', '12 logo files; 54 raw iPhone clips (June to July 2023)'),
        ('the platform 2025 photo gallery', '11 edited event photos (client unclear)'),
        ('AMA Pittsburgh Chapter, 2024/2025 Marquee Awards', 'Association documents'),
        ('Programs, Iron 24, Union Trust Happy Hour', 'Empty folders'),
        ('Other shares', 'Vendor uploads, influencer analytics, artist files, a game screenshot, 19 loose media files (demo reels, stock, other agencies)'),
    ]),
]


def fmt_dur(s):
    if not s:
        return ''
    s = int(round(s))
    return f'{s // 60}:{s % 60:02d}'


def card(it, still_ids, size=''):
    places = [p for p in it['placements'] if p != 'gallery'] or it['placements']
    groups = ' '.join(sorted({place_group(p) for p in it['placements']}))
    img = (f'<img loading="lazy" src="img/{esc(it["id"])}.webp" alt="{esc(it.get("summary") or it["name"])}">'
           if it['id'] in still_ids else '<div class="noimg">No preview</div>')
    orient = 'port' if (it.get('orientation') == 'portrait' or (it.get('h') and it.get('w') and it['h'] > it['w'])) else ''
    badge = f'<span class="badge">Video {fmt_dur(it.get("dur"))}</span>' if it['kind'] == 'video' else ''
    typ = (it.get('type') or '').replace('-', ' ')
    variants = it.get('variants') or []
    extra = []
    if it.get('hero_moment') and 'hero-loop' in it['placements']:
        extra.append(f'<p class="moment"><b>Hero shot</b> {esc(it["hero_moment"])}</p>')
    if it.get('issues'):
        extra.append(f'<p class="issue">{esc("; ".join(it["issues"]))}</p>')
    if variants:
        extra.append(f'<p class="variants">{len(variants) + 1} versions (sizes or logo options)</p>')
    return f'''<article class="card {size} {orient}" data-place="{groups}" data-score="{it['score']}">
  <a class="thumb" href="{esc(it['url'])}" target="_blank" rel="noopener">{img}{badge}</a>
  <div class="cbody">
    <div class="cmeta"><span class="score s{it['score']}" title="Score out of 5">{it['score']}</span><span class="ctype">{esc(typ)}</span></div>
    {f'<h4>{esc(it["name"])}</h4>' if it['kind'] == 'video' and not it.get('mosaic') else ''}
    <p class="sum{' lead' if it.get('mosaic') or it['kind'] == 'image' else ''}">{esc(it.get('summary'))}</p>
    {''.join(extra)}
    <ul class="places">{''.join(f'<li class="pl-{place_group(p)}">{esc(place_label(p))}</li>' for p in places)}</ul>
    <p class="path">{esc(it['folder'])}{'' if it['kind'] == 'video' and not it.get('mosaic') else ' / ' + esc(it['name'])}</p>
  </div>
</article>'''


def render(data, still_ids):
    clients = [data[c[0]] for c in CLIENTS]
    # start-here picks: best unused across clients, at most 2 per client
    pool = sorted((it for c in clients for it in c['items'] if it['id'] in still_ids),
                  key=lambda it: (-it['score'], 'cover' not in it['placements'], it['kind'] != 'video'))
    start, per = [], collections.Counter()
    for it in pool:
        c = CLIENT_KEY.get(client_of(byid[it['id']]))
        if per[c] < 2:
            start.append(it)
            per[c] += 1
        if len(start) == 12:
            break
    hero = [it for c in clients for it in c['items'] if 'hero-loop' in it['placements'] and it['id'] in still_ids]
    hero.sort(key=lambda it: -it['score'])

    nav = ''.join(f'<a href="#{c["anchor"]}"><span>{esc(c["name"])}</span><b>{len(c["items"])}</b></a>' for c in clients)
    out = [HEAD]
    out.append(f'''<header class="top wrap">
  <p class="eyebrow">The Stoop &middot; Google Drive audit &middot; 23 Sep 2026</p>
  <h1>Drive Content Map</h1>
  <p class="lede">Every file in the agency Drive, checked against the live site. Each finished video and photo folder was looked at and scored for how well it would sell The Stoop on the website, then matched to the page where it would do the most work.</p>
  <dl class="totals">
    <div><dt>Videos</dt><dd>{TOTALS['videos']:,}</dd><small>{TOTALS['hours']} hours</small></div>
    <div><dt>Photos</dt><dd>{TOTALS['images']:,}</dd><small>in {TOTALS['folders']} folders</small></div>
    <div><dt>Storage</dt><dd>{TOTALS['tb']} TB</dd><small>shared drive</small></div>
    <div><dt>On the site</dt><dd>{TOTALS['on_site']}</dd><small>files in use today</small></div>
    <div><dt>Unused 4s and 5s</dt><dd>{sum(len(c["items"]) for c in clients)}</dd><small>ready to place</small></div>
  </dl>
</header>
<nav class="filters" aria-label="Filter recommendations">
  <div class="wrap frow">
    <span class="flabel">Show</span>
    <button type="button" class="on" data-f="all">Everything</button>
    <button type="button" data-f="hero-loop">Hero loop</button>
    <button type="button" data-f="case-study">Case studies</button>
    <button type="button" data-f="cover">Cover images</button>
    <button type="button" data-f="service">Service pages</button>
    <button type="button" data-f="blog">Blog posts</button>
    <label class="five"><input type="checkbox" id="only5"> Only 5s</label>
  </div>
</nav>
<main class="wrap">
<section id="start" class="block">
  <div class="shead"><h2>Put these up first</h2><p>The twelve strongest unused pieces, two per client at most. Click any image to open the file in Drive.</p></div>
  <div class="grid">{''.join(card(it, still_ids) for it in start)}</div>
</section>
<section id="clients-nav" class="block">
  <div class="shead"><h2>Clients</h2><p>Number of unused pieces scored 4 or 5 for each client.</p></div>
  <div class="cnav">{nav}</div>
</section>
<section id="fix" class="block">
  <div class="shead"><h2>Fix on the live site</h2><p>Things already published that the review flagged.</p></div>
  <ol class="fixes">{''.join(f'<li><span class="who">{esc(c)}</span><span class="where">{esc(p)}</span><p>{esc(t)}</p></li>' for c, p, t in FIXES)}</ol>
  <details class="more"><summary>Other things the review turned up ({len(HEADS_UP)})</summary><ul class="notes">{''.join(f'<li>{esc(h)}</li>' for h in HEADS_UP)}</ul></details>
</section>
<section id="hero" class="block">
  <div class="shead"><h2>Hero loop candidates</h2><p>Unused clips with a clean 3 to 6 second moment and no text on screen. The time noted is where the shot starts.</p></div>
  <div class="grid small">{''.join(card(it, still_ids, 'sm') for it in hero[:16])}</div>
</section>''')

    for c in clients:
        s = c['stats']
        page = (f'<a class="pagelink" href="https://thestooppgh.com/{c["page"].replace(".html", "")}" target="_blank" rel="noopener">{esc(c["page"].replace(".html", ""))}</a>'
                if c['page'] else '<span class="nopage">No case study yet</span>')
        pages = sorted(c['pages'].items(), key=lambda kv: -kv[1])
        pages_html = ''.join(f'<li><span>{esc(p.replace(".html", ""))}</span><b>{n}</b></li>' for p, n in pages) or '<li><span>Nothing from the shared drive yet</span></li>'
        keep = ''.join(f'<li><a href="{esc(k["url"])}" target="_blank" rel="noopener">{esc(k["name"])}</a> <span class="score s{k["score"]}">{k["score"]}</span></li>' for k in c['keep'][:8])
        replace = ''.join(card(it, still_ids, 'sm') for it in c['replace'])
        more = ''.join(
            f'<tr><td><a href="{esc(it["url"])}" target="_blank" rel="noopener">{esc(it["name"])}</a></td><td><span class="score s{it["score"]}">{it["score"]}</span></td>'
            f'<td>{esc(", ".join(place_label(p) for p in it["placements"]))}</td><td class="muted">{esc(it.get("summary"))}</td></tr>'
            for it in c['more'])
        folders = ''.join(
            f'<tr><td><a href="{esc(f["url"])}" target="_blank" rel="noopener">{esc(f["path"])}</a></td>'
            f'<td class="num">{f["n_vid"] or ""}</td><td class="num">{f["n_img"] or ""}</td>'
            f'<td>{"Raw" if f["raw"] else "Edited"}</td><td><span class="score s{f["score"]}">{f["score"]}</span></td>'
            f'<td class="num">{f["on_site"] or ""}</td><td class="muted">{esc(f.get("summary"))}</td></tr>'
            for f in c['folders'])
        takeaways = ''.join(f'<p>{esc(t)}</p>' for t in c['takeaways'])
        out.append(f'''<section id="{c['anchor']}" class="client block">
  <div class="chead">
    <div><h2>{esc(c['name'])}</h2><p class="line">{esc(c['line'])}</p></div>
    {page}
  </div>
  <dl class="cstats">
    <div><dt>Finished videos</dt><dd>{s['distinct_finished']}</dd></div>
    <div><dt>Raw clips</dt><dd>{s['raw_videos']:,}</dd></div>
    <div><dt>Footage</dt><dd>{s['video_s'] / 3600:.1f} h</dd></div>
    <div><dt>Photos</dt><dd>{s['images']:,}</dd></div>
    <div><dt>Folders</dt><dd>{s['folders']}</dd></div>
    <div><dt>On the site</dt><dd>{s['on_site']}</dd></div>
  </dl>
  {f'<details class="take"><summary>Reviewer notes</summary>{takeaways}</details>' if takeaways else ''}
  <h3>Best unused</h3>
  {f'<div class="grid">{"".join(card(it, still_ids) for it in c["cards"])}</div>' if c['cards'] else '<p class="muted">Nothing unused scored 4 or 5.</p>'}
  {f'<details class="more"><summary>{len(c["more"])} more unused pieces scored 4 or 5</summary><div class="tscroll"><table><thead><tr><th>File</th><th>Score</th><th>Best for</th><th>Notes</th></tr></thead><tbody>{more}</tbody></table></div></details>' if c['more'] else ''}
  <div class="onsite">
    <div><h3>On the site now</h3><ul class="pages">{pages_html}</ul></div>
    {f'<div><h3>Keep</h3><ul class="keep">{keep}</ul></div>' if keep else ''}
  </div>
  {f'<h3>Consider replacing</h3><div class="grid small">{replace}</div>' if replace else ''}
  <details class="more"><summary>Folder map: {len(c['folders'])} folders reviewed</summary><div class="tscroll"><table class="ftable"><thead><tr><th>Folder</th><th>Videos</th><th>Photos</th><th>Type</th><th>Score</th><th>On site</th><th>What's in it</th></tr></thead><tbody>{folders}</tbody></table></div></details>
</section>''')

    out.append(f'''<section id="unreachable" class="block">
  <div class="shead"><h2>Outside the site's reach</h2><p>The site's Drive account can only read the shared drive. These pieces live elsewhere, so they could not be sheeted or embedded.</p></div>
  <div class="tscroll"><table><thead><tr><th>What</th><th>Client</th><th>Where it is</th><th>What to do</th></tr></thead><tbody>
  {''.join(f'<tr><td><b>{esc(a)}</b></td><td>{esc(b)}</td><td class="muted">{esc(c)}</td><td>{esc(d)}</td></tr>' for a, b, c, d in UNREACHABLE)}
  </tbody></table></div>
</section>
<section id="rest" class="block">
  <div class="shead"><h2>The rest of the Drive</h2><p>Listed in full, not creative work.</p></div>
  <div class="rest">{''.join(f'<div><h3>{esc(t)}</h3><dl>{"".join(f"<div><dt>{esc(a)}</dt><dd>{esc(b)}</dd></div>" for a, b in rows)}</dl></div>' for t, rows in REST)}</div>
</section>
<section id="method" class="block">
  <div class="shead"><h2>How this was made</h2></div>
  <div class="method">
    <p>The site's Drive account listed all 18,875 files it can see: the shared drive "1. Stoop Campaigns" and "2. Stoop Case Studies" plus one Sylvan folder shared from their office. Your own My Drive and the folders shared with you were listed through your Drive connection.</p>
    <p>Finished videos were separated from raw camera files by folder and file names, then versions of the same edit (16x9, 9x16, 4x5, 1x1, logo or no logo) were collapsed to one. That left 259 distinct finished pieces, and each got an 8-frame contact sheet. Every photo folder got numbered thumbnail grids, every image shown for edited folders and an even sample of 48 for raw ones. 877 sheets in all.</p>
    <p>Each sheet was looked at and scored 1 to 5 for how well it would sell The Stoop on the website: 5 is portfolio-grade, 4 is strong, 3 is supporting material. Anything scoring 4 or 5 and not already on a page is listed above with where it fits best. "On the site" means the file's Drive ID appears on a page, in a Drive gallery, or in the hero loop.</p>
    <p>Personal files were counted but not opened or listed.</p>
  </div>
</section>
</main>
<footer class="wrap foot">Prepared for The Stoop. Drive links open for accounts with access to the files.</footer>''')
    out.append(SCRIPT)
    return '\n'.join(out)


HEAD = r'''<title>Drive Content Map</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anton&family=Outfit:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap">
<style>
:root{
  color-scheme: dark;
  --bg:#0b0b0a; --surface:#151513; --surface-2:#1d1d1a; --line:#2b2b27; --text:#f1f0ec; --muted:#a3a29b; --faint:#6f6e68;
  --yellow:#ffcc00; --yellow-ink:#141200; --warn:#ff9f5a; --s3:#5d5c56;
  --display:'Anton', 'Impact', 'Arial Narrow', sans-serif;
  --body:'Outfit', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  --mono:'JetBrains Mono', ui-monospace, 'SFMono-Regular', Menlo, monospace;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:var(--body);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1240px;margin-inline:auto;padding-inline:24px}
@media (max-width:600px){.wrap{padding-inline:16px}}
h1,h2{font-family:var(--display);font-weight:400;text-transform:uppercase;letter-spacing:.01em;line-height:.95;margin:0;text-wrap:balance}
h1{font-size:clamp(56px,10vw,128px)}
h2{font-size:clamp(34px,5vw,54px)}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);font-weight:600;margin:32px 0 14px}
h4{margin:0;font-size:15px;font-weight:600;line-height:1.3;overflow-wrap:anywhere}
p{margin:0}
.top{padding-block:56px 36px}
.eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--yellow);margin-bottom:18px}
.lede{max-width:62ch;font-size:18px;color:var(--muted);margin-top:22px}
.totals{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin:36px 0 0}
.totals>div{background:var(--bg);padding:16px 18px}
.totals dt{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
.totals dd{margin:6px 0 2px;font-family:var(--display);font-size:40px;line-height:1;font-variant-numeric:tabular-nums}
.totals div:last-child dd{color:var(--yellow)}
.totals small{color:var(--faint);font-size:12px}
.filters{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(8px);border-block:1px solid var(--line)}
.frow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding-block:10px}
.flabel{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);margin-right:4px}
.filters button{font:inherit;font-size:13px;color:var(--text);background:var(--surface);border:1px solid var(--line);border-radius:999px;padding:5px 12px;cursor:pointer}
.filters button:hover{border-color:var(--muted)}
.filters button.on{background:var(--yellow);color:var(--yellow-ink);border-color:var(--yellow);font-weight:600}
.filters button:focus-visible,.five input:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--yellow);outline-offset:2px}
.five{margin-left:auto;font-size:13px;color:var(--muted);display:flex;gap:6px;align-items:center;cursor:pointer}
.five input{accent-color:var(--yellow)}
.block{padding-block:56px 8px;scroll-margin-top:56px}
.shead{display:grid;gap:10px;margin-bottom:24px}
.shead p{color:var(--muted);max-width:70ch}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:18px}
.grid.small{grid-template-columns:repeat(auto-fill,minmax(200px,1fr))}
.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;overflow:hidden;display:flex;flex-direction:column}
.thumb{position:relative;display:block;aspect-ratio:4/3;background:#000;overflow:hidden}
.card.port .thumb{aspect-ratio:4/3}
.thumb img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .25s ease}
.card.port .thumb img{object-fit:contain;background:#050505}
.thumb:hover img{transform:scale(1.03)}
.noimg{display:grid;place-items:center;height:100%;color:var(--faint);font-size:13px}
.badge{position:absolute;left:8px;bottom:8px;background:rgba(0,0,0,.72);color:#fff;font-family:var(--mono);font-size:11px;padding:3px 7px;border-radius:3px}
.cbody{padding:14px 14px 16px;display:grid;gap:8px;align-content:start;flex:1}
.cmeta{display:flex;align-items:center;gap:8px}
.ctype{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.score{display:inline-grid;place-items:center;min-width:22px;height:22px;padding:0 5px;border-radius:3px;font-family:var(--mono);font-size:12px;font-weight:500;background:var(--surface-2);color:var(--muted);border:1px solid var(--line)}
.score.s5{background:var(--yellow);color:var(--yellow-ink);border-color:var(--yellow)}
.score.s4{color:var(--yellow);border-color:color-mix(in srgb,var(--yellow) 55%,transparent)}
.score.s1,.score.s2{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 45%,transparent)}
.sum{color:var(--muted);font-size:14px}
.sum.lead{color:var(--text);font-size:15px;font-weight:500;line-height:1.4}
.moment{font-size:13px;color:var(--text)}
.moment b{color:var(--yellow);font-weight:600;margin-right:4px}
.issue{font-size:13px;color:var(--warn)}
.variants{font-size:12px;color:var(--faint)}
.places{list-style:none;padding:0;margin:2px 0 0;display:flex;flex-wrap:wrap;gap:5px}
.places li{font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--text)}
.places .pl-hero-loop{border-color:var(--yellow);color:var(--yellow)}
.places .pl-cover{background:var(--surface-2)}
.path{font-family:var(--mono);font-size:11px;color:var(--faint);overflow-wrap:anywhere;margin-top:auto}
.card.sm .sum{font-size:13px}
.cnav{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:1px;background:var(--line);border:1px solid var(--line)}
.cnav a{display:flex;justify-content:space-between;align-items:center;gap:12px;background:var(--bg);padding:14px 16px;text-decoration:none}
.cnav a:hover{background:var(--surface)}
.cnav b{font-family:var(--mono);font-weight:500;color:var(--yellow)}
.fixes{list-style:none;padding:0;margin:0;display:grid;gap:1px;background:var(--line);border:1px solid var(--line)}
.fixes li{background:var(--bg);padding:16px 18px;display:grid;grid-template-columns:160px 1fr;gap:4px 18px}
.fixes .who{font-weight:600}
.fixes .where{font-family:var(--mono);font-size:12px;color:var(--muted);grid-column:1;grid-row:2}
.fixes p{grid-column:2;grid-row:1/span 2;color:var(--text)}
@media (max-width:640px){.fixes li{grid-template-columns:1fr}.fixes p,.fixes .where{grid-column:1;grid-row:auto}}
details.more,details.take{margin-top:18px;border:1px solid var(--line);border-radius:6px;background:var(--surface)}
details>summary{cursor:pointer;padding:12px 16px;font-weight:500;list-style:none}
details>summary::before{content:'+';display:inline-block;width:18px;color:var(--yellow);font-family:var(--mono)}
details[open]>summary::before{content:'–'}
details.take p{padding:0 16px 14px 34px;color:var(--muted);max-width:90ch}
.notes{margin:0;padding:0 18px 16px 40px;color:var(--muted);display:grid;gap:8px}
.tscroll{overflow-x:auto;padding:0 8px 12px}
table{border-collapse:collapse;width:100%;font-size:13px;min-width:720px}
th{text-align:left;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);padding:10px 8px;border-bottom:1px solid var(--line)}
td{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:top}
td a{text-decoration:none;border-bottom:1px solid var(--line)}
td a:hover{border-color:var(--yellow)}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right;color:var(--muted)}
.muted{color:var(--muted)}
.client{border-top:1px solid var(--line);margin-top:48px}
.chead{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:end;gap:14px 24px}
.line{color:var(--muted);margin-top:10px}
.pagelink{font-family:var(--mono);font-size:13px;color:var(--yellow);text-decoration:none;border:1px solid var(--yellow);padding:6px 10px;border-radius:4px}
.nopage{font-family:var(--mono);font-size:13px;color:var(--warn);border:1px dashed var(--warn);padding:6px 10px;border-radius:4px}
.cstats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin:26px 0 0}
.cstats>div{background:var(--bg);padding:12px 14px}
.cstats dt{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
.cstats dd{margin:4px 0 0;font-family:var(--mono);font-size:20px;font-variant-numeric:tabular-nums}
.onsite{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:0 32px}
.pages,.keep{list-style:none;padding:0;margin:0;display:grid;gap:6px}
.pages li{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid var(--line);padding-bottom:6px;font-family:var(--mono);font-size:13px}
.pages b{font-weight:500;color:var(--muted)}
.keep li{display:flex;justify-content:space-between;gap:10px;font-size:14px}
.keep a{text-decoration:none}
.rest{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:32px}
.rest h3{margin-top:0}
.rest dl{margin:0;display:grid;gap:0}
.rest dl>div{display:grid;grid-template-columns:minmax(120px,38%) 1fr;gap:12px;padding:9px 0;border-bottom:1px solid var(--line);font-size:14px}
.rest dt{font-weight:500}
.rest dd{margin:0;color:var(--muted)}
.method{display:grid;gap:14px;max-width:72ch;color:var(--muted)}
.foot{padding-block:48px 64px;color:var(--faint);font-size:13px}
.card[hidden]{display:none!important}
@media (prefers-reduced-motion:reduce){.thumb img{transition:none}}
</style>'''

SCRIPT = r'''<script>
(function(){
  var filter = 'all', only5 = false;
  var buttons = document.querySelectorAll('.filters button');
  var box = document.getElementById('only5');
  function apply(){
    document.querySelectorAll('.card').forEach(function(c){
      var places = (c.getAttribute('data-place') || '').split(' ');
      var ok = (filter === 'all' || places.indexOf(filter) !== -1) && (!only5 || c.getAttribute('data-score') === '5');
      c.hidden = !ok;
    });
  }
  buttons.forEach(function(b){
    b.addEventListener('click', function(){
      filter = b.getAttribute('data-f');
      buttons.forEach(function(x){ x.classList.toggle('on', x === b); });
      apply();
    });
  });
  box.addEventListener('change', function(){ only5 = box.checked; apply(); });
})();
</script>'''


def build_html():
    data, still_ids = main()
    page = render(data, still_ids)
    open(f'{OUT}/index.html', 'w').write(page)
    print('wrote', f'{OUT}/index.html', round(len(page) / 1024), 'KB')
