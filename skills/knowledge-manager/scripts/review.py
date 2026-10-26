#!/usr/bin/env python3
"""summary: local approve/reject page for an Init review list; each click saves decisions.json next to the items file.
run: python3 review.py <items.json> [--port 8791]

items.json: {"title": str, "intro": str, "sections": [{"title": str, "note": str, "collapsed": bool,
  "items": [{"id": str, "title": str, "detail": str (html allowed), "rec": "approve|reject|", "risk": str}]}]}
Serves on 127.0.0.1 only. GET / renders the page; POST /decisions (JSON {id: {"v": "approve|reject|skip", "note": str}})
overwrites decisions.json. Nothing else is writable.
"""
import html, json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ITEMS = Path(sys.argv[1]).resolve()
OUT = ITEMS.with_name("decisions.json")
PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8791

CSS = """
body{font:15px/1.45 -apple-system,system-ui,sans-serif;max-width:980px;margin:24px auto;padding:0 16px;color:#1b1b1b;background:#fafafa}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 6px;border-bottom:1px solid #ddd;padding-bottom:4px}
.intro,.note{color:#555;margin:4px 0 10px}.item{background:#fff;border:1px solid #e2e2e2;border-left:4px solid #bbb;border-radius:6px;padding:10px 12px;margin:8px 0}
.item.approve{border-left-color:#107c10}.item.reject{border-left-color:#c42b1c}.item.skip{border-left-color:#8e6a00}
.t{font-weight:600}.risk{font-size:12px;color:#fff;background:#c42b1c;border-radius:3px;padding:1px 6px;margin-left:6px}
.risk.medium{background:#c47a00}.risk.low{background:#777}.d{margin:6px 0;color:#333}.d code{background:#f0f0f0;padding:0 3px;border-radius:3px}
.rec{font-size:12px;color:#555}.btns button{margin-right:6px;padding:4px 12px;border:1px solid #bbb;border-radius:4px;background:#fff;cursor:pointer}
.btns button.on[data-v=approve]{background:#107c10;color:#fff;border-color:#107c10}.btns button.on[data-v=reject]{background:#c42b1c;color:#fff;border-color:#c42b1c}
.btns button.on[data-v=skip]{background:#8e6a00;color:#fff;border-color:#8e6a00}textarea{width:100%;box-sizing:border-box;margin-top:6px;font:13px system-ui;min-height:30px}
#bar{position:sticky;top:0;background:#fafafa;padding:8px 0;border-bottom:1px solid #ddd;z-index:2;display:flex;gap:12px;align-items:center}
#saved{color:#107c10;font-size:13px}details>summary{cursor:pointer;color:#0063b1;margin:6px 0}
"""

JS = """
const D = JSON.parse(document.getElementById('dec').textContent);
function paint(){ for (const el of document.querySelectorAll('.item')) { const v=(D[el.dataset.id]||{}).v||'';
  for (const c of ['approve','reject','skip']) el.classList.toggle(c, c===v); for (const b of el.querySelectorAll('button')) b.classList.toggle('on', b.dataset.v===v);
  const ta=el.querySelector('textarea'); if (document.activeElement!==ta) ta.value=(D[el.dataset.id]||{}).note||''; }
  const all=document.querySelectorAll('.item.need').length, done=[...document.querySelectorAll('.item.need')].filter(e=>(D[e.dataset.id]||{}).v).length;
  document.getElementById('count').textContent = done+' / '+all+' decisions needed'; }
let t; async function save(){ const r=await fetch('/decisions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(D)});
  document.getElementById('saved').textContent = r.ok ? 'saved '+new Date().toLocaleTimeString() : 'SAVE FAILED'; }
document.addEventListener('click', e => { const b=e.target.closest('button[data-v]'); if(!b) return; const id=b.closest('.item').dataset.id;
  D[id]=Object.assign(D[id]||{}, {v: (D[id]||{}).v===b.dataset.v ? '' : b.dataset.v}); paint(); save(); });
document.addEventListener('input', e => { if(e.target.tagName!=='TEXTAREA') return; const id=e.target.closest('.item').dataset.id;
  D[id]=Object.assign(D[id]||{}, {note:e.target.value}); clearTimeout(t); t=setTimeout(save,600); });
document.getElementById('acceptrec').onclick = () => { for (const el of document.querySelectorAll('.item.need')) { const id=el.dataset.id;
  if (!(D[id]||{}).v && el.dataset.rec) D[id]=Object.assign(D[id]||{}, {v:el.dataset.rec}); } paint(); save(); };
paint();
"""


def page():
    data = json.loads(ITEMS.read_text())
    dec = json.loads(OUT.read_text()) if OUT.exists() else {}
    h = [f"<!doctype html><meta charset=utf-8><title>{html.escape(data['title'])}</title><style>{CSS}</style>",
         f"<h1>{html.escape(data['title'])}</h1><div class=intro>{data.get('intro', '')}</div>",
         "<div id=bar><b id=count></b><button id=acceptrec>Accept my recommendation on all undecided</button><span id=saved></span></div>"]
    for s in data["sections"]:
        need = not s.get("collapsed")
        body = []
        for it in s["items"]:
            risk = it.get("risk", "")
            rec = it.get("rec", "")
            body.append(
                f"<div class='item{' need' if need else ''}' data-id='{html.escape(it['id'], True)}' data-rec='{rec}'>"
                f"<span class=t>{html.escape(it['title'])}</span>"
                + (f"<span class='risk {risk}'>{risk}</span>" if risk else "")
                + f"<div class=d>{it.get('detail', '')}</div>"
                + (f"<div class=rec>My recommendation: <b>{rec}</b></div>" if rec else "")
                + "<div class=btns><button data-v=approve>Approve</button><button data-v=reject>Reject</button>"
                  "<button data-v=skip>Park</button></div><textarea placeholder='note (optional)'></textarea></div>")
        inner = "".join(body)
        h.append(f"<h2>{html.escape(s['title'])} ({len(s['items'])})</h2><div class=note>{s.get('note', '')}</div>")
        h.append(f"<details><summary>show {len(s['items'])} items</summary>{inner}</details>" if s.get("collapsed") else inner)
    dec_json = json.dumps(dec).replace("</", "<\\/")
    h.append(f"<script id=dec type=application/json>{dec_json}</script><script>{JS}</script>")
    return "".join(h).encode()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(200, page())
        if self.path == "/decisions.json":
            return self.send(200, OUT.read_bytes() if OUT.exists() else b"{}", "application/json")
        self.send(404, b"not found", "text/plain")

    def do_POST(self):
        host = self.headers.get("Origin") or ""
        if self.path != "/decisions" or (host and host != f"http://127.0.0.1:{PORT}" and host != f"http://localhost:{PORT}"):
            return self.send(403, b"forbidden", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            return self.send(413, b"too large", "text/plain")
        try:
            d = json.loads(self.rfile.read(n))
            assert isinstance(d, dict)
        except Exception:
            return self.send(400, b"bad json", "text/plain")
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False))
        tmp.replace(OUT)
        self.send(200, b"ok", "text/plain")


if __name__ == "__main__":
    print(f"review: http://127.0.0.1:{PORT}/  (decisions -> {OUT})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
