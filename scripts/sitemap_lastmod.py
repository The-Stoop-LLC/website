#!/usr/bin/env python3
"""
Set each <lastmod> in sitemap.xml from the page it points at.

Why: stamping every URL with the same date tells search engines the dates
are meaningless, and it contradicted the dateModified in each page's schema.

Rule, per URL:
  1. the page's JSON-LD dateModified (latest, if several), else
  2. its JSON-LD datePublished, else
  3. the date of the last git commit that touched the file.

Usage (from the repo root, after committing page changes):

    python3 scripts/sitemap_lastmod.py           # preview
    python3 scripts/sitemap_lastmod.py --write   # update sitemap.xml

When you make a real content change to a page with a schema date, bump its
dateModified first; tracking-code or markup-only edits don't need it.
"""

import json
import re
import subprocess
import sys
def file_for(url):
    p=url.replace("https://thestooppgh.com/","")
    if p=="" or p.endswith("/"): return p+"index.html"
    return p if p.endswith(".html") else p+".html"  # GitHub Pages serves /contact from contact.html
def schema_dates(path):
    s=open(path,encoding="utf-8").read(); mod=[]; pub=[]
    def walk(o, top):
        if isinstance(o,dict):
            # only dates on the page's own main entity, not nested reviews/articles in lists
            if o.get("@type") in ("WebPage","Article","BlogPosting","FAQPage","CollectionPage","ContactPage","ProfilePage","Service","ProfessionalService","Blog","AboutPage") or top:
                if "dateModified" in o: mod.append(o["dateModified"])
                if "datePublished" in o: pub.append(o["datePublished"])
            for k,v in o.items():
                if k in ("blogPost","itemListElement","hasPart","review"): continue
                walk(v, False)
        elif isinstance(o,list):
            for v in o: walk(v, top)
    for m in re.findall(r'<script[^>]+ld\+json[^>]*>(.*?)</script>',s,re.S):
        walk(json.loads(m), True)
    full=lambda d: [x for x in d if re.fullmatch(r"\d{4}-\d{2}-\d{2}",x[:10])]
    return max(full(mod))[:10] if full(mod) else None, max(full(pub))[:10] if full(pub) else None
def git_date(path):
    return subprocess.run(["git","log","-1","--format=%cs","--",path],capture_output=True,text=True).stdout.strip()
sm=open("sitemap.xml",encoding="utf-8").read()
rows=[]
for url in re.findall(r"<loc>([^<]+)</loc>",sm):
    f=file_for(url); mod,pub=schema_dates(f)
    src,val=("dateModified",mod) if mod else (("datePublished",pub) if pub else ("git",git_date(f)))
    rows.append((url,val,src))
if "--write" in sys.argv:
    def sub(m):
        url=m.group(1); val=dict((u,v) for u,v,_ in rows)[url]
        return re.sub(r"<lastmod>[^<]*</lastmod>",f"<lastmod>{val}</lastmod>",m.group(0))
    new=re.sub(r"<url>\s*<loc>([^<]+)</loc>.*?</url>",sub,sm,flags=re.S)
    open("sitemap.xml","w",encoding="utf-8").write(new)
for u,v,src in rows: print(f"{v}  {src:13s} {u.replace('https://thestooppgh.com','')}")
