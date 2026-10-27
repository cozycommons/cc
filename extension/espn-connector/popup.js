const API = "https://api.cozycommons.dev";

let found = { espn_s2: null, swid: null };
let mintedToken = null;

function decodeVal(v) {
  let value = v || "";
  try {
    value = decodeURIComponent(value);
  } catch (e) {
    /* keep the raw value */
  }
  return value.trim() || null;
}

function pickCookie(cookies, name) {
  const matches = cookies.filter((c) => c.name === name);
  if (!matches.length) return null;
  matches.sort(
    (a, b) => (a.domain === ".espn.com" ? 0 : 1) - (b.domain === ".espn.com" ? 0 : 1)
  );
  return decodeVal(matches[0].value);
}

function describe(c) {
  if (!c) return "miss";
  return (
    `HIT domain=${c.domain} path=${c.path} httpOnly=${!!c.httpOnly} ` +
    `sameSite=${c.sameSite || "?"} partition=${
      c.partitionKey ? JSON.stringify(c.partitionKey) : "none"
    } len=${(c.value || "").length}`
  );
}

async function refresh() {
  const el = document.getElementById("found");
  const btn = document.getElementById("connect");
  const diag = document.getElementById("diagpre");
  const lines = [];
  const pool = [];
  const addToPool = (cs) => {
    for (const c of cs || []) if (!pool.includes(c)) pool.push(c);
  };

  try {
    // --- broad sweep (same as v0.1.1) ---
    const stores = await chrome.cookies.getAllCookieStores();
    lines.push(`cookie stores: ${stores.map((s) => s.id).join(", ") || "(none)"}`);
    for (const store of stores) {
      const queries = [
        { storeId: store.id, url: "https://www.espn.com/" },
        { storeId: store.id, url: "https://fantasy.espn.com/" },
        { storeId: store.id, domain: "espn.com" },
        { storeId: store.id },
      ];
      for (const q of queries) {
        const via = q.url
          ? `url:${new URL(q.url).host}`
          : q.domain
            ? `domain:${q.domain}`
            : "all";
        try {
          const cs = await chrome.cookies.getAll(q);
          addToPool(cs.filter((c) => /espn/i.test(c.domain)));
          lines.push(`sweep store ${store.id} · ${via}: ${cs.length} cookies`);
        } catch (e) {
          lines.push(`sweep store ${store.id} · ${via}: ERROR ${e && e.message ? e.message : e}`);
        }
      }
    }

    // --- deep probe 1: by name across everything we can access ---
    for (const name of ["espn_s2", "SWID"]) {
      try {
        const cs = await chrome.cookies.getAll({ name });
        addToPool(cs);
        lines.push(
          `by-name getAll({name:"${name}"}): ${cs.length} hit(s)` +
            (cs.length ? ` [${cs.map(describe).join(" | ")}]` : "")
        );
      } catch (e) {
        lines.push(`by-name ${name}: ERROR ${e && e.message ? e.message : e}`);
      }
    }

    // --- deep probe 2: direct get by name+url ---
    const urls = [
      "https://fantasy.espn.com/",
      "https://www.espn.com/",
      "https://espn.com/",
    ];
    for (const name of ["espn_s2", "SWID"]) {
      for (const url of urls) {
        try {
          const c = await chrome.cookies.get({ url, name });
          if (c) addToPool([c]);
          lines.push(`get ${name} @ ${new URL(url).host}: ${describe(c)}`);
        } catch (e) {
          lines.push(`get ${name} @ ${new URL(url).host}: ERROR ${e && e.message ? e.message : e}`);
        }
      }
    }

    // --- deep probe 3: partitioned (CHIPS) queries ---
    const tops = ["https://fantasy.espn.com", "https://www.espn.com", "https://espn.com"];
    for (const top of tops) {
      try {
        const cs = await chrome.cookies.getAll({ partitionKey: { topLevelSite: top } });
        const espn = cs.filter((c) => /espn/i.test(c.domain));
        addToPool(espn);
        lines.push(
          `partitioned getAll topLevelSite=${top}: ${cs.length} cookies, ${espn.length} espn` +
            (espn.length
              ? ` [${espn.map((c) => `${c.name}@${c.domain}`).join(", ")}]`
              : "")
        );
      } catch (e) {
        lines.push(`partitioned ${top}: ERROR ${e && e.message ? e.message : e}`);
      }
      for (const name of ["espn_s2", "SWID"]) {
        try {
          const c = await chrome.cookies.get({
            url: "https://fantasy.espn.com/",
            name,
            partitionKey: { topLevelSite: top },
          });
          if (c) addToPool([c]);
          lines.push(`partitioned get ${name} top=${top}: ${describe(c)}`);
        } catch (e) {
          lines.push(
            `partitioned get ${name} top=${top}: ERROR ${e && e.message ? e.message : e}`
          );
        }
      }
    }
  } catch (e) {
    lines.push(`diagnostics error: ${e && e.message ? e.message : e}`);
  }
  diag.textContent = lines.join("\n");

  found.espn_s2 = pickCookie(pool, "espn_s2");
  found.swid = pickCookie(pool, "SWID") || pickCookie(pool, "swid");
  if (found.espn_s2 && found.swid) {
    el.innerHTML =
      'ESPN cookies found: espn_s2 <span class="ok">✓</span> · SWID <span class="ok">✓</span>';
    btn.disabled = false;
  } else {
    el.innerHTML =
      'ESPN cookies <span class="err">not found</span> — diagnostics below show what the browser returned.';
    btn.disabled = true;
  }
}

document.getElementById("connect").addEventListener("click", async () => {
  const status = document.getElementById("status");
  const tokenBox = document.getElementById("token");
  const btn = document.getElementById("connect");
  btn.disabled = true;
  status.className = "";
  status.textContent = "Sending cookies to Cozy Commons…";
  tokenBox.style.display = "none";
  document.getElementById("copy").style.display = "none";
  mintedToken = null;
  try {
    const res = await fetch(`${API}/espn/onboard`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        label: document.getElementById("label").value || "ext-prototype",
        league_id: Number(document.getElementById("league").value),
        season: Number(document.getElementById("season").value),
        espn_s2: found.espn_s2,
        swid: found.swid,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);

    let autoNote = "";
    if (document.getElementById("automation").checked && body.token) {
      try {
        const r2 = await fetch(`${API}/espn/automation/lineup`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${body.token}`,
          },
          body: JSON.stringify({ enabled: true }),
        });
        autoNote = r2.ok
          ? "\nAutomatic lineups: enabled."
          : "\nAutomatic lineups: could not enable (can be retried later).";
      } catch (e) {
        autoNote = "\nAutomatic lineups: could not enable (can be retried later).";
      }
    }

    status.className = "ok";
    status.textContent = `Connected. Account ${body.id} · league ${body.league_id}.${autoNote}\nSave this token now — it is shown once:`;
    tokenBox.textContent = body.token;
    tokenBox.style.display = "block";
    mintedToken = body.token;
    const copyBtn = document.getElementById("copy");
    copyBtn.textContent = "Copy token";
    copyBtn.style.display = "block";
  } catch (e) {
    status.className = "err";
    status.textContent = `Failed: ${e.message}`;
    btn.disabled = false;
  }
});

document.getElementById("copy").addEventListener("click", async () => {
  const btn = document.getElementById("copy");
  const tokenBox = document.getElementById("token");
  const token = mintedToken || tokenBox.textContent;
  const flash = (msg) => {
    btn.textContent = msg;
    setTimeout(() => {
      btn.textContent = "Copy token";
    }, 2000);
  };
  try {
    await navigator.clipboard.writeText(token);
    flash("Copied ✓");
  } catch (e) {
    // Clipboard API unavailable (focus/permission): select the token text so
    // Cmd+C / Ctrl+C works, and try the legacy copy command first.
    const range = document.createRange();
    range.selectNodeContents(tokenBox);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (err) {
      ok = false;
    }
    flash(ok ? "Copied ✓" : "Token selected — press Cmd+C / Ctrl+C");
  }
});

refresh();
