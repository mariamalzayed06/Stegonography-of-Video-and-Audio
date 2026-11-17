// Steganography website front end: talks to the Flask API and draws the results.
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (n) => Number(n).toLocaleString();

// ---- tabs
$$(".tab").forEach((t) => t.addEventListener("click", () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === t.dataset.tab));
}));

// ---- drag and drop on every drop box
$$(".drop").forEach((d) => {
  const input = d.querySelector("input");
  ["dragenter", "dragover"].forEach((e) => d.addEventListener(e, (ev) => { ev.preventDefault(); d.classList.add("over"); }));
  ["dragleave", "drop"].forEach((e) => d.addEventListener(e, () => d.classList.remove("over")));
  d.addEventListener("drop", (ev) => {
    ev.preventDefault();
    if (ev.dataTransfer.files.length) { input.files = ev.dataTransfer.files; input.dispatchEvent(new Event("change")); }
  });
});

function status(el, html, cls = "") { el.className = "status " + cls; el.innerHTML = html; }
const busy = (t) => `<span class="spinner"></span>${t}`;

async function post(url, fd) {
  const r = await fetch(url, { method: "POST", body: fd });
  let j;
  try { j = await r.json(); } catch { throw new Error("The server had a problem (error " + r.status + "). Check the terminal where app.py is running."); }
  if (!j.ok) throw new Error(j.error || "Something went wrong.");
  return j;
}

// ---- HIDE
let carrierInfo = null, secretMode = "text";

$("#carrier").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const box = $("#carrier-info");
  box.classList.remove("hidden");
  box.innerHTML = busy("Reading " + esc(f.name) + "…");
  $("#drop-carrier .drop-main").textContent = f.name;
  const fd = new FormData(); fd.append("carrier", f);
  try {
    carrierInfo = await post("/api/info", fd);
    const i = carrierInfo;
    const rows = i.kind === "audio"
      ? [["Type", "Audio"], ["Length", i.duration + " seconds"], ["Sample rate", fmt(i.rate) + " Hz"], ["Channels", i.channels]]
      : [["Type", "Video"], ["Size", i.width + " × " + i.height], ["Frames", fmt(i.frames) + " (" + i.fps.toFixed(0) + " per second)"],
         ["Length", i.duration + " seconds"], ["Sound", i.has_audio ? "yes, it will be kept" : "no sound track"]];
    rows.push(["Room for a secret", `${i.capacity_h[1]} at 1 bit, up to ${i.capacity_h[4]} at 4 bits`]);
    box.innerHTML = `<table>${rows.map(([a, b]) => `<tr><td>${a}</td><td>${b}</td></tr>`).join("")}</table>`;
  } catch (err) { carrierInfo = null; box.innerHTML = `<span style="color:var(--bad)">${esc(err.message)}</span>`; }
  updateFit();
});

$$(".seg-b").forEach((b) => b.addEventListener("click", () => {
  secretMode = b.dataset.secret;
  $$(".seg-b").forEach((x) => x.classList.toggle("active", x === b));
  $("#secret-text").classList.toggle("hidden", secretMode !== "text");
  $("#secret-file").classList.toggle("hidden", secretMode !== "file");
  updateFit();
}));

$("#message").addEventListener("input", () => {
  $("#msg-bytes").textContent = fmt(new TextEncoder().encode($("#message").value).length);
  updateFit();
});

$("#secret-input").addEventListener("change", (e) => {
  const f = e.target.files[0], p = $("#secret-preview");
  if (!f) { p.innerHTML = ""; return; }
  p.innerHTML = `<b>${esc(f.name)}</b>, ${fmt(f.size)} bytes`;
  if (f.type.startsWith("image/")) { const img = new Image(); img.src = URL.createObjectURL(f); img.alt = f.name; p.appendChild(img); }
  updateFit();
});

$("#bits").addEventListener("input", () => { $("#bits-val").textContent = $("#bits").value; updateFit(); });

function secretSize() {
  if (secretMode === "text") return new TextEncoder().encode($("#message").value).length;
  const f = $("#secret-input").files[0]; return f ? f.size : 0;
}

function updateFit() {
  const k = +$("#bits").value, fill = $("#meter-fill"), note = $("#fit-note");
  $("#bits-note").textContent = {
    1: "1 is the safest. More bits give more room but add more noise.",
    2: "2 bits: still impossible to hear or see.",
    3: "3 bits: very quiet noise, but easier for detection tools to spot.",
    4: "4 bits: the most room. You might start to hear faint hiss on quiet audio.",
  }[k];
  if (!carrierInfo) { fill.style.width = "0"; note.textContent = "Pick a file in step 1 to see how much fits."; return; }
  const cap = carrierInfo.capacity[k], need = secretSize() + 64; // rough overhead for header + encryption
  const pct = Math.min(100, (100 * need) / cap);
  fill.style.width = Math.max(pct, need > 64 ? 1 : 0) + "%";
  fill.classList.toggle("full", need > cap);
  note.innerHTML = need > cap
    ? `<span style="color:var(--bad)">That’s too big for this file at ${k} bit${k > 1 ? "s" : ""} (room for ${carrierInfo.capacity_h[k]}). Try more bits or a longer file. Compression might still squeeze it in.</span>`
    : `Your secret will use about ${pct < 0.01 ? "less than 0.01" : pct.toFixed(2)}% of the ${carrierInfo.capacity_h[k]} available.`;
}

$("#btn-hide").addEventListener("click", async () => {
  const st = $("#hide-status"), res = $("#hide-result"), btn = $("#btn-hide");
  const c = $("#carrier").files[0];
  if (!c) return status(st, "Pick a song or video in step 1 first.", "err");
  const fd = new FormData();
  fd.append("carrier", c);
  if (carrierInfo) fd.append("kind", carrierInfo.kind);
  fd.append("password", $("#password").value);
  fd.append("bits", $("#bits").value);
  if (secretMode === "file") {
    const f = $("#secret-input").files[0];
    if (!f) return status(st, "Choose the picture or file you want to hide.", "err");
    fd.append("secret_file", f);
  } else fd.append("message", $("#message").value);

  btn.disabled = true; res.classList.add("hidden");
  const isVideo = carrierInfo && carrierInfo.kind === "video";
  status(st, busy(isVideo ? "Hiding… videos take a little while because every frame gets saved again." : "Hiding…"));
  try {
    const r = await post("/api/hide", fd);
    status(st, `Hidden in ${r.seconds} s${r.encrypted ? ", with encryption" : ""}. Download your file below.`, "ok");
    renderHide(r); res.classList.remove("hidden");
    res.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) { status(st, esc(err.message), "err"); }
  btn.disabled = false;
});

function bitsHTML(bits, k, other) {
  return bits.split("").map((b, i) => {
    const low = i >= bits.length - k, chg = other && other[i] !== b;
    return chg ? `<span class="chg">${b}</span>` : low ? `<span class="lo">${b}</span>` : b;
  }).join("");
}

function renderHide(r) {
  const s = r.stats, m = r.metric;
  const q = m.value === null ? "perfect (no change)" : m.value + " dB";
  const qHelp = r.kind === "audio" ? "anything above 60 dB is impossible to hear" : "anything above 40 dB is impossible to see";
  const facts = [
    [r.kind === "audio" ? "Sound quality (SNR)" : "Picture quality (PSNR)", `<b>${q}</b>, ${qHelp}`],
    ["Hidden data", `<b>${fmt(s.payload_bytes)} bytes</b> (your ${r.secret_size} secret, compressed${r.encrypted ? " and encrypted" : ""}, plus a small header)`],
    ["Room used", `<b>${s.used_percent}%</b> of ${fmt(s.capacity)} bytes at ${r.bits} bit${r.bits > 1 ? "s" : ""} per sample`],
    r.kind === "audio"
      ? ["Samples changed", `<b>${fmt(s.samples_changed)}</b> of the ${fmt(s.samples_used)} we wrote to (the rest already had the right bit)`]
      : ["Frames used", `<b>${fmt(s.frames_used)}</b> of ${fmt(s.frames)}`],
    ["File size", `${r.in_size} before, ${r.out_size} after (lossless formats are bigger)`],
  ];
  let html = `<h2>Your new ${r.kind === "audio" ? "audio" : "video"} file</h2>
    <p class="help">Keep it as <b>${esc(r.filename)}</b>. Converting it to another format will erase the secret.</p>
    <a class="dl" href="${r.download}">Download ${esc(r.filename)}</a>
    <ul class="facts">${facts.map(([k, v]) => `<li><span class="k">${k}</span><span>${v}</span></li>`).join("")}</ul>`;

  if (r.kind === "audio") {
    html += `<h3>Listen to it</h3><p class="help">It should sound exactly like the original.</p>
      <audio class="media" controls src="${r.preview}"></audio>
      <h3>What changed in the waveform</h3>
      <div class="figs wide"><figure><img src="${r.figures.wave}" alt="Original and stego waveforms with the difference underneath">
      <figcaption>The top two plots are the original and the new file. The bottom plot is the difference: tiny steps of at most ±${(1 << r.bits) - 1}.</figcaption></figure></div>
      <h3>The actual bits</h3>
      <p class="help">The first few samples we changed. The last ${r.bits} bit${r.bits > 1 ? "s are" : " is"} underlined; <span class="hl">highlighted</span> bits are the ones that flipped.</p>
      <table><thead><tr><th>Sample #</th><th>Before</th><th>Bits before</th><th>After</th><th>Bits after</th></tr></thead><tbody>
      ${r.figures.bit_rows.map((x) => `<tr><td>${fmt(x.index)}</td><td>${x.orig}</td><td class="bitcell">${bitsHTML(x.orig_bits, r.bits)}</td>
        <td>${x.stego}</td><td class="bitcell">${bitsHTML(x.stego_bits, r.bits, x.orig_bits)}</td></tr>`).join("")}</tbody></table>`;
  } else {
    const f = r.figures;
    html += `<h3>Watch it</h3>
      <p class="help">This preview is a normal MP4 so your browser can play it. It doesn’t contain the secret. Use the MKV you downloaded.</p>
      <video class="media" controls src="${r.preview}"></video>
      <h3>What changed in the first frame</h3>
      <div class="figs">
        <figure><img src="${f.orig}" alt="Original first frame"><figcaption>Before</figcaption></figure>
        <figure><img src="${f.stego}" alt="First frame with the secret"><figcaption>After. Looks the same.</figcaption></figure>
        <figure><img src="${f.lsb_orig}" alt="Lowest bit of the green channel, original"><figcaption>Just the last bit of each pixel (green), before. You can still see shapes.</figcaption></figure>
        <figure><img src="${f.lsb_stego}" alt="Lowest bit of the green channel after hiding"><figcaption>Same thing after hiding. Where the data went, it turns into noise.</figcaption></figure>
      </div>
      <div class="figs" style="margin-top:14px"><figure><img src="${f.diff}" alt="Map of changed pixels"><figcaption>Pixels that changed: ${f.changed_pixels_percent}% of the frame, scattered by your password.</figcaption></figure></div>`;
  }
  $("#hide-result").innerHTML = html;
}

// ---- EXTRACT
$("#x-carrier").addEventListener("change", (e) => { const f = e.target.files[0]; if (f) $("#x-name").textContent = f.name; });

$("#btn-extract").addEventListener("click", async () => {
  const st = $("#x-status"), out = $("#x-result"), btn = $("#btn-extract");
  const f = $("#x-carrier").files[0];
  if (!f) return status(st, "Choose the file first.", "err");
  const fd = new FormData(); fd.append("carrier", f); fd.append("password", $("#x-password").value);
  btn.disabled = true; status(st, busy("Looking for hidden bits…")); out.innerHTML = "";
  try {
    const r = await post("/api/extract", fd);
    status(st, `Found it (${r.size}).`, "ok");
    if (r.type === "text") {
      out.innerHTML = `<div class="secret-text">${esc(r.text)}</div><button class="ghost" id="copy-btn">Copy text</button>`;
      $("#copy-btn").onclick = () => { navigator.clipboard.writeText(r.text); $("#copy-btn").textContent = "Copied"; };
    } else {
      out.innerHTML = `<div class="recovered"><b>${esc(r.filename)}</b>, ${r.size}
        ${r.mime.startsWith("image/") ? `<img src="${r.url}" alt="The recovered picture">` : ""}
        ${r.mime.startsWith("audio/") ? `<audio class="media" controls src="${r.url}"></audio>` : ""}
        ${r.mime.startsWith("video/") ? `<video class="media" controls src="${r.url}"></video>` : ""}
        <p><a class="dl" href="${r.download}">Download ${esc(r.filename)}</a></p></div>`;
    }
  } catch (err) { status(st, esc(err.message), "err"); }
  btn.disabled = false;
});

// ---- LEARN: the bit demo
function demo() {
  const bitsN = +$("#d-type").value, slider = $("#d-val");
  slider.max = bitsN === 8 ? 255 : 65535;
  if (+slider.value > +slider.max) slider.value = slider.max;
  const v = +slider.value;
  const sec = ($("#d-secret").value.match(/[01]/g) || ["0"]).join("").slice(0, 4);
  const k = sec.length, mask = (1 << k) - 1;
  const s = (v & ~mask) | parseInt(sec, 2);
  const ob = v.toString(2).padStart(bitsN, "0"), sb = s.toString(2).padStart(bitsN, "0");
  const cells = (b, cmp) => b.split("").map((c, i) => `<span class="${i >= bitsN - k ? (cmp && cmp[i] !== c ? "flip" : "low") : ""}">${c}</span>`).join("");
  $("#d-val-t").textContent = v;
  $("#d-orig").innerHTML = cells(ob); $("#d-stego").innerHTML = cells(sb, ob);
  $("#d-orig-v").textContent = "= " + v; $("#d-stego-v").textContent = "= " + s;
  const diff = Math.abs(s - v), range = bitsN === 8 ? 255 : 65535;
  $("#d-note").innerHTML = diff === 0
    ? `The last bit${k > 1 ? "s" : ""} already matched <b>${sec}</b>, so nothing changed. That happens about half the time.`
    : `Writing <b>${sec}</b> changed the value by <b>${diff}</b>, which is ${(100 * diff / range).toFixed(4)}% of the full range.`;
}
["#d-type", "#d-val", "#d-secret"].forEach((id) => $(id).addEventListener("input", demo));
demo();