"use strict";
const $ = (s) => document.querySelector(s),
  esc = (s) =>
    String(s ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
const categories = [
  "Todos",
  "Filmes",
  "Séries",
  "Animes",
  "Mangás",
  "Livros",
  "Jogos",
];
let db = {
  works: [],
  reviews: [],
  profile: { name: "Visitante", bio: "", avatar: "", staff: false },
  favorites: [],
  statuses: {},
  reports: [],
  users: [],
  blocked: [],
};
let session = false,
  category = "Todos",
  query = "",
  order = "score",
  reviewOrder = "likes",
  listStatus = "Quero ver / ler",
  adminTab = "Denúncias",
  rating = null;
function save() {}
function toast(t) {
  $("#toast").textContent = t;
  $("#toast").style.display = "block";
  clearTimeout(window.tt);
  window.tt = setTimeout(() => ($("#toast").style.display = "none"), 3500);
}
function modal(html) {
  $("#modal-content").innerHTML = html;
  $("#modal").showModal();
}
$(".close").onclick = () => $("#modal").close();
$("#modal").addEventListener("click", (e) => {
  if (e.target === $("#modal")) $("#modal").close();
});
const num = (n) =>
  Number(n).toLocaleString("pt-BR", { maximumFractionDigits: 1 });
const initials = (n) =>
  n
    .split(" ")
    .slice(0, 2)
    .map((s) => s[0])
    .join("")
    .toUpperCase();
const work = (id) => db.works.find((w) => w.id === Number(id));
const statusNames = [
  "Quero ver / ler",
  "Consumindo",
  "Finalizado",
  "Abandonado",
];
function avg(w) {
  return w.score;
}
function total(w) {
  return w.count;
}
function cover(w) {
  return `<a class="cover" style="--cover:${esc(w.color)}" href="#/obra/${w.id}">${w.poster ? `<img class="poster" src="${esc(w.poster)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}<span class="badge">${esc(w.category.toUpperCase())}</span><h3>${esc(w.title)}</h3></a>`;
}
function cards(ws) {
  return ws.length
    ? ws
        .map(
          (w) =>
            `<article>${cover(w)}<div class="card-meta"><div><a href="#/obra/${w.id}"><b>${esc(w.title)}</b></a><br><small>${w.year} · ${num(total(w))} avaliações</small></div><span class="score">${num(avg(w))}</span></div></article>`,
        )
        .join("")
    : '<p class="empty">Nenhuma obra encontrada.</p>';
}
function guard() {
  if (session) return true;
  location.hash = "/entrar";
  toast("Entre na sua conta para interagir.");
  return false;
}
function updateAccount() {}
function logout() {}
function catalog() {
  let ws = db.works.filter(
    (w) =>
      (category === "Todos" || w.category === category) &&
      w.title
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .includes(
          query
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase(),
        ),
  );
  ws.sort((a, b) =>
    order === "year"
      ? b.year - a.year
      : order === "count"
        ? total(b) - total(a)
        : avg(b) - avg(a),
  );
  $("#app").innerHTML =
    `<section class="hero"><p class="eyebrow">FILMES · SÉRIES · ANIMES · MANGÁS · LIVROS · JOGOS</p><h1>Tudo o que você assiste, lê e joga. Avaliado por quem consome.</h1><form class="search" id="search"><input aria-label="Buscar por título" placeholder="Busque por título: Frieren, Elden Ring, Torto Arado..." value="${esc(query)}"><button class="primary">Buscar</button></form></section><div class="toolbar"><div class="chips">${categories.map((c) => `<button class="${category === c ? "active" : ""}" data-cat="${c}">${c}</button>`).join("")}</div><select class="sort" aria-label="Ordenar catálogo" id="order"><option value="score">Melhor nota</option><option value="year">Mais recentes</option><option value="count">Mais avaliadas</option></select></div><small>${ws.length} obras encontradas</small><div class="grid">${cards(ws)}</div><section class="section"><h2>Resenhas em alta</h2><div class="review-grid">${db.reviews
      .slice()
      .sort((a, b) => b.likes - a.likes)
      .slice(0, 3)
      .map((r) => review(r, true))
      .join("")}</div></section>`;
  $("#search").onsubmit = (e) => {
    e.preventDefault();
    query = e.target.querySelector("input").value.trim();
    catalog();
  };
  document.querySelectorAll("[data-cat]").forEach(
    (b) =>
      (b.onclick = () => {
        category = b.dataset.cat;
        catalog();
      }),
  );
  $("#order").value = order;
  $("#order").onchange = (e) => {
    order = e.target.value;
    catalog();
  };
}
function review(r, compact = false) {
  return `<article class="panel" id="review-${r.id}"><div class="review-head"><a class="avatar" href="#/usuario/${r.userId}">${esc(initials(r.name))}</a><div><b>${esc(r.name)}</b><small>${compact ? "sobre " + esc(work(r.work)?.title) : "na comunidade Resenha"}</small></div><span class="score">${num(r.score)}</span></div>${r.spoiler ? `<div class="spoiler" id="spoiler-${r.id}"><span>Contém spoilers. O texto revela detalhes da história.</span><button onclick="reveal('${r.id}')">Ler mesmo assim</button></div>` : `<p>${esc(r.text)}</p>`}${compact ? `<small>${num(r.likes)} curtidas · ${r.comments.length} respostas</small><br><a class="text-button" href="#/obra/${r.work}">Ver discussão →</a>` : `<div class="review-actions"><button onclick="like('${r.id}')" aria-pressed="${!!r.liked}">${r.liked ? "✓" : "↑"} ${r.likes}</button><button class="text-button" onclick="reply('${r.id}')">Responder</button><button class="text-button" onclick="share('${r.work}','${r.id}')">Compartilhar</button>${r.own ? `<button class="text-button" onclick="editReview('${r.id}')">Editar</button><button class="text-button" onclick="deleteOwn('${r.id}')">Excluir</button>` : ""}<button class="text-button report" onclick="report('${r.id}')">Denunciar</button></div>${r.comments.length ? `<div class="comments">${r.comments.map((c) => `<p><b>${esc(c.name)}</b><br>${esc(c.text)} <button class="text-button" onclick="reportComment(${c.id})">Denunciar</button>${c.own ? `<button class="text-button" onclick="deleteComment(${c.id})">Excluir</button>` : ""}</p>`).join("")}</div>` : ""}`}</article>`;
}
function detail(id) {
  const w = work(id);
  if (!w) {
    $("#app").innerHTML =
      '<h1>Obra não encontrada</h1><a href="#/">Voltar ao catálogo</a>';
    return;
  }
  let rs = db.reviews
    .filter((r) => r.work === w.id)
    .sort((a, b) =>
      reviewOrder === "likes" ? b.likes - a.likes : b.date - a.date,
    );
  $("#app").innerHTML =
    `<a class="back" href="#/">← Voltar ao catálogo</a><section class="detail">${cover(w)}<div><div class="row"><span class="muted">${esc(w.category)} · ${w.year}</span></div><h1>${esc(w.title)}</h1><p>${esc(w.synopsis)}</p><p><b>${["Filmes", "Séries", "Animes"].includes(w.category) ? "Direção / criação" : "Autoria / desenvolvimento"}:</b> ${esc(w.creator)}</p>${w.cast ? `<p><b>Elenco:</b> ${esc(w.cast)}</p>` : ""}<div class="panel rating"><div><small>Nota média</small><div class="big-score">${num(avg(w))}</div><small>${num(total(w))} avaliações</small></div><div class="bars">${distribution(
      w.id,
    )
      .map(
        ([l, p]) =>
          `<div class="bar"><span>${l}</span><i><em style="width:${p}%"></em></i><span>${p}%</span></div>`,
      )
      .join(
        "",
      )}<small>Distribuição das avaliações</small></div></div><label>Seu status</label><div class="row">${statusNames.map((s) => `<button class="${db.statuses[w.id] === s ? "active" : ""}" onclick="setStatus(${w.id},'${s}')">${s}</button>`).join("")}<button class="${db.favorites.includes(w.id) ? "active" : ""}" onclick="favorite(${w.id})">♡ ${db.favorites.includes(w.id) ? "Favorito" : "Favoritar"}</button></div><div class="row" style="margin-top:18px"><small>Compartilhar</small><button onclick="share(${w.id})">Copiar link</button><a class="text-button" href="https://wa.me/?text=${encodeURIComponent(w.title + " " + location.href)}" target="_blank" rel="noopener">WhatsApp ↗</a><a class="text-button" href="https://twitter.com/intent/tweet?text=${encodeURIComponent(w.title)}&url=${encodeURIComponent(location.href)}" target="_blank" rel="noopener">X / Twitter ↗</a></div></div></section><form class="panel" id="review-form"><h2>Sua resenha</h2>${session ? "" : '<p class="muted">Entre para publicar sua avaliação.</p>'}<label>Nota (0 a 10)</label><div class="row ratings">${Array.from({ length: 11 }, (_, n) => `<button type="button" data-rating="${n}" class="${rating === n ? "active" : ""}">${n}</button>`).join("")}</div><label for="review-text">Escreva o que achou</label><textarea id="review-text" required maxlength="5000" placeholder="O que funcionou, o que não funcionou, para quem você recomenda..."></textarea><div class="form-footer"><label class="check"><input type="checkbox" id="has-spoiler">Contém spoilers</label><button class="primary">Publicar resenha</button></div></form><div class="toolbar"><h2>Resenhas (${rs.length})</h2><select class="sort" id="review-order" aria-label="Ordenar resenhas"><option value="likes">Mais relevantes</option><option value="date">Mais recentes</option></select></div>${rs.map((r) => review(r)).join("") || '<p class="empty">Seja a primeira pessoa a avaliar esta obra.</p>'}`;
  document.querySelectorAll("[data-rating]").forEach(
    (b) =>
      (b.onclick = () => {
        rating = Number(b.dataset.rating);
        document
          .querySelectorAll("[data-rating]")
          .forEach((x) => x.classList.toggle("active", x === b));
      }),
  );
  $("#review-order").value = reviewOrder;
  $("#review-order").onchange = (e) => {
    reviewOrder = e.target.value;
    detail(w.id);
  };
}
function reveal(id) {
  const r = db.reviews.find((r) => r.id === id);
  $("#spoiler-" + id).innerHTML = `<p>${esc(r.text)}</p>`;
}
function like(id) {}
function reply(id) {}
async function share(id, rid) {
  const url =
    location.origin +
    location.pathname +
    "#/obra/" +
    id +
    (rid ? "?resenha=" + rid : "");
  try {
    await navigator.clipboard.writeText(url);
    toast("Link copiado.");
  } catch {
    modal(
      `<h2>Compartilhar</h2><input readonly value="${esc(url)}" onclick="this.select()">`,
    );
  }
}
function favorite(id) {}
function setStatus(id, s) {}
function report(id) {}
function editReview(id) {}
function deleteOwn(id) {}
function confirmAction(title, fn) {}
function profile(name) {
  const mine = !name;
  if (mine && !guard()) return;
  const pname = mine ? db.profile.name : decodeURIComponent(name),
    rs = db.reviews.filter((r) => (mine ? r.own : r.name === pname));
  $("#app").innerHTML =
    `<section class="profile-head"><div class="avatar" id="profile-avatar">${mine && db.profile.avatar ? `<img alt="Avatar" style="width:100%;height:100%;object-fit:cover;border-radius:50%" src="${esc(db.profile.avatar)}">` : esc(initials(pname))}</div><div class="profile-info"><h1>${esc(pname)}</h1><p class="muted">Comunidade Resenha</p><p>${esc(mine ? db.profile.bio : "")}</p><div class="row"><span><b>${rs.length}</b> resenhas</span><span><b>${rs.length ? num(rs.reduce((s, r) => s + r.score, 0) / rs.length) : "—"}</b> nota média dada</span><span><b>${rs.reduce((s, r) => s + r.likes, 0)}</b> curtidas recebidas</span></div></div>${mine ? '<button onclick="editProfile()">Editar perfil</button>' : ""}</section>${mine ? `<h2>Favoritos</h2><div class="grid">${cards(db.works.filter((w) => db.favorites.includes(w.id)))}</div><h2>Listas</h2><div class="chips">${statusNames.map((s) => `<button class="${s === listStatus ? "active" : ""}" onclick="listStatus='${s}';profile()">${s} ${Object.values(db.statuses).filter((x) => x === s).length}</button>`).join("")}</div><div class="grid">${cards(db.works.filter((w) => db.statuses[w.id] === listStatus))}</div>` : ""}<h2>Últimas resenhas</h2>${
      rs
        .slice()
        .reverse()
        .map(
          (r) =>
            `<div class="panel list-item"><div style="--cover:${work(r.work)?.color}" class="cover"></div><div><a href="#/obra/${r.work}"><b>${esc(work(r.work)?.title || "Obra removida")}</b></a><p>${r.spoiler ? "Contém spoilers — abra a obra para ler." : esc(r.text)}</p><small>${r.likes} curtidas</small></div><span class="score">${num(r.score)}</span></div>`,
        )
        .join("") || '<p class="empty">Nenhuma resenha publicada.</p>'
    }`;
}
function editProfile() {}
function auth(mode) {}
function admin() {}
function moderate(id, action) {}
function editWork(id) {
  if (!session) return;
  const w = work(id) || {
    title: "",
    category: "Filmes",
    year: new Date().getFullYear(),
    synopsis: "",
    creator: "",
    color: "#3a4551",
  };
  modal(
    `<h2>${id ? "Editar" : "Cadastrar"} obra</h2><form id="work-form"><label>Título<input name="title" required maxlength="150" value="${esc(w.title)}"></label><label>Categoria<select name="category">${categories
      .slice(1)
      .map((c) => `<option ${c === w.category ? "selected" : ""}>${c}</option>`)
      .join(
        "",
      )}</select></label><label>Ano<input name="year" type="number" min="1" max="2100" required value="${w.year}"></label><label>Autoria / direção<input name="creator" required maxlength="200" value="${esc(w.creator)}"></label><label>Sinopse<textarea name="synopsis" required maxlength="3000">${esc(w.synopsis)}</textarea></label><label>Cor da capa<input type="color" name="color" value="${esc(w.color)}"></label><button class="primary full">Salvar obra</button></form>`,
  );
}
function removeWork(id) {}
function render(scroll = true) {
  updateAccount();
  const hash = location.hash.slice(1) || "/",
    [path, params] = hash.split("?"),
    parts = path.split("/").filter(Boolean);
  if (!parts.length) catalog();
  else if (parts[0] === "obra") detail(parts[1]);
  else if (parts[0] === "perfil") profile();
  else if (parts[0] === "usuario") profile(parts[1]);
  else if (["entrar", "cadastro", "recuperar"].includes(parts[0]))
    auth(parts[0]);
  else if (parts[0] === "admin") admin();
  else
    $("#app").innerHTML =
      '<h1>Página não encontrada</h1><a href="#/">Voltar ao catálogo</a>';
  if (scroll) window.scrollTo(0, 0);
  if (params) {
    const id = new URLSearchParams(params).get("resenha");
    if (id) document.getElementById("review-" + id)?.scrollIntoView();
  }
}
window.addEventListener("hashchange", () => {
  rating = null;
  render();
});
