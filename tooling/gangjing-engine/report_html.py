#!/usr/bin/env python3
"""
Break My Code - HTML Report Generator (v2)

Features: verdict/severity filters, full-text search, category bar chart,
fix suggestion field, diff mode (--diff old.json new.json), print-friendly CSS.

Usage:
    python report_html.py results1.json results2.json -o report.html
    python report_html.py --dir ./test-demo/ -o report.html
    python report_html.py --diff before.json after.json -o diff.html
"""
import argparse, glob, json, os, sys
from collections import Counter
from datetime import datetime

VERDICT_META = {
    "crashed": {"icon": "\U0001F4A5", "color": "#ef4444", "label": "Crashed"},
    "wrong":   {"icon": "\U0001F3AF", "color": "#f59e0b", "label": "Wrong"},
    "hung":    {"icon": "\u23F3",     "color": "#8b5cf6", "label": "Hung"},
    "leaked":  {"icon": "\U0001F513", "color": "#ec4899", "label": "Leaked"},
    "survived":{"icon": "\U0001F6E1\uFE0F", "color": "#22c55e", "label": "Survived"},
}
SEV_ORDER = ["CRITICAL","HIGH","MEDIUM","LOW","INFO"]
SEV_COLORS = {"CRITICAL":"#dc2626","HIGH":"#ea580c","MEDIUM":"#d97706","LOW":"#65a30d","INFO":"#6b7280"}
GRADE_COLORS = {"A":"#22c55e","B":"#84cc16","C":"#eab308","D":"#f97316","F":"#ef4444"}

def _e(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")

def load_results(paths):
    out = []
    for p in paths:
        with open(p) as f: d = json.load(f)
        nm = d.get("target", os.path.basename(p))
        if "::" in nm: nm = nm.split("::")[-1]
        out.append({"name": nm, "data": d, "file": os.path.basename(p)})
    return out

def _donut(summary, total):
    if total == 0: return ""
    s, off = "", 25
    for v in ["crashed","wrong","hung","leaked","survived"]:
        c = summary.get(v, 0)
        if c == 0: continue
        pct = c / total * 100
        s += f'<circle cx="21" cy="21" r="15.9" fill="transparent" stroke="{VERDICT_META[v]["color"]}" stroke-width="4" stroke-dasharray="{pct} {100-pct}" stroke-dashoffset="{-off}"/>\n'
        off += pct
    return s

def _cat_bars(results):
    cats = Counter(); cv = {}
    for r in results:
        c = r.get("category","Unknown"); cats[c] += 1
        cv.setdefault(c, Counter())[r["verdict"]] += 1
    if not cats: return ""
    rows = ""
    for cat, total in cats.most_common():
        segs = ""
        for v in ["crashed","wrong","hung","leaked","survived"]:
            n = cv[cat].get(v, 0)
            if n == 0: continue
            segs += f'<div class="bar-seg" style="width:{n/total*100}%;background:{VERDICT_META[v]["color"]}" title="{VERDICT_META[v]["label"]}: {n}"></div>'
        rows += f'<div class="bar-row"><span class="bar-label">{_e(cat)}</span><div class="bar-track">{segs}</div><span class="bar-count">{total}</span></div>'
    return f'<div class="cat-chart">{rows}</div>'

def _kill_card(k):
    vm = VERDICT_META.get(k["verdict"], VERDICT_META["crashed"])
    sc = SEV_COLORS.get(k.get("severity","MEDIUM"), "#6b7280")
    sem = '<span class="sem-tag">Semantic</span>' if k.get("semantic_findings") else ""
    fix = f'<div class="kill-fix"><b>Fix:</b> {_e(str(k["fix"])[:500])}</div>' if k.get("fix") else ""
    return f'''<div class="kill-card" data-verdict="{_e(k['verdict'])}" data-severity="{_e(k.get('severity','MEDIUM'))}" style="border-left:4px solid {vm['color']}">
  <div class="kill-header"><span class="verdict-badge" style="background:{vm['color']}">{vm['icon']} {vm['label']}</span><span class="sev-badge" style="background:{sc}">{k.get('severity','MEDIUM')}</span><span class="cat-label">{_e(k.get('category',''))}</span>{sem}</div>
  <div class="kill-name">{_e(k['name'])}</div>
  <div class="kill-payload"><b>Payload:</b> <code>{_e(str(k.get('payload','')))[:200]}</code></div>
  <div class="kill-detail"><b>Result:</b> {_e(str(k.get('detail',''))[:300])}</div>{fix}
</div>'''

CSS = r"""@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@400;600;700&display=swap');
:root{--bg:#0f172a;--surface:#1e293b;--surface2:#334155;--text:#e2e8f0;--text2:#94a3b8;--accent:#38bdf8;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Space Grotesk',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}
.header{background:linear-gradient(135deg,#0f172a 0%,#1e1b4b 50%,#0f172a 100%);padding:3rem 2rem 2rem;text-align:center;border-bottom:1px solid var(--surface2);}
.header h1{font-size:2.2rem;letter-spacing:-1px;} .header .skull{font-size:3rem;display:block;margin-bottom:0.5rem;} .header .subtitle{color:var(--text2);margin-top:0.5rem;font-size:0.95rem;}
.stats-bar{display:flex;justify-content:center;gap:2rem;margin-top:1.5rem;flex-wrap:wrap;} .stat{text-align:center;} .stat-val{font-size:2rem;font-weight:700;font-family:'JetBrains Mono',monospace;} .stat-label{font-size:0.8rem;color:var(--text2);text-transform:uppercase;letter-spacing:1px;}
.container{max-width:960px;margin:2rem auto;padding:0 1.5rem;}
.target-list{display:flex;flex-direction:column;gap:0.75rem;margin-bottom:2rem;}
.target-card{display:flex;align-items:center;gap:1rem;padding:1rem 1.2rem;background:var(--surface);border-radius:12px;cursor:pointer;transition:all 0.2s;border:2px solid transparent;}
.target-card:hover{border-color:var(--accent);transform:translateX(4px);} .target-card.active{border-color:var(--accent);background:#1e293bcc;}
.target-score{width:52px;height:52px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1.2rem;font-family:'JetBrains Mono',monospace;color:#fff;flex-shrink:0;}
.target-name{font-weight:600;font-size:1.05rem;} .target-grade{color:var(--text2);font-size:0.85rem;}
.detail-section{animation:fadeIn 0.3s ease;} @keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
.score-row{display:flex;align-items:center;gap:1.5rem;margin:1.5rem 0;}
.big-score{font-size:4rem;font-weight:700;font-family:'JetBrains Mono',monospace;line-height:1;} .score-unit{font-size:1.5rem;color:var(--text2);}
.big-grade{padding:0.4rem 1.2rem;border-radius:8px;color:#fff;font-weight:700;font-size:1.3rem;}
.donut-row{display:flex;align-items:center;gap:2rem;margin:1.5rem 0;} .donut{width:120px;height:120px;}
.legend{display:flex;flex-direction:column;gap:0.4rem;} .legend-item{display:flex;align-items:center;gap:0.5rem;font-size:0.9rem;} .legend-dot{width:12px;height:12px;border-radius:3px;flex-shrink:0;}
h3{margin:2rem 0 1rem;font-size:1.2rem;color:var(--accent);}
.cat-chart{margin:0.5rem 0 1.5rem;} .bar-row{display:flex;align-items:center;gap:0.5rem;margin:0.3rem 0;} .bar-label{width:110px;font-size:0.8rem;color:var(--text2);text-align:right;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;} .bar-track{flex:1;height:18px;background:var(--surface);border-radius:4px;display:flex;overflow:hidden;} .bar-seg{height:100%;} .bar-count{font-size:0.75rem;color:var(--text2);width:24px;text-align:right;}
.filter-bar{display:flex;align-items:center;gap:0.75rem;margin:1rem 0;flex-wrap:wrap;}
.search-box{background:var(--surface);border:1px solid var(--surface2);color:var(--text);padding:0.4rem 0.8rem;border-radius:8px;font-size:0.85rem;width:200px;outline:none;font-family:inherit;} .search-box:focus{border-color:var(--accent);}
.filter-chips{display:flex;align-items:center;gap:0.3rem;} .chip{display:flex;align-items:center;gap:0.15rem;cursor:pointer;padding:0.2rem 0.4rem;border-radius:6px;background:var(--surface);font-size:0.85rem;transition:opacity 0.15s;} .chip input{display:none;} .chip:has(input:not(:checked)){opacity:0.3;} .chip-sep{color:var(--surface2);font-size:0.9rem;}
.kill-list{display:flex;flex-direction:column;gap:0.75rem;} .kill-card{background:var(--surface);border-radius:10px;padding:1rem 1.2rem;transition:transform 0.15s;} .kill-card:hover{transform:translateX(4px);} .kill-card.hidden{display:none;}
.kill-header{display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.5rem;} .verdict-badge,.sev-badge{padding:0.15rem 0.6rem;border-radius:6px;font-size:0.78rem;font-weight:600;color:#fff;white-space:nowrap;}
.cat-label{color:var(--text2);font-size:0.85rem;} .sem-tag{padding:0.15rem 0.5rem;border-radius:6px;font-size:0.72rem;background:#7c3aed33;color:#a78bfa;border:1px solid #7c3aed55;}
.kill-name{font-weight:600;margin-bottom:0.4rem;} .kill-payload,.kill-detail,.kill-fix{font-size:0.85rem;color:var(--text2);margin:0.2rem 0;line-height:1.5;} .kill-payload code{background:var(--surface2);padding:0.1rem 0.4rem;border-radius:4px;font-family:'JetBrains Mono',monospace;font-size:0.8rem;}
.kill-fix{color:#4ade80;border-top:1px dashed var(--surface2);padding-top:0.4rem;margin-top:0.4rem;}
.no-kills{text-align:center;padding:2rem;color:var(--text2);font-size:1.1rem;}
.surv-details{margin:1.5rem 0;} .surv-details summary{cursor:pointer;color:var(--text2);font-size:0.9rem;padding:0.5rem 0;} .surv-list{display:flex;flex-direction:column;gap:0.3rem;margin-top:0.5rem;} .surv-item{font-size:0.85rem;color:var(--text2);padding:0.3rem 0.5rem;background:var(--surface);border-radius:6px;}
.footer{text-align:center;padding:2rem;color:var(--text2);font-size:0.8rem;border-top:1px solid var(--surface2);margin-top:3rem;}
table{width:100%;border-collapse:collapse;margin:1.5rem 0;} th{text-align:left;padding:0.6rem 0.8rem;color:var(--text2);font-size:0.8rem;text-transform:uppercase;border-bottom:1px solid var(--surface2);} td{padding:0.6rem 0.8rem;border-bottom:1px solid var(--surface2);font-size:0.9rem;}
.diff-header{display:flex;justify-content:center;align-items:center;gap:2rem;margin:2rem 0;flex-wrap:wrap;} .diff-box{text-align:center;padding:1.5rem 2rem;background:var(--surface);border-radius:12px;min-width:140px;} .diff-box .val{font-size:2.5rem;font-weight:700;font-family:'JetBrains Mono',monospace;} .diff-box .lbl{font-size:0.8rem;color:var(--text2);text-transform:uppercase;} .diff-arrow{font-size:2rem;color:var(--text2);}
.diff-stats{display:flex;gap:1.5rem;justify-content:center;margin:1rem 0;flex-wrap:wrap;} .diff-stat{padding:0.3rem 0.8rem;border-radius:6px;font-size:0.85rem;font-weight:600;}
.fixed-tag{color:#22c55e;} .regressed-tag{color:#ef4444;} .improved-tag{color:#38bdf8;} .same-tag{color:var(--text2);} .new-tag{color:#a78bfa;} .diff-tag{font-weight:600;font-size:0.8rem;}
@media print{body{background:#fff;color:#111;} .header{background:#f8fafc;border-bottom:2px solid #e2e8f0;} .header h1,.header .skull{color:#111;} .target-card{border:1px solid #e2e8f0;break-inside:avoid;} .target-card:hover{transform:none;} .kill-card{break-inside:avoid;border:1px solid #e2e8f0;} .detail-section{display:block!important;page-break-before:always;} .target-list,.filter-bar{display:none;} .big-score,.big-grade,.verdict-badge,.sev-badge{print-color-adjust:exact;-webkit-print-color-adjust:exact;}}"""

JS = r"""let active=-1;
function showDetail(i){document.querySelectorAll('.detail-section').forEach(e=>e.style.display='none');document.querySelectorAll('.target-card').forEach(e=>e.classList.remove('active'));if(active===i){active=-1;return;}document.getElementById('detail-'+i).style.display='block';document.querySelectorAll('.target-card')[i].classList.add('active');active=i;}
function filterKills(idx){const sec=document.getElementById('detail-'+idx);if(!sec)return;const q=(sec.querySelector('.search-box')||{}).value||'';const ql=q.toLowerCase();const chips=sec.querySelectorAll('#chips-'+idx+' input');const aV=new Set,aS=new Set;chips.forEach(c=>{if(c.dataset.type==='verdict'&&c.checked)aV.add(c.value);if(c.dataset.type==='severity'&&c.checked)aS.add(c.value);});sec.querySelectorAll('.kill-card').forEach(card=>{const show=aV.has(card.dataset.verdict)&&aS.has(card.dataset.severity)&&(!ql||card.textContent.toLowerCase().includes(ql));card.classList.toggle('hidden',!show);});}
if(document.querySelectorAll('.target-card').length>0)showDetail(0);"""

def render_html(targets):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ta = sum(t["data"]["total_attacks"] for t in targets)
    tk = sum(t["data"]["total_attacks"] - t["data"]["summary"].get("survived",0) for t in targets)
    avg = round(sum(t["data"]["resilience_score"] for t in targets)/len(targets)) if targets else 0
    ag = "A" if avg>=90 else "B" if avg>=75 else "C" if avg>=60 else "D" if avg>=40 else "F"
    tc, ds = "", ""
    for idx, t in enumerate(targets):
        d = t["data"]; sc, gr = d["resilience_score"], d["grade"]; gc = GRADE_COLORS.get(gr,"#6b7280")
        kills = [r for r in d["results"] if r["verdict"]!="survived"]
        surv = [r for r in d["results"] if r["verdict"]=="survived"]
        ks = sorted(kills, key=lambda r: SEV_ORDER.index(r["severity"]) if r["severity"] in SEV_ORDER else 99)
        cnt = d["summary"]
        tc += f'''<div class="target-card" onclick="showDetail({idx})"><div class="target-score" style="background:{gc}">{sc}</div><div class="target-info"><div class="target-name">{_e(t["name"])}</div><div class="target-grade">Grade {gr} &middot; {d["total_attacks"]} attacks &middot; {len(kills)} kills</div></div></div>'''
        legend = "".join(f'<div class="legend-item"><span class="legend-dot" style="background:{VERDICT_META[v]["color"]}"></span>{VERDICT_META[v]["label"]}: {cnt.get(v,0)}</div>' for v in VERDICT_META if cnt.get(v,0)>0)
        kr = "".join(_kill_card(k) for k in ks)
        si = "".join(f'<div class="surv-item">{VERDICT_META["survived"]["icon"]} {_e(s["category"])}: {_e(s["name"])}</div>' for s in surv)
        chips = ''.join(f'<label class="chip"><input type="checkbox" checked onchange="filterKills({idx})" data-type="verdict" value="{v}"><span style="color:{VERDICT_META[v]["color"]}">{VERDICT_META[v]["icon"]}</span></label>' for v in ["crashed","wrong","hung","leaked"])
        chips += '<span class="chip-sep">|</span>'
        chips += ''.join(f'<label class="chip"><input type="checkbox" checked onchange="filterKills({idx})" data-type="severity" value="{s}"><span style="color:{SEV_COLORS[s]}">{s[0]}</span></label>' for s in SEV_ORDER[:4])
        ds += f'''<div class="detail-section" id="detail-{idx}" style="display:none">
<h2>{_e(t["name"])}</h2>
<div class="score-row"><div class="big-score" style="color:{gc}">{sc}<span class="score-unit">/100</span></div><div class="big-grade" style="background:{gc}">Grade {gr}</div></div>
<div class="donut-row"><svg viewBox="0 0 42 42" class="donut"><circle cx="21" cy="21" r="15.9" fill="transparent" stroke="#1e293b" stroke-width="4"/>{_donut(cnt,d["total_attacks"])}</svg><div class="legend">{legend}</div></div>
<h3>Category Breakdown</h3>{_cat_bars(d["results"])}
<div class="filter-bar"><input type="text" class="search-box" placeholder="Search kills..." oninput="filterKills({idx})"><div class="filter-chips" id="chips-{idx}">{chips}</div></div>
<h3>Kill Log ({len(kills)})</h3><div class="kill-list" id="kills-{idx}">{kr if kr else '<div class="no-kills">No kills &mdash; all attacks survived!</div>'}</div>
<details class="surv-details"><summary>Survival Log ({len(surv)})</summary><div class="surv-list">{si}</div></details></div>'''

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Break My Code - Destruction Report</title><style>{CSS}</style></head><body>
<div class="header"><span class="skull">\U0001f480</span><h1>Break My Code</h1><div class="subtitle">Destruction Report &middot; {now}</div>
<div class="stats-bar"><div class="stat"><div class="stat-val">{len(targets)}</div><div class="stat-label">Targets</div></div><div class="stat"><div class="stat-val">{ta}</div><div class="stat-label">Attacks</div></div><div class="stat"><div class="stat-val" style="color:#ef4444">{tk}</div><div class="stat-label">Kills</div></div><div class="stat"><div class="stat-val" style="color:{GRADE_COLORS.get(ag,"#6b7280")}">{avg}</div><div class="stat-label">Avg Score</div></div></div></div>
<div class="container"><div class="target-list">{tc}</div>{ds}</div>
<div class="footer">Generated by break-my-code skill &middot; Adversarial Pair Programmer</div>
<script>{JS}</script></body></html>'''

def render_diff(old_path, new_path):
    with open(old_path) as f: old = json.load(f)
    with open(new_path) as f: new = json.load(f)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    os_, ns_ = old["resilience_score"], new["resilience_score"]
    delta = ns_ - os_
    dc = "#22c55e" if delta>0 else "#ef4444" if delta<0 else "#94a3b8"
    ds = ("+" if delta>0 else "") + str(delta)
    on = {r["name"]:r for r in old["results"]}
    nn = {r["name"]:r for r in new["results"]}
    names = list(dict.fromkeys(list(on)+list(nn)))
    rows, fixed, regr, changed, same, newn = "", 0, 0, 0, 0, 0
    for nm in names:
        o, n = on.get(nm), nn.get(nm)
        if not o:
            newn += 1; nvm=VERDICT_META.get(n["verdict"],VERDICT_META["crashed"])
            rows += f'<tr><td>{_e(nm)}</td><td>&mdash;</td><td><span class="verdict-badge" style="background:{nvm["color"]}">{nvm["icon"]} {nvm["label"]}</span></td><td class="diff-tag new-tag">NEW</td></tr>'
            continue
        if not n:
            rows += f'<tr><td>{_e(nm)}</td><td>{o["verdict"]}</td><td>&mdash;</td><td class="diff-tag">REMOVED</td></tr>'; continue
        ov, nv = o["verdict"], n["verdict"]
        ovm, nvm = VERDICT_META.get(ov,VERDICT_META["crashed"]), VERDICT_META.get(nv,VERDICT_META["crashed"])
        ob = f'<span class="verdict-badge" style="background:{ovm["color"]}">{ovm["icon"]} {ovm["label"]}</span>'
        nb = f'<span class="verdict-badge" style="background:{nvm["color"]}">{nvm["icon"]} {nvm["label"]}</span>'
        if ov!="survived" and nv=="survived": fixed+=1; tag='<td class="diff-tag fixed-tag">FIXED</td>'
        elif ov==nv: same+=1; tag='<td class="diff-tag same-tag">SAME</td>'
        elif ov=="survived" and nv!="survived": regr+=1; tag='<td class="diff-tag regressed-tag">REGRESSED</td>'
        else: changed+=1; tag='<td class="diff-tag improved-tag">CHANGED</td>'
        rows += f'<tr><td>{_e(nm)}</td><td>{ob}</td><td>{nb}</td>{tag}</tr>'

    return f'''<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Break My Code - Diff Report</title><style>{CSS}</style></head><body>
<div class="header"><span class="skull">\U0001f480</span><h1>Break My Code &mdash; Diff</h1><div class="subtitle">Comparison Report &middot; {now}</div></div>
<div class="container">
<div class="diff-header">
<div class="diff-box"><div class="val" style="color:{GRADE_COLORS.get(old['grade'],'#6b7280')}">{os_}</div><div class="lbl">Before (Grade {old['grade']})</div></div>
<div class="diff-arrow">&rarr;</div>
<div class="diff-box"><div class="val" style="color:{GRADE_COLORS.get(new['grade'],'#6b7280')}">{ns_}</div><div class="lbl">After (Grade {new['grade']})</div></div>
<div class="diff-box"><div class="val" style="color:{dc}">{ds}</div><div class="lbl">Delta</div></div>
</div>
<div class="diff-stats">
<span class="diff-stat" style="background:#22c55e22;color:#22c55e">Fixed: {fixed}</span>
<span class="diff-stat" style="background:#ef444422;color:#ef4444">Regressed: {regr}</span>
<span class="diff-stat" style="background:#38bdf822;color:#38bdf8">Changed: {changed}</span>
<span class="diff-stat" style="background:#94a3b822;color:#94a3b8">Same: {same}</span>
<span class="diff-stat" style="background:#a78bfa22;color:#a78bfa">New: {newn}</span>
</div>
<table><thead><tr><th>Attack</th><th>Before</th><th>After</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table>
</div><div class="footer">Generated by break-my-code skill</div></body></html>'''

def main():
    p = argparse.ArgumentParser(description="Generate HTML destruction report")
    p.add_argument("files", nargs="*", help="JSON result files")
    p.add_argument("--dir", help="Directory to scan for *results*.json")
    p.add_argument("-o","--output", default="report.html")
    p.add_argument("--diff", nargs=2, metavar=("OLD","NEW"), help="Diff mode")
    a = p.parse_args()
    if a.diff:
        html = render_diff(a.diff[0], a.diff[1])
        with open(a.output,"w") as f: f.write(html)
        print(f"Diff report: {a.output}"); return
    paths = list(a.files)
    if a.dir:
        paths.extend(sorted(glob.glob(os.path.join(a.dir,"*results*.json"))))
        paths.extend(sorted(glob.glob(os.path.join(a.dir,"*result*.json"))))
    paths = list(dict.fromkeys(paths))
    if not paths: print("No result files found.",file=sys.stderr); sys.exit(1)
    targets = load_results(paths)
    html = render_html(targets)
    with open(a.output,"w") as f: f.write(html)
    print(f"Report generated: {a.output} ({len(targets)} targets)")

if __name__ == "__main__":
    main()
