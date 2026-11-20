"""Build a fully offline copy of FaultLens from the live service.

    python make_offline.py                        # uses the default live URL
    python make_offline.py https://other-url      # or point it somewhere else

Step 1 drives the live service over HTTP, exactly as the page does, and records every
response. Step 2 glues those recordings into the real web/index.html behind a fetch shim,
so the offline file IS the real interface with real answers and no network at all.

Writes: faultlens_offline.html  (open it by double-clicking; works with wifi off)
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE = (sys.argv[1] if len(sys.argv) > 1
        else "https://faultlens-580714829977.asia-south1.run.app").rstrip("/")
HERE = Path(__file__).resolve().parent
INDEX = HERE / "web" / "index.html"
OUT = HERE / "faultlens_offline.html"

calls: dict[str, dict] = {}
images: dict[str, str] = {}
TIMEOUT = 180


# --------------------------------------------------------------------------- http

def _req(path: str, method="GET", data=None, headers=None):
    url = BASE + path
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(r, timeout=TIMEOUT) as resp:
        return resp.status, resp.headers.get("content-type", ""), resp.read()


def key_of(path: str, method="GET", body: str = "") -> str:
    return f"{method.upper()} {path}" + (f" :: {body}" if body else "")


def record(path, method="GET", json_body=None, form=None, label=""):
    """Call the live service and keep the answer under the same key the page will ask for."""
    data = headers = None
    body_key = ""
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers = {"Content-Type": "application/json"}
        body_key = json.dumps(json_body, separators=(",", ":"))
    elif form is not None:
        boundary = "----faultlens" + uuid.uuid4().hex
        parts = []
        for k, v in form:
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n")
        parts.append(f"--{boundary}--\r\n")
        data = "".join(parts).encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        body_key = "&".join(sorted(f"{k}={v}" for k, v in form))
    t = time.time()
    try:
        status, ct, raw = _req(path, method, data, headers)
    except urllib.error.HTTPError as e:
        print(f"  ! {label or path}: HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  ! {label or path}: {e}")
        return None
    text = raw.decode("utf-8", "replace")
    calls[key_of(path, method, body_key)] = {"status": status, "ct": ct, "body": text}
    print(f"  ok {label or path}  ({len(text):,} bytes, {time.time() - t:.1f}s)")
    try:
        return json.loads(text)
    except ValueError:
        return None


def grab_image(path: str):
    if path in images or not path.startswith("/"):
        return
    try:
        status, ct, raw = _req(path)
    except Exception:
        return
    if status != 200:
        return
    if not ct:
        ct = mimetypes.guess_type(path)[0] or "application/octet-stream"
    images[path] = f"data:{ct.split(';')[0]};base64," + base64.b64encode(raw).decode()


ASSET = re.compile(r'"(/(?:api|library)/[^"\\]+?\.(?:jpe?g|png|webp|gif|svg|wav|mp3|mp4))"')
DIAGRAM = re.compile(r'"(/api/diagram\.jpg\?[^"\\]*)"')


def harvest_assets():
    """Every image, sound and diagram mentioned anywhere in what we recorded."""
    found = set()
    for c in list(calls.values()):
        for m in ASSET.finditer(c["body"]):
            found.add(m.group(1))
        for m in DIAGRAM.finditer(c["body"]):
            found.add(m.group(1).replace("\\u0026", "&").replace("&amp;", "&"))
    for p in sorted(found):
        grab_image(p)
    print(f"  assets: {len(images)} captured")


# --------------------------------------------------------------------------- capture

def capture():
    print(f"Recording from {BASE}")
    print("\n[1/7] Pages that load on open")
    profile = record("/api/profile")
    lib = record("/api/library")
    parts = record("/api/parts")
    for p in ("/api/pattern-report", "/api/partcheck-report", "/api/vision-report",
              "/api/eval-report", "/api/anomaly-report", "/api/jobcards"):
        record(p)

    print("\n[2/7] Every library sample")
    samples = []
    for c in (lib or {}).get("conditions", []):
        for s in c.get("samples", []):
            samples.append((c["condition"], s["id"]))
            record(f"/api/library/{c['condition']}/{s['id']}", label=f"{c['condition']}/{s['id']}")

    print("\n[3/7] A full investigation (the slow one, about a minute)")
    target = next((cs for cs in samples if cs[0] == "clogged_air_filter"), samples[0] if samples else None)
    if target:
        record("/api/investigate", "POST", form=[
            ("sensor_csv", ""), ("library_sample", f"{target[0]}/{target[1]}"),
            ("notes", "[]"), ("find_parts", "true"), ("use_checker", "true"),
        ], label=f"investigate {target[0]}/{target[1]}")

    print("\n[4/7] A played job, driven by the coach")
    job = record("/api/game/new", "POST", json_body={"condition": ""}, label="new job")
    if job and job.get("id"):
        jid = job["id"]
        for step in range(4):
            adv = record(f"/api/game/{jid}/advise", "POST", json_body={"question": ""},
                         label=f"advise {step + 1}")
            if not adv:
                break
            nxt = adv.get("next_action_id")
            if nxt in ("conclude", None):
                break
            if nxt == "power_off":
                record(f"/api/game/{jid}/power", "POST", json_body={"on": False}, label="power off")
                continue
            if nxt == "power_on":
                record(f"/api/game/{jid}/power", "POST", json_body={"on": True}, label="power on")
                continue
            record(f"/api/game/{jid}/action", "POST", json_body={"action": nxt}, label=f"check: {nxt}")
        adv = record(f"/api/game/{jid}/advise", "POST", json_body={"question": ""}, label="final advice")
        choice = ((adv or {}).get("hypotheses") or [{}])[0].get("fault_id") or "clogged_air_filter"
        record(f"/api/game/{jid}/conclude", "POST", json_body={"choice": choice}, label="diagnosis")

    print("\n[5/7] Job cards")
    cards = calls.get(key_of("/api/jobcards"))
    card_ids = []
    if cards:
        try:
            card_ids = [c["id"] for c in json.loads(cards["body"]).get("cards", [])][:3]
        except Exception:
            pass
    for cid in card_ids:
        record("/api/jobcard/read", "POST", form=[("card_id", cid)], label=f"card {cid}")

    print("\n[6/7] Part check")
    urls = []
    for pool in ("wear_examples", "severity_examples"):
        for x in (parts or {}).get(pool, []) or []:
            u = x.get("url") if isinstance(x, dict) else x
            if isinstance(u, str) and u.startswith("/"):
                urls.append(u)
    for u in urls[:2]:
        record("/api/partcheck", "POST",
               form=[("library_url", u), ("part_no", ""), ("complaint", "")],
               label=f"part check {u.rsplit('/', 1)[-1]}")

    print("\n[7/7] Anomaly lab")
    for fault in ("condenser_fan_failure", "clogged_air_filter"):
        d = record("/api/anomaly", "POST", json_body={"fault": fault, "signal": "sensors"},
                   label=f"inject {fault}")
        if d:
            record("/api/anomaly/explain", "POST",
                   json_body={"fault": d.get("fault"), "signal": d.get("signal"), "seed": d.get("seed")},
                   label=f"explain {fault}")

    print("\nCollecting images and sounds")
    harvest_assets()


# --------------------------------------------------------------------------- build

SHIM = """
<script>
/* ---- FaultLens offline replay -------------------------------------------------
   Every answer below was recorded from the live Cloud Run service. This file calls
   nothing and needs no network. ------------------------------------------------ */
window.__FL_OFFLINE = true;
const __CALLS = __CALLS_JSON__;
const __ASSETS = __ASSETS_JSON__;
const __REC_AT = "__REC_AT__";

(function () {
  function bodyKey(init) {
    if (!init || !init.body) return "";
    if (typeof init.body === "string") {
      try { return JSON.stringify(JSON.parse(init.body)); } catch (e) { return init.body; }
    }
    if (init.body instanceof FormData) {
      const parts = [];
      for (const [k, v] of init.body.entries())
        parts.push(k + "=" + (v instanceof File ? "file:" + v.name : String(v)));
      return parts.sort().join("&");
    }
    return "";
  }
  function pathOf(url) {
    const s = (typeof url === "string" ? url : url.url);
    return s.replace(location.origin, "").replace(/^\\./, "");
  }
  function pick(method, path, bk) {
    const exact = method + " " + path + (bk ? " :: " + bk : "");
    if (__CALLS[exact]) return __CALLS[exact];
    const bare = method + " " + path;
    if (__CALLS[bare]) return __CALLS[bare];
    const pre = bare + " :: ";                       // same endpoint, different inputs
    for (const k in __CALLS) if (k.indexOf(pre) === 0) return __CALLS[k];
    return null;
  }
  window.fetch = function (url, init) {
    const path = pathOf(url);
    const method = ((init && init.method) || "GET").toUpperCase();
    const hit = pick(method, path, bodyKey(init));
    if (!hit) {
      return Promise.resolve(new Response(
        JSON.stringify({ detail: "Not part of this offline recording. Use the live service for this step." }),
        { status: 501, headers: { "Content-Type": "application/json" } }));
    }
    const wait = method === "GET" ? 40 : 450;        // a beat, so the stages visibly run
    return new Promise(function (ok) {
      setTimeout(function () {
        ok(new Response(hit.body, { status: hit.status,
          headers: { "Content-Type": hit.ct || "application/json" } }));
      }, wait);
    });
  };

  /* images, diagrams and sounds come from the same recording */
  function swap(el, attr) {
    const v = el.getAttribute(attr);
    if (!v || v.startsWith("data:")) return;
    const clean = v.replace(/&amp;/g, "&");
    if (__ASSETS[clean]) el.setAttribute(attr, __ASSETS[clean]);
  }
  function sweep(root) {
    if (!root || root.nodeType !== 1) return;
    if (root.tagName === "IMG" || root.tagName === "AUDIO" || root.tagName === "SOURCE") swap(root, "src");
    root.querySelectorAll && root.querySelectorAll("img,audio,source").forEach(function (e) { swap(e, "src"); });
  }
  new MutationObserver(function (ms) {
    ms.forEach(function (m) {
      m.addedNodes.forEach(sweep);
      if (m.type === "attributes") swap(m.target, "src");
    });
  }).observe(document.documentElement,
             { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
  /* ---- autopilot: replays the recorded job by clicking the real buttons ---- */
  const __PLAN = __PLAN_JSON__;
  const sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  async function settle(max) {
    const until = Date.now() + (max || 6000);
    while (Date.now() < until) {
      await sleep(120);
      const busy = document.querySelector(".thinking") ||
                   document.querySelector("#askBtn[disabled]");
      if (!busy) { await sleep(260); return; }
    }
  }
  function click(sel) {
    const el = document.querySelector(sel);
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.click(); return true; }
    return false;
  }

  async function autopilot(btn) {
    btn.disabled = true;
    const was = btn.textContent;
    for (let i = 0; i < __PLAN.length; i++) {
      const s = __PLAN[i];
      btn.textContent = "Replaying " + (i + 1) + " / " + __PLAN.length;
      if (s.t === "start") { click('[data-view="play"]') || click('a[href="#play"]'); await sleep(400); click("#newMystery"); }
      else if (s.t === "ask") { const a = document.querySelector("#askText"); if (a) a.value = ""; click("#askBtn"); }
      else if (s.t === "act") { click('.act[data-a="' + s.a + '"]') || click('[data-do="' + s.a + '"]'); }
      else if (s.t === "power") { click("#powerBtn"); }
      else if (s.t === "conclude") {
        click("#concludeBtn"); await sleep(500);
        const r = document.querySelector('#concludePanel input[value="' + s.a + '"]') ||
                  document.querySelector('#concludePanel input[type="radio"]');
        if (r) { r.checked = true; r.click(); }
        await sleep(250);
        const go = [].slice.call(document.querySelectorAll("#concludePanel button"))
                     .filter(function (b) { return /submit|diagnos/i.test(b.textContent); })[0];
        if (go) go.click();
      }
      await settle(s.t === "ask" ? 7000 : 4000);
    }
    btn.textContent = was; btn.disabled = false;
  }

  document.addEventListener("DOMContentLoaded", function () {
    sweep(document.body);
    const b = document.createElement("div");
    b.setAttribute("style", "background:#fff3e0;border-bottom:1px solid #f0c48a;color:#7a4a00;" +
      "font:13px/1.5 Arial,sans-serif;padding:9px 20px;display:flex;align-items:center;gap:14px;flex-wrap:wrap");
    const t = document.createElement("div");
    t.style.flex = "1";
    t.innerHTML = "<b>Offline replay.</b> Every answer on this page was recorded from the live " +
      "Cloud Run service on " + __REC_AT + " and saved into this file. Nothing here calls a model " +
      "or uses the network. Live service: __BASE__";
    b.appendChild(t);
    if (__PLAN.length) {
      const go = document.createElement("button");
      go.textContent = "\\u25b6  Play the recorded job";
      go.setAttribute("style", "background:#14202e;color:#fff;border:0;border-radius:8px;" +
        "padding:9px 15px;font:bold 13px Arial,sans-serif;cursor:pointer;white-space:nowrap");
      go.addEventListener("click", function () { autopilot(go); });
      b.appendChild(go);
    }
    document.body.insertBefore(b, document.body.firstChild);
  });
})();
</script>
"""


def autoplay_plan() -> list[dict]:
    """The recorded job, as a list of clicks the autopilot can replay."""
    plan: list[dict] = []
    for k in calls:
        if not k.startswith("POST /api/game/"):
            continue
        head, _, body = k.partition(" :: ")
        try:
            arg = json.loads(body) if body else {}
        except ValueError:
            arg = {}
        if head.endswith("/new"):
            plan.append({"t": "start"})
        elif head.endswith("/advise"):
            plan.append({"t": "ask"})
        elif head.endswith("/action"):
            plan.append({"t": "act", "a": arg.get("action", "")})
        elif head.endswith("/power"):
            plan.append({"t": "power"})
        elif head.endswith("/conclude"):
            plan.append({"t": "conclude", "a": arg.get("choice", "")})
    return plan


def build():
    if not INDEX.exists():
        print(f"\nCannot find {INDEX}. Run this from the project folder.")
        sys.exit(1)
    html = INDEX.read_text(encoding="utf-8")
    shim = (SHIM
            .replace("__CALLS_JSON__", json.dumps(calls))
            .replace("__ASSETS_JSON__", json.dumps(images))
            .replace("__PLAN_JSON__", json.dumps(autoplay_plan()))
            .replace("__REC_AT__", time.strftime("%d %B %Y, %H:%M"))
            .replace("__BASE__", BASE))
    if "</head>" in html:
        html = html.replace("</head>", shim + "\n</head>", 1)
    else:
        html = shim + html
    html = html.replace("<title>", "<title>Offline replay — ", 1)
    OUT.write_text(html, encoding="utf-8")
    mb = OUT.stat().st_size / 1024 / 1024
    print(f"\nWrote {OUT.name}  ({mb:.1f} MB, {len(calls)} recorded answers, {len(images)} assets)")
    print(f"Autopilot: {len(autoplay_plan())} steps of the recorded job.")
    print("Open it by double-clicking. Turn the wifi off and try it before you rely on it.")


if __name__ == "__main__":
    capture()
    build()
