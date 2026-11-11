/* Adaptador HTTP: os dados e as permissões são controlados pelo Django. */
let csrf = "";
async function apiCall(route, method = "GET", data) {
  const result = await fetch("/api/" + route, {
    method,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
  });
  let payload;
  try {
    payload = await result.json();
  } catch {
    throw Error("Não foi possível processar a resposta do servidor.");
  }
  if (!result.ok)
    throw Error(payload.error || "Não foi possível concluir a operação.");
  if (payload.csrf) csrf = payload.csrf;
  return payload;
}
async function refresh(scroll = false) {
  const state = await apiCall("state");
  db = state;
  session = state.authenticated;
  csrf = state.csrf;
  render(scroll);
}
async function run(action) {
  try {
    await action();
  } catch (e) {
    toast(e.message || "Erro ao comunicar com o servidor.");
  }
}
function distribution(id) {
  const rs = db.reviews.filter((r) => r.work === id);
  return [
    ["9–10", 9, 10],
    ["7–8", 7, 8.999],
    ["5–6", 5, 6.999],
    ["0–4", 0, 4.999],
  ].map(([label, min, max]) => [
    label,
    rs.length
      ? Math.round(
          (rs.filter((r) => r.score >= min && r.score <= max).length /
            rs.length) *
            100,
        )
      : 0,
  ]);
}
updateAccount = function () {
  $("#account").innerHTML = session
    ? `<a href="#/perfil" class="avatar" aria-label="Meu perfil">${esc(initials(db.profile.name))}</a><button class="text-button" onclick="logout()">Sair</button>`
    : '<a href="#/entrar">Entrar</a><button class="primary" onclick="location.hash=\'/cadastro\'">Criar conta</button>';
  $("#admin-link").hidden = !db.profile.staff;
};
logout = function () {
  run(async () => {
    await apiCall("logout", "POST", {});
    location.hash = "/";
    await refresh();
  });
};
auth = function (mode) {
  const signup = mode === "cadastro",
    recover = mode === "recuperar";
  $("#app").innerHTML =
    `<section class="auth"><aside class="auth-aside"><h1>Sua opinião é o destaque.</h1><p>Dê notas de 0 a 10 e escreva resenhas</p><p>Responda e curta as resenhas da comunidade</p><p>Monte suas listas e favoritos no perfil</p><a href="#/" style="margin-top:40px;text-decoration:underline">Continuar sem conta →</a></aside><div class="auth-form"><div class="row"><a class="text-button" href="#/entrar">Entrar</a><a class="text-button" href="#/cadastro">Criar conta</a></div><h2 style="margin-top:30px">${recover ? "Recuperar senha" : signup ? "Faça parte da conversa" : "Bem-vindo de volta"}</h2><form id="auth-form">${signup ? '<label>Nome<input name="displayName" required maxlength="80" autocomplete="name"></label>' : ""}<label>E-mail<input type="email" name="email" required autocomplete="email" placeholder="voce@email.com"></label>${recover ? "" : `<label>Senha<input name="password" type="password" required minlength="8" maxlength="128" autocomplete="${signup ? "new-password" : "current-password"}"></label>`}<button class="primary full">${recover ? "Solicitar recuperação" : signup ? "Criar conta" : "Entrar"}</button></form>${!recover ? '<a class="text-button" style="display:block;margin-top:15px" href="#/recuperar">Esqueci minha senha</a>' : ""}</div></section>`;
  $("#auth-form").onsubmit = (e) => {
    e.preventDefault();
    const f = e.target,
      button = f.querySelector("button");
    run(async () => {
      button.disabled = true;
      try {
        const payload = {
          email: f.email.value,
          ...(recover ? {} : { password: f.password.value }),
          ...(signup ? { name: f.displayName.value } : {}),
        };
        const result = await apiCall(
          recover ? "password-reset" : signup ? "register" : "login",
          "POST",
          payload,
        );
        if (recover) {
          toast(result.message);
          return;
        }
        f.reset();
        await refresh();
        location.hash = "/perfil";
      } finally {
        button.disabled = false;
      }
    });
  };
};
const drawDetail = detail;
detail = function (id) {
  drawDetail(id);
  if (!work(id)) return;
  $("#review-form").onsubmit = (e) => {
    e.preventDefault();
    if (!guard()) return;
    if (rating === null) return toast("Escolha uma nota de 0 a 10.");
    const payload = {
      work: Number(id),
      score: rating,
      text: $("#review-text").value.trim(),
      spoiler: $("#has-spoiler").checked,
    };
    run(async () => {
      await apiCall("reviews", "POST", payload);
      rating = null;
      await refresh();
      toast("Resenha publicada.");
    });
  };
};
like = function (id) {
  if (!guard()) return;
  run(async () => {
    await apiCall("reviews/" + id + "/like", "POST", {});
    await refresh();
  });
};
favorite = function (id) {
  if (!guard()) return;
  run(async () => {
    await apiCall("library/" + id, "PATCH", {
      favorite: !db.favorites.includes(id),
    });
    await refresh();
  });
};
setStatus = function (id, s) {
  if (!guard()) return;
  run(async () => {
    await apiCall("library/" + id, "PATCH", {
      status: db.statuses[id] === s ? "" : s,
    });
    await refresh();
  });
};
reply = function (id) {
  if (!guard()) return;
  modal(
    '<h2>Responder à resenha</h2><form id="reply-form"><label for="reply-text">Comentário</label><textarea id="reply-text" required maxlength="2000"></textarea><button class="primary full">Publicar resposta</button></form>',
  );
  $("#reply-form").onsubmit = (e) => {
    e.preventDefault();
    const text = $("#reply-text").value;
    run(async () => {
      await apiCall("reviews/" + id + "/comments", "POST", { text });
      $("#modal").close();
      await refresh();
    });
  };
};
function reportTarget(payload) {
  if (!guard()) return;
  modal(
    '<h2>Denunciar conteúdo</h2><form id="report-form"><label for="reason">Motivo</label><select id="reason"><option>Ofensa</option><option>Spam</option><option>Spoiler sem aviso</option><option>Outro</option></select><label for="context">Informações adicionais</label><textarea id="context" maxlength="1000"></textarea><button class="primary full">Enviar denúncia</button></form>',
  );
  $("#report-form").onsubmit = (e) => {
    e.preventDefault();
    run(async () => {
      await apiCall("reports", "POST", {
        ...payload,
        reason: $("#reason").value,
        context: $("#context").value,
      });
      $("#modal").close();
      toast("Denúncia enviada para moderação.");
    });
  };
}
report = function (id) {
  reportTarget({ review: Number(id) });
};
function reportComment(id) {
  reportTarget({ comment: id });
}
function deleteComment(id) {
  confirmAction("Excluir comentário?", () =>
    run(async () => {
      await apiCall("comments/" + id, "DELETE");
      await refresh();
    }),
  );
}
editReview = function (id) {
  const r = db.reviews.find((r) => r.id === id);
  if (!session || !r?.own) return;
  modal(
    `<h2>Editar resenha</h2><form id="edit-review"><label>Nota<input name="score" type="number" min="0" max="10" step="0.1" required value="${r.score}"></label><label>Texto<textarea name="text" required maxlength="5000">${esc(r.text)}</textarea></label><label class="check"><input name="spoiler" type="checkbox" ${r.spoiler ? "checked" : ""}>Contém spoilers</label><button class="primary full">Salvar alterações</button></form>`,
  );
  $("#edit-review").onsubmit = (e) => {
    e.preventDefault();
    const f = e.target;
    run(async () => {
      await apiCall("reviews/" + id, "PATCH", {
        score: Number(f.score.value),
        text: f.text.value,
        spoiler: f.spoiler.checked,
      });
      $("#modal").close();
      await refresh();
    });
  };
};
deleteOwn = function (id) {
  confirmAction("Excluir sua resenha?", () =>
    run(async () => {
      await apiCall("reviews/" + id, "DELETE");
      await refresh();
    }),
  );
};
confirmAction = function (title, fn, message) {
  modal(
    `<h2>${esc(title)}</h2><p>${esc(message || "Confirme para continuar.")}</p><button class="primary" id="confirm">Confirmar</button>`,
  );
  $("#confirm").onclick = () => {
    $("#modal").close();
    fn();
  };
};
editProfile = function () {
  if (!guard()) return;
  modal(
    `<h2>Editar perfil</h2><form id="profile-form"><label>Nome<input name="displayName" required maxlength="80" value="${esc(db.profile.name)}"></label><label>Biografia<textarea name="bio" maxlength="300">${esc(db.profile.bio)}</textarea></label><label>Foto<input type="file" accept="image/png,image/jpeg,image/webp" name="photo"></label><small>PNG, JPEG ou WebP, até 1 MB.</small><button class="primary full">Salvar perfil</button></form>`,
  );
  $("#profile-form").onsubmit = (e) => {
    e.preventDefault();
    const f = e.target;
    run(async () => {
      const photo = f.photo.files[0],
        payload = { name: f.displayName.value, bio: f.bio.value };
      if (photo) {
        if (photo.size > 1048576)
          throw Error("Escolha uma imagem de até 1 MB.");
        payload.avatar = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = reject;
          reader.readAsDataURL(photo);
        });
      }
      await apiCall("profile", "PATCH", payload);
      $("#modal").close();
      await refresh();
    });
  };
};
const drawProfile = profile;
profile = function (id) {
  if (!id) {
    drawProfile();
    return;
  }
  $("#app").innerHTML = "<p>Carregando perfil…</p>";
  run(async () => {
    const p = await apiCall("profiles/" + id);
    if (location.hash !== "#/usuario/" + id) return;
    const rs = db.reviews.filter((r) => r.userId === p.id);
    const favorites = db.works.filter((w) => p.favorites.includes(w.id));
    const reviewsRow = rs.length
      ? `<div class="profile-row">${rs
          .slice()
          .reverse()
          .map((r) => `<div class="profile-row-cell">${review(r, true)}</div>`)
          .join("")}</div>`
      : '<p class="empty">Nenhuma resenha publicada.</p>';
    $("#app").innerHTML =
      `<section class="profile-head"><div class="avatar">${p.avatar ? `<img alt="Avatar" style="width:100%;height:100%;object-fit:cover;border-radius:50%" src="${esc(p.avatar)}">` : esc(initials(p.name))}</div><div class="profile-info"><h1>${esc(p.name)}</h1><p>${esc(p.bio)}</p><span>${rs.length} resenhas · ${rs.reduce((n, r) => n + r.likes, 0)} curtidas recebidas</span></div></section><h2>Favoritos</h2><div class="profile-row">${favorites.length ? cards(favorites) : '<p class="empty">Nenhuma obra aqui.</p>'}</div><h2>Últimas resenhas</h2>${reviewsRow}`;
  });
};

admin = function () {
  if (!session || !db.profile.staff) {
    $("#app").innerHTML =
      '<h1>Acesso restrito</h1><p>Esta área está disponível para administradores.</p><a href="#/">Voltar ao catálogo</a>';
    return;
  }
  const pageOf = (tab) => adminPage[tab] || 1;
  const paginate = (items, tab) => {
    const totalPages = Math.max(1, Math.ceil(items.length / adminPageSize));
    const page = Math.min(pageOf(tab), totalPages);
    adminPage[tab] = page;
    const start = (page - 1) * adminPageSize;
    return {
      items: items.slice(start, start + adminPageSize),
      page,
      totalPages,
      total: items.length,
    };
  };
  const pager = (page, totalPages, total) =>
    total ? `${searchPager(page, totalPages, total)}<div class="pager-total"><span>${total} itens</span></div>` : "";
  $("#app").innerHTML =
    `<div class="toolbar"><h1>Administração</h1><a href="/admin/">Admin Django ↗</a></div><div class="stats">${[
      ["Denúncias pendentes", db.reports.length],
      ["Obras no catálogo", db.works.length],
      ["Usuários ativos", db.users.filter((u) => u.active).length],
      ["Resenhas", db.reviews.length],
    ]
      .map(
        ([label, n]) =>
          `<div class="panel"><small>${label}</small><strong>${n}</strong></div>`,
      )
      .join(
        "",
      )}</div><div class="chips admin-tabs">${["Denúncias", "Obras", "Usuários"].map((t) => `<button class="${adminTab === t ? "active" : ""}" onclick="adminTab='${t}';adminPage['${t}']=1;admin()">${t}</button>`).join("")}</div><div id="admin-body"></div>`;
  const target = $("#admin-body");
  if (adminTab === "Denúncias") {
    const view = paginate(db.reports, "Denúncias");
    target.innerHTML =
      "<h2>Fila de denúncias</h2>" +
      (view.items
        .map((p) => {
          const r = db.reviews.find((r) => r.id === p.review);
          return `<div class="panel"><div class="toolbar"><b>${p.comment ? "Comentário" : "Resenha"} · ${esc(r ? work(r.work)?.title : "Conteúdo denunciado")}</b><span class="danger">${esc(p.reason)}</span></div><p>${esc(p.snapshot)}</p><p class="muted">${esc(p.context)}</p><div class="row"><button onclick="moderate('${p.id}','keep')">Manter conteúdo</button><button class="danger" onclick="moderate('${p.id}','delete')">Excluir conteúdo</button><button class="danger" onclick="moderate('${p.id}','block')">Excluir e bloquear autor</button></div></div>`;
        })
        .join("") || '<p class="empty">Nenhuma denúncia pendente.</p>') +
      pager(view.page, view.totalPages, view.total);
  } else if (adminTab === "Obras") {
    const view = paginate(db.works, "Obras");
    target.innerHTML =
      `<div class="toolbar"><h2>Catálogo</h2><div class="row"><button onclick="importWork('omdb')">Importar do OMDb</button><button onclick="importWork('rawg')">Importar do RAWG</button><button onclick="importWork('books')">Importar livro</button><button onclick="importWork('comicvine')">Importar do Comic Vine</button><button class="primary" onclick="editWork()">+ Cadastrar obra</button></div></div><div class="table-wrap"><table><thead><tr><th>Título</th><th>Categoria</th><th>Ano</th><th>Ações</th></tr></thead><tbody>${view.items.map((w) => `<tr><td>${esc(w.title)}</td><td>${esc(w.category)}</td><td>${w.year}</td><td><button onclick="editWork(${w.id})">Editar</button> <button class="danger" onclick="removeWork(${w.id})">Excluir</button></td></tr>`).join("")}</tbody></table></div>` +
      pager(view.page, view.totalPages, view.total);
  } else {
    const view = paginate(db.users, "Usuários");
    target.innerHTML =
      "<h2>Usuários</h2>" +
      (view.items
        .map(
          (u) =>
            `<div class="panel row"><span class="avatar">${esc(initials(u.name))}</span><b>${esc(u.name)}</b><span class="muted">${u.staff ? "Administrador" : u.active ? "Ativo" : "Bloqueado"}</span>${u.staff ? "" : `<span style="margin-left:auto;display:flex;gap:8px"><button onclick="toggleUser(${u.id},${!u.active})">${u.active ? "Bloquear" : "Desbloquear"}</button><button class="danger" onclick="deleteUser(${u.id},'${esc(u.name).replace(/'/g, "&#39;")}')">Excluir</button></span>`}</div>`,
        )
        .join("") || '<p class="empty">Nenhum usuário.</p>') +
      pager(view.page, view.totalPages, view.total);
  }
  // Liga os botões da paginação numerada à aba atual.
  target.querySelectorAll(".pagination [data-page]").forEach((btn) => {
    btn.onclick = () => {
      if (btn.disabled) return;
      adminGoto(adminTab, Number(btn.dataset.page));
    };
  });
};
function adminGoto(tab, page) {
  adminPage[tab] = Math.max(1, page);
  admin();
}
function toggleUser(id, active) {
  confirmAction(active ? "Desbloquear conta?" : "Bloquear conta?", () =>
    run(async () => {
      await apiCall("admin/users/" + id, "PATCH", { active });
      await refresh();
    }),
  );
}
function deleteUser(id, name) {
  confirmAction(
    `Excluir a conta de ${name || "usuário"}?`,
    () =>
      run(async () => {
        await apiCall("admin/users/" + id, "DELETE");
        adminPage["Usuários"] = 1;
        await refresh();
        toast("Conta excluída.");
      }),
    "Esta ação é permanente e remove resenhas, curtidas, listas e denúncias do usuário.",
  );
}
moderate = function (id, action) {
  confirmAction("Confirmar ação de moderação?", () =>
    run(async () => {
      await apiCall("admin/reports/" + id, "POST", { action });
      await refresh();
    }),
  );
};
const drawWorkForm = editWork;
editWork = function (id) {
  drawWorkForm(id);
  if (!session) return;
  $("#work-form").onsubmit = (e) => {
    e.preventDefault();
    const f = e.target,
      category = f.category.value,
      // Elenco só se aplica a Filmes e Séries.
      hasCast = ["Filmes", "Séries"].includes(category),
      payload = {
        title: f.elements.namedItem("title").value,
        category,
        year: Number(f.year.value),
        creator: f.creator.value,
        synopsis: f.synopsis.value,
        cast: hasCast ? f.elements.namedItem("cast").value : "",
        tags: f.elements.namedItem("tags").value,
        poster: f.elements.namedItem("poster").value.trim(),
        color: f.color.value,
      };
    run(async () => {
      await apiCall(
        "admin/works" + (id ? "/" + id : ""),
        id ? "PATCH" : "POST",
        payload,
      );
      $("#modal").close();
      await refresh();
    });
  };
};
removeWork = function (id) {
  confirmAction("Excluir obra e suas resenhas?", () =>
    run(async () => {
      await apiCall("admin/works/" + id, "DELETE");
      await refresh();
    }),
  );
};
const IMPORT_SOURCES = {
  omdb: { heading: "Importar do OMDb", provider: "OMDb" },
  rawg: { heading: "Importar do RAWG", provider: "RAWG" },
  // Livros: Open Library, com Google Books como reserva no servidor.
  books: {
    heading: "Importar livro",
    provider: "Open Library",
    id: { name: "isbn", label: "ou ISBN", max: 20, placeholder: "978..." },
    hint: "Busca no Open Library. O ISBN encontra uma edição específica.",
  },
  comicvine: {
    heading: "Importar do Comic Vine",
    provider: "Comic Vine",
    id: { name: "comicvine_id", label: "ou ID do Comic Vine", max: 20, placeholder: "4050-3092" },
    hint: "Importa a série ou o encadernado. O ID aparece no endereço da página do Comic Vine.",
  },
};
function importWork(source = "omdb") {
  const config = IMPORT_SOURCES[source] || IMPORT_SOURCES.omdb;
  const idField = config.id
    ? `<label>${config.id.label}<input name="${config.id.name}" maxlength="${config.id.max}" placeholder="${config.id.placeholder}"></label>`
    : "";
  modal(
    `<h2>${config.heading}</h2><form id="import-form"><label>Título<input name="title" ${config.id ? "" : "required"} maxlength="150"></label>${idField}${config.hint ? `<p class="muted">${config.hint}</p>` : ""}<button class="primary full">Buscar e importar</button></form>`,
  );
  $("#import-form").onsubmit = (e) => {
    e.preventDefault();
    const fields = e.target.elements;
    const payload = { source, title: fields.namedItem("title").value.trim() };
    if (config.id) payload[config.id.name] = fields.namedItem(config.id.name).value.trim();
    if (!payload.title && !(config.id && payload[config.id.name])) {
      toast(`Informe o título ${config.id.label}.`);
      return;
    }
    run(async () => {
      const result = await apiCall("admin/import", "POST", payload);
      $("#modal").close();
      await refresh();
      toast(result.created === false ? "Esta obra já estava no catálogo." : `Obra importada via ${config.provider}.`);
    });
  };
}
// O servidor é a única fonte de dados; falhas não ativam um modo local silencioso.
run(async () => {
  try {
    await refresh(true);
  } catch (e) {
    $("#app").innerHTML =
      "<h1>Não foi possível carregar o catálogo</h1><p>Verifique se o servidor está disponível e recarregue a página.</p>";
    throw e;
  }
});
