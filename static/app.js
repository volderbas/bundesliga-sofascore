const $ = (s) => document.querySelector(s);
const state = { tab: "live", league: "bundesliga", matchId: null, timer: null };

const fmtTime = (ts) =>
  new Date(ts * 1000).toLocaleString("tr-TR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t.slice(0, 200));
  }
  return r.json();
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.style.display = "block";
  setTimeout(() => (t.style.display = "none"), 4000);
}

/* ---------------- liste ---------------- */
async function loadList() {
  const el = $("#list");
  el.innerHTML = '<div class="empty">Yükleniyor…</div>';
  try {
    let events = [];
    if (state.tab === "live") events = (await api("/api/live")).events;
    else if (state.tab === "today") events = (await api(`/api/date/${new Date().toISOString().slice(0, 10)}`)).events;
    else if (state.tab === "upcoming") events = (await api("/api/upcoming?days=8")).events;
    else if (state.tab === "finished") events = (await api(`/api/league/${state.league}/events?kind=last`)).events;
    else return loadStandings();

    renderList(events);
  } catch (e) {
    el.innerHTML = `<div class="empty">Veri alınamadı.<br><small>${e.message}</small></div>`;
  }
}

function renderList(events) {
  const el = $("#list");
  if (!events.length) {
    el.innerHTML = '<div class="empty">Maç bulunamadı.</div>';
    return;
  }
  const groups = {};
  events.forEach((e) => {
    const k = e.league + (e.round ? ` · ${e.round}. Hafta` : "");
    (groups[k] ||= []).push(e);
  });
  el.innerHTML = Object.entries(groups)
    .map(
      ([g, list]) =>
        `<div class="grp">${g}</div>` +
        list
          .map((e) => {
            const live = e.status === "inprogress";
            const done = e.status === "finished";
            const score = done || live ? `${e.homeScore ?? 0}-${e.awayScore ?? 0}` : "-";
            return `<div class="match ${state.matchId === e.id ? "sel" : ""}" data-id="${e.id}">
              <div class="time ${live ? "livem" : ""}">${live ? "CANLI" : fmtTime(e.startTimestamp)}</div>
              <div class="teams"><div>${e.home.name}</div><div>${e.away.name}</div></div>
              <div class="score">${score}</div>
            </div>`;
          })
          .join("")
    )
    .join("");
  el.querySelectorAll(".match").forEach((n) =>
    n.addEventListener("click", () => openMatch(+n.dataset.id))
  );
}

/* ---------------- puan durumu ---------------- */
async function loadStandings() {
  const el = $("#list");
  try {
    const d = await api(`/api/league/${state.league}/standings`);
    const t = d.tables[0];
    el.innerHTML = `<div class="grp">${t?.name || "Puan Durumu"}</div>
      <table><thead><tr><th>#</th><th>Takım</th><th class="num">O</th><th class="num">A-B-M</th><th class="num">Av</th><th class="num">P</th></tr></thead><tbody>
      ${(t?.rows || [])
        .map(
          (r) => `<tr><td>${r.position}</td><td>${r.team}</td><td class="num">${r.matches}</td>
          <td class="num">${r.wins}-${r.draws}-${r.losses}</td>
          <td class="num">${r.scoresFor - r.scoresAgainst}</td><td class="num"><b>${r.points}</b></td></tr>`
        )
        .join("")}</tbody></table>`;
  } catch (e) {
    el.innerHTML = `<div class="empty">Puan durumu alınamadı.<br><small>${e.message}</small></div>`;
  }
}

/* ---------------- maç detayı ---------------- */
async function openMatch(id) {
  state.matchId = id;
  document.querySelectorAll(".match").forEach((n) => n.classList.toggle("sel", +n.dataset.id === id));
  const el = $("#detail");
  el.innerHTML = '<div class="empty">Maç detayı yükleniyor…</div>';
  try {
    renderDetail(await api(`/api/match/${id}`));
  } catch (e) {
    el.innerHTML = `<div class="empty">Detay alınamadı.<br><small>${e.message}</small></div>`;
  }
}

const icon = (i) => {
  if (i.type === "goal") return i.class === "ownGoal" ? "🥅" : i.class === "penalty" ? "🎯" : "⚽";
  if (i.type === "card") return i.class === "yellow" ? "🟨" : i.class === "yellowRed" ? "🟨🟥" : "🟥";
  if (i.type === "substitution") return "🔁";
  if (i.type === "period") return "⏱️";
  if (i.type === "injuryTime") return "➕";
  if (i.type === "varDecision") return "📺";
  return "•";
};

function evText(i) {
  if (i.type === "goal")
    return `<b>${i.player || ""}</b> ${i.class === "ownGoal" ? "(k.k.)" : i.class === "penalty" ? "(pen.)" : ""} ${
      i.assist ? `<span class="pos">asist: ${i.assist}</span>` : ""
    } <span class="pos">${i.homeScore}-${i.awayScore}</span>`;
  if (i.type === "card") return `<b>${i.player || ""}</b> ${i.reason ? `<span class="pos">${i.reason}</span>` : ""}`;
  if (i.type === "substitution")
    return `<b style="color:var(--green)">▲ ${i.playerIn || ""}</b><br><span style="color:var(--muted)">▼ ${i.playerOut || ""}</span>`;
  if (i.type === "period") return `<span style="color:var(--muted)">${i.text || "Devre"}</span>`;
  if (i.type === "injuryTime") return `<span style="color:var(--muted)">Uzatma +${i.addedTime}'</span>`;
  return i.text || i.description || i.type;
}

function playerRow(p) {
  const r = p.rating ? `<span class="rat ${p.rating >= 7.5 ? "hi" : p.rating < 6.3 ? "lo" : ""}">${p.rating}</span>` : "";
  return `<div class="pl"><span class="no">${p.jerseyNumber ?? ""}</span>
    <span>${p.name}${p.captain ? " (K)" : ""}</span>
    <span class="pos">${p.position ?? ""}</span>${r}</div>`;
}

function statBar(s) {
  const num = (v) => parseFloat(String(v).replace("%", "").split("/")[0]) || 0;
  const h = num(s.home), a = num(s.away), t = h + a || 1;
  return `<div class="statrow"><div><b>${s.home}</b></div>
    <div><div class="statname">${s.name}</div><div class="bar"><i class="h" style="width:${(h / t) * 100}%"></i><i class="a" style="width:${(a / t) * 100}%"></i></div></div>
    <div style="text-align:right"><b>${s.away}</b></div></div>`;
}

function renderDetail(d) {
  const s = d.summary || {};
  const lu = d.lineups;
  const el = $("#detail");
  const live = s.status === "inprogress";

  const side = (k, title) => {
    const x = lu?.[k];
    if (!x) return "";
    return `<div class="card"><h3>${title} — ${x.formation || "-"}</h3>
      <div><b style="font-size:12px;color:var(--muted)">İLK 11</b>${x.startXI.map(playerRow).join("")}</div>
      <div style="margin-top:10px"><b style="font-size:12px;color:var(--muted)">YEDEKLER</b>${
        x.bench.length ? x.bench.map(playerRow).join("") : '<div class="empty">-</div>'
      }</div>
      ${
        x.missingPlayers.length
          ? `<div style="margin-top:10px"><b style="font-size:12px;color:var(--muted)">EKSİKLER</b>${x.missingPlayers
              .map((m) => `<div class="pl"><span>${m.name}</span><span class="pos">${m.reason ?? ""}</span></div>`)
              .join("")}</div>`
          : ""
      }</div>`;
  };

  el.innerHTML = `
    <h2>${s.home?.name ?? ""} vs ${s.away?.name ?? ""}</h2>
    <div class="sub">${s.league ?? ""} ${s.round ? `· ${s.round}. Hafta` : ""} · ${
      s.startTimestamp ? fmtTime(s.startTimestamp) : ""
    } · <span class="badge">${s.statusText ?? ""}</span></div>

    <div class="hero">
      <div class="t">${s.home?.name ?? ""}</div>
      <div class="sc">${s.homeScore ?? "-"} : ${s.awayScore ?? "-"}</div>
      <div class="t">${s.away?.name ?? ""}</div>
    </div>

    <div class="card"><h3>Maç Bilgileri</h3><div class="kv">
      ${d.venue ? `<span>🏟️ ${d.venue}${d.city ? ", " + d.city : ""}</span>` : ""}
      ${d.referee ? `<span>🧑‍⚖️ ${d.referee}</span>` : ""}
      ${d.attendance ? `<span>👥 ${d.attendance.toLocaleString("tr-TR")}</span>` : ""}
      ${d.season ? `<span>📅 ${d.season}</span>` : ""}
      ${s.homeHalf != null ? `<span>İY: ${s.homeHalf}-${s.awayHalf}</span>` : ""}
      ${d.managers?.home ? `<span>👔 ${d.managers.home} / ${d.managers.away ?? ""}</span>` : ""}
      ${lu ? `<span>Kadro: ${d.lineupsConfirmed ? "onaylı" : "tahmini"}</span>` : ""}
      ${live ? '<span style="color:var(--accent-2)">● CANLI</span>' : ""}
    </div></div>

    <div class="card"><h3>Goller & Kartlar</h3>
      ${
        d.goals.length || d.cards.length
          ? [...d.goals, ...d.cards]
              .sort((a, b) => (a.time || 0) - (b.time || 0))
              .map(
                (i) =>
                  `<div class="ev ${i.isHome ? "" : "away"}"><div class="m">${i.time ?? ""}'${
                    i.addedTime ? "+" + i.addedTime : ""
                  }</div><div class="ic">${icon(i)}</div><div>${evText(i)}</div></div>`
              )
              .join("")
          : '<div class="empty">Henüz yok.</div>'
      }</div>

    <div class="card"><h3>Oyuncu Değişiklikleri</h3>
      ${
        d.substitutions.length
          ? d.substitutions
              .map(
                (i) =>
                  `<div class="ev ${i.isHome ? "" : "away"}"><div class="m">${i.time ?? ""}'</div><div class="ic">🔁</div><div>${evText(
                    i
                  )}</div></div>`
              )
              .join("")
          : '<div class="empty">Henüz yok.</div>'
      }</div>

    <div class="card"><h3>Olay Akışı</h3>
      ${
        d.incidents.length
          ? d.incidents
              .map(
                (i) =>
                  `<div class="ev ${i.isHome === false ? "away" : ""}"><div class="m">${
                    i.time != null ? i.time + "'" : ""
                  }</div><div class="ic">${icon(i)}</div><div>${evText(i)}</div></div>`
              )
              .join("")
          : '<div class="empty">Olay yok.</div>'
      }</div>

    <div class="two">${side("home", s.home?.name ?? "Ev")}${side("away", s.away?.name ?? "Deplasman")}</div>

    ${
      d.statistics?.length
        ? d.statistics
            .map(
              (p) =>
                `<div class="card"><h3>İstatistikler — ${
                  p.period === "ALL" ? "Maç Geneli" : p.period
                }</h3>${p.groups
                  .map((g) => `<div class="grp">${g.name}</div>` + g.items.map(statBar).join(""))
                  .join("")}</div>`
            )
            .join("")
        : ""
    }
  `;
  el.scrollTop = 0;
}

/* ---------------- olaylar ---------------- */
document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    state.tab = b.dataset.tab;
    loadList();
  })
);
$("#league").addEventListener("change", (e) => {
  state.league = e.target.value;
  loadList();
});
$("#refresh").addEventListener("click", () => {
  loadList();
  if (state.matchId) openMatch(state.matchId);
});

function tick() {
  clearInterval(state.timer);
  state.timer = setInterval(() => {
    if (!$("#auto").checked) return;
    loadList();
    if (state.matchId) openMatch(state.matchId);
  }, 30000);
}

loadList();
tick();
