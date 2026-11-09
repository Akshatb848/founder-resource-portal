/** Company profile (alpha v1.2.6): one screen shared by the Demo Ventures workspace and the founder portal.
 *  CompanyProfile.mount(host, cfg) loads the profile, shows it, and switches to an edit form when the person
 *  may edit. cfg: { url, confirmUrl, pdfUrl, firmsUrl, onSaved }.
 *  - Brand name large, legal name smaller beneath it.
 *  - Firms come from one shared list: a typed name that matches an existing firm (ignoring case, "&" and
 *    suffixes such as LLP or Pvt Ltd) is replaced by the name already in the list, so nothing is entered twice.
 *  - Expired certificates show red, ones expiring soon amber. Email reminders are phase 2.
 *  No inline handlers (the Content-Security-Policy blocks them): one delegated listener per mounted host. */
(function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const say = (m) => (typeof window.toast === "function" ? window.toast(m) : alert(m));
  const YNA = { yes: "Yes", no: "No", na: "Not applicable" };
  const KINDS = { auditor: "auditor", company_secretary: "company_secretary", law_firm: "law_firm", bank: "bank", lender: "lender", investment_bank: "investment_bank", tax_advisor: "tax_advisor" };
  const CLOUDS = ["AWS", "Microsoft Azure", "Google Cloud", "Oracle Cloud", "DigitalOcean", "On-premises"];
  const INSTRUMENTS = ["Term loan", "Working capital loan", "Cash credit", "Overdraft", "Venture debt", "Invoice discounting", "Bank guarantee", "Letter of credit"];
  const SUFFIXES = ["private limited", "pvt ltd", "pvt", "limited", "ltd", "llp", "and co", "co", "inc", "india"];
  let uid = 0;

  /* Same rule as backend/profile_api.py firm_key(). */
  function firmKey(name) {
    let s = String(name || "").toLowerCase().replace(/&/g, " and ").replace(/[^a-z0-9]+/g, " ").trim();
    let changed = true;
    while (changed && s) {
      changed = false;
      for (const suf of SUFFIXES) {
        if (suf === "india" && s.endsWith(" of india")) continue;
        if (s.endsWith(" " + suf) && s.length > suf.length + 1) { s = s.slice(0, -suf.length - 1).trim(); changed = true; }
      }
    }
    return s.replace(/\s+/g, " ");
  }

  const fmtDate = (d) => (d ? new Date(d + (d.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "");
  const dash = (v) => (v ? esc(v) : `<span class="muted">Not filled in</span>`);
  const peopleText = (rows) => rows.map((p) => `${esc(p.full_name)}${p.role_note ? ` <small class="muted">(${esc(p.role_note)})</small>` : ""}`).join("<br>");

  /* ---------------- read-only view */
  function viewHtml(p, cfgTracker = "") {
    const c = p.company, g = p.governance, a = p.agreements, d = p.dpdp, comp = p.completeness, sv = p.services || {}, pt = p.patents || {};
    const yn = (v) => (v ? esc(YNA[v]) : dash(""));
    const num = (v) => (v === null || v === undefined ? `<span class="muted">Not filled in</span>` : esc(v));
    const confirmLine = p.confirmed_at
      ? `Details confirmed ${esc(fmtDate(p.confirmed_at.slice(0, 10)))} by ${esc(p.confirmed_by)}`
      : "Details not yet confirmed";
    const alerts = p.alerts.length
      ? `<div class="cp-alerts">${p.alerts.map((al) => `<span class="cp-alert ${al.level}">${al.level === "red" ? "Expired" : "Expires soon"}: ${esc(al.item)} (${esc(fmtDate(al.expires_on))})</span>`).join("")}</div>`
      : "";
    const row = (label, val) => `<div class="cp-row"><span>${esc(label)}</span><span>${val}</span></div>`;
    const compRows = p.compliance.filter((x) => x.standard || x.status).map((x) => `<tr class="${x.alert ? `cp-${x.alert}` : ""}">
        <td data-label="Item" class="cp-cell-title">${esc(x.item)}</td><td data-label="Answer">${x.status ? esc(YNA[x.status]) : `<span class="muted">Not answered</span>`}</td>
        <td data-label="Certificate">${x.status === "yes" ? esc(x.certificate_no || "") : ""}</td>
        <td data-label="Expires">${x.status === "yes" && x.expires_on ? `${esc(fmtDate(x.expires_on))}${x.alert ? ` <span class="cp-badge ${x.alert}">${x.alert === "red" ? "Expired" : "Soon"}</span>` : ""}` : ""}</td>
        <td data-label="Note">${esc(x.note || "")}</td></tr>`).join("");
    const creditTable = (rows, cardMode) => rows.length
      ? `<div class="table-wrap"><table class="cp-table"><thead><tr><th>${cardMode ? "Issuing bank" : "Bank or lender"}</th><th>${cardMode ? "Card" : "Instrument"}</th><th class="num">${cardMode ? "Limit" : "Amount"}</th><th class="num">Interest</th><th>Note</th></tr></thead><tbody>${rows.map((r) => `<tr><td data-label="${cardMode ? "Issuing bank" : "Bank or lender"}" class="cp-cell-title">${esc(r.lender || "-")}</td><td data-label="${cardMode ? "Card" : "Instrument"}">${esc(r.instrument || "")}</td><td class="num" data-label="${cardMode ? "Limit" : "Amount"}">${esc(r.amount_label || "")}</td><td class="num" data-label="Interest">${r.interest_rate != null ? `${esc(r.interest_rate)}%` : ""}</td><td data-label="Note">${esc(r.note || "")}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="muted">None recorded.</p>`;
    const hist = p.history?.length
      ? p.history.map((h) => `<li><strong>${esc(h.what)}</strong> <small class="muted">${esc(new Date(h.at).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }))} · ${esc(h.by)}</small>${Object.keys(h.changes || {}).length ? `<ul>${Object.entries(h.changes).map(([k, [o, n]]) => `<li>${esc(k)}: ${o ? `<s>${esc(o)}</s> ` : ""}${n ? esc(n) : `<span class="muted">cleared</span>`}</li>`).join("")}</ul>` : ""}</li>`).join("")
      : `<li class="muted">No changes recorded yet. Every change from now on is listed here.</li>`;
    return `<div class="cp">
      <div class="card cp-head">
        <div class="cp-names"><h2>${esc(c.brand_name)}</h2>${c.legal_name ? `<p class="cp-legal">${esc(c.legal_name)}</p>` : `<p class="cp-legal muted">Legal name not filled in</p>`}
          <p class="muted cp-meta"><span class="cp-badge ${comp.pct === 100 ? "ok" : "neutral"}">${comp.pct}% complete</span> <span class="cp-badge ${p.confirm_due ? "amber" : "ok"}">${esc(confirmLine)}</span></p></div>
        <div class="row-actions cp-actions">${p.can_edit ? `<button class="btn primary" type="button" data-cp="edit">Edit profile</button><button class="btn ghost" type="button" data-cp="confirm">Confirm details are current</button>` : ""}<button class="btn ghost" type="button" data-cp="pdf">Download PDF</button></div>
      </div>
      ${alerts}
      ${comp.missing.length ? `<details class="card cp-missing"><summary><strong>Still to fill in (${comp.missing.length})</strong></summary><p class="muted">${comp.missing.map(esc).join(", ")}</p></details>` : ""}
      <div class="cp-grid">
        <section class="card"><h3>Governance</h3>
          ${row("Statutory auditor", dash(g.auditor))}${row("Auditor appointed on", dash(fmtDate(g.auditor_appointed_on)))}
          ${row("Company secretary", dash(g.company_secretary))}${row("Company secretary engaged since", dash(fmtDate(g.secretary_engaged_on)))}${row("Legal counsel", dash(g.legal_counsel))}
          ${row("Bankers", g.bankers.length ? g.bankers.map(esc).join("<br>") : dash(""))}
          ${row("Board members", g.board.length ? peopleText(g.board) : dash(""))}
          ${row("Advisory board", g.advisory.length ? peopleText(g.advisory) : `<span class="muted">None</span>`)}
          ${row("Independent directors", g.independent.length ? peopleText(g.independent) : `<span class="muted">None</span>`)}
          ${row("Demo Ventures nominee or observer", dash(g.board_nominee))}
          ${row("Information security and privacy policy", yn(g.infosec_policy))}
          ${row("Chief of Staff", g.cos_name ? `${esc(g.cos_name)}${g.cos_joined_on ? ` <small class="muted">(joined ${esc(fmtDate(g.cos_joined_on))})</small>` : ""}` : dash(""))}
        </section>
        <section class="card"><h3>Service providers and patents</h3>
          ${row("Audited accounts signed on", dash(fmtDate(sv.accounts_signed_on)))}
          ${row("Investment banker", dash(sv.investment_bank))}
          ${row("Tax or structuring advisor", dash(sv.tax_advisor))}
          ${row("Cloud service provider", dash(sv.cloud_provider))}
          ${row("Patents filed", num(pt.filed))}${row("Patents granted", num(pt.granted))}
        </section>
        ${a && d ? `<section class="card"><h3>Agreements and DPDP</h3>
          ${row("SHA custody", dash(a.sha_custody))}${row("Share certificates custody", dash(a.share_cert_custody))}${row("Demat status", yn(a.demat_status))}
          ${row("AOP for the current year", a.aop_status ? `${esc(YNA[a.aop_status])}${a.aop_note ? ` · ${esc(a.aop_note)}` : ""}` : dash(""))}
          ${row("DPDP consent captured", d.consent ? esc(YNA[d.consent]) : dash(""))}
          ${row("Consent duration", dash(d.consent_duration))}${row("Renewal frequency", dash(d.renewal))}
          ${row("DPDP consent annexure in the SHA", d.sha_annexure ? esc(YNA[d.sha_annexure]) : dash(""))}
        </section>` : ""}
      </div>
      <section class="card"><h3>Compliance</h3><div class="table-wrap"><table class="cp-table"><thead><tr><th>Item</th><th>Answer</th><th>Certificate</th><th>Expires</th><th>Note</th></tr></thead><tbody>${compRows}</tbody></table></div></section>
      <section class="card"><h3>Credit lines</h3>${creditTable(p.credit.credit_line, false)}</section>
      <section class="card"><h3>Corporate credit cards</h3>${creditTable(p.credit.credit_card, true)}</section>
      ${cfgTracker}
      <details class="card cp-history"><summary><strong>Change history</strong></summary><ul>${hist}</ul></details>
    </div>`;
  }

  /* ---------------- edit form */
  const ynaSelect = (name, val, label) => `<select name="${name}" aria-label="${esc(label)}"><option value="">Not answered</option>${Object.entries(YNA).map(([k, v]) => `<option value="${k}"${val === k ? " selected" : ""}>${v}</option>`).join("")}</select>`;
  const firmInput = (name, val, kind, label, extra = "") => `<input name="${name}" value="${esc(val || "")}" list="cp-firms-${kind}-${uid}" data-firm="${kind}" maxlength="160" aria-label="${esc(label)}" autocomplete="off"${extra}>`;
  const removeBtn = `<button class="btn ghost cp-remove" type="button" data-cp="remove" aria-label="Remove this row">Remove</button>`;

  function bankRow(name) { return `<div class="cp-list-row" data-row="banker">${firmInput("bank", name, "bank", "Bank")}${removeBtn}</div>`; }
  function personRow(kind, p = {}) {
    return `<div class="cp-list-row" data-row="${kind}"><input name="full_name" value="${esc(p.full_name || "")}" maxlength="120" placeholder="Full name" aria-label="Full name"><input name="role_note" value="${esc(p.role_note || "")}" maxlength="120" placeholder="Role, e.g. Chair or Demo Ventures nominee" aria-label="Role">${removeBtn}</div>`;
  }
  function complianceRow(x) {
    const custom = !x.standard;
    return `<tr data-row="compliance"${x.standard ? ` data-standard="1"` : ""}>
      <td data-label="Item" class="cp-cell-title">${custom ? `<input name="item" value="${esc(x.item || "")}" maxlength="120" placeholder="Certificate or registration" aria-label="Compliance item">` : `<input type="hidden" name="item" value="${esc(x.item)}">${esc(x.item)}`}</td>
      <td data-label="Answer">${ynaSelect("status", x.status, `${x.item || "Item"}: answer`)}</td>
      <td data-label="Certificate no."><input name="certificate_no" value="${esc(x.certificate_no || "")}" maxlength="120" aria-label="Certificate number"></td>
      <td data-label="Issued"><input type="date" name="issued_on" value="${esc(x.issued_on || "")}" aria-label="Issued on"></td>
      <td data-label="Expires"><input type="date" name="expires_on" value="${esc(x.expires_on || "")}" aria-label="Expires on"></td>
      <td data-label="Note"><input name="note" value="${esc(x.note || "")}" maxlength="300" aria-label="Note"></td>
      <td class="cp-cell-action">${custom ? removeBtn : ""}</td></tr>`;
  }
  function creditRow(kind, r = {}) {
    const card = kind === "credit_card";
    return `<tr data-row="${kind}"><td data-label="${card ? "Issuing bank" : "Bank or lender"}">${firmInput("lender", r.lender, card ? "bank" : "lender", card ? "Issuing bank" : "Bank or lender")}</td>
      <td data-label="${card ? "Card" : "Instrument"}"><input name="instrument" value="${esc(r.instrument || "")}" maxlength="120" ${card ? `placeholder="Card name"` : `list="cp-instruments-${uid}"`} aria-label="${card ? "Card" : "Instrument"}"></td>
      <td data-label="${card ? "Limit" : "Amount"}"><input name="amount" value="${esc(r.amount_label ? r.amount_label.replace("₹", "") : "")}" maxlength="40" placeholder="e.g. 5 crore" aria-label="${card ? "Limit" : "Amount"}"></td>
      <td data-label="Interest %"><input name="interest_rate" value="${esc(r.interest_rate ?? "")}" maxlength="8" inputmode="decimal" placeholder="%" aria-label="Interest rate"></td>
      <td data-label="Note"><input name="note" value="${esc(r.note || "")}" maxlength="300" aria-label="Note"></td><td class="cp-cell-action">${removeBtn}</td></tr>`;
  }

  function formHtml(p, firms) {
    uid += 1;
    const c = p.company, g = p.governance, a = p.agreements, d = p.dpdp, sv = p.services || {}, pt = p.patents || {};
    const lists = Object.values(KINDS).map((k) => {
      const mine = firms.filter((f) => f.kinds.includes(k)), others = firms.filter((f) => !f.kinds.includes(k));
      return `<datalist id="cp-firms-${k}-${uid}">${[...mine, ...others].map((f) => `<option value="${esc(f.name)}">`).join("")}</datalist>`;
    }).join("");
    const people = (kind, title, rows) => `<div class="full"><h4>${title}</h4><div data-list="${kind}">${rows.map((r) => personRow(kind, r)).join("")}</div><button class="btn ghost" type="button" data-cp="add" data-kind="${kind}">+ Add a person</button></div>`;
    return `<form class="cp cp-form" novalidate>${lists}<datalist id="cp-instruments-${uid}">${INSTRUMENTS.map((x) => `<option value="${x}">`).join("")}</datalist>
      <datalist id="cp-clouds-${uid}">${CLOUDS.map((x) => `<option value="${x}">`).join("")}</datalist>
      <datalist id="cp-renewal-${uid}">${(p.choices?.dpdp_renewal || []).map((x) => `<option value="${esc(x)}">`).join("")}</datalist>
      <div class="card cp-head"><div class="cp-names"><h2>Edit profile: ${esc(c.brand_name)}</h2><p class="muted">Start typing a firm's name to pick it from the shared list. A new name is added to the list for everyone.</p></div>
        <div class="row-actions cp-actions"><button class="btn primary" type="submit">Save profile</button><button class="btn ghost" type="button" data-cp="cancel">Cancel</button></div></div>
      <section class="card"><h3>Names</h3><div class="review-form">
        <label>Brand name<input value="${esc(c.brand_name)}" disabled aria-describedby="cp-brand-hint-${uid}"><small class="muted" id="cp-brand-hint-${uid}">The Demo Ventures team changes the brand name in Companies, Edit details.</small></label>
        <label>Legal name<input name="legal_name" value="${esc(c.legal_name || "")}" maxlength="200" placeholder="As registered with the MCA"></label></div></section>
      <section class="card"><h3>Governance</h3><div class="review-form">
        <label>Statutory auditor${firmInput("auditor", g.auditor, "auditor", "Statutory auditor")}</label>
        <label>Auditor appointed on<input type="date" name="auditor_appointed_on" value="${esc(g.auditor_appointed_on || "")}"></label>
        <label>Company secretary${firmInput("company_secretary", g.company_secretary, "company_secretary", "Company secretary")}</label>
        <label>Company secretary engaged since<input type="date" name="secretary_engaged_on" value="${esc(g.secretary_engaged_on || "")}"></label>
        <label>Legal counsel${firmInput("legal_counsel", g.legal_counsel, "law_firm", "Legal counsel")}</label>
        <div class="full"><h4>Bankers</h4><div data-list="banker">${(g.bankers.length ? g.bankers : [""]).map(bankRow).join("")}</div><button class="btn ghost" type="button" data-cp="add" data-kind="banker">+ Add a bank</button></div>
        ${people("board", "Board members", g.board)}${people("advisory", "Advisory board", g.advisory)}${people("independent", "Independent directors", g.independent)}
        <label>Demo Ventures nominee or observer on the board<input name="board_nominee" value="${esc(g.board_nominee || "")}" maxlength="200" placeholder="Name, and whether nominee or observer"></label>
        <label>Information security and privacy policy${ynaSelect("infosec_policy", g.infosec_policy, "Information security and privacy policy")}</label>
        <label>Chief of Staff<input name="cos_name" value="${esc(g.cos_name || "")}" maxlength="120" placeholder="Name, if appointed"></label>
        <label>Chief of Staff joined on<input type="date" name="cos_joined_on" value="${esc(g.cos_joined_on || "")}"></label>
      </div></section>
      <section class="card"><h3>Service providers and patents</h3><div class="review-form">
        <label>Audited accounts signed on<input type="date" name="accounts_signed_on" value="${esc(sv.accounts_signed_on || "")}"></label>
        <label>Investment banker (appointed or used before)${firmInput("investment_bank", sv.investment_bank, "investment_bank", "Investment banker")}</label>
        <label>Tax or structuring advisor${firmInput("tax_advisor", sv.tax_advisor, "tax_advisor", "Tax or structuring advisor")}</label>
        <label>Cloud service provider<input name="cloud_provider" value="${esc(sv.cloud_provider || "")}" maxlength="160" list="cp-clouds-${uid}"></label>
        <label>Patents filed<input name="patents_filed" value="${esc(pt.filed ?? "")}" inputmode="numeric" maxlength="5" placeholder="0 if none"></label>
        <label>Patents granted<input name="patents_granted" value="${esc(pt.granted ?? "")}" inputmode="numeric" maxlength="5" placeholder="0 if none"></label>
      </div></section>
      <section class="card"><h3>Compliance</h3><p class="muted">Answer Yes, No or Not applicable. Certificate details are kept only for Yes. Expired certificates show red, ones expiring within ${esc(p.choices?.expiry_warn_days || 60)} days amber.</p>
        <div class="table-wrap"><table class="cp-table cp-edit-table"><thead><tr><th>Item</th><th>Answer</th><th>Certificate no.</th><th>Issued</th><th>Expires</th><th>Note</th><th></th></tr></thead><tbody data-list="compliance">${p.compliance.map(complianceRow).join("")}</tbody></table></div>
        <button class="btn ghost" type="button" data-cp="add" data-kind="compliance">+ Add another certificate or registration</button></section>
      ${a && d ? `<section class="card"><h3>Agreements and DPDP</h3><div class="review-form">
        <label class="full">SHA custody (who holds the signed shareholders' agreement)<input name="sha_custody" value="${esc(a.sha_custody || "")}" maxlength="300"></label>
        <label class="full">Share certificates custody (who holds them)<input name="share_cert_custody" value="${esc(a.share_cert_custody || "")}" maxlength="300"></label>
        <label>Demat status (shares dematerialised)${ynaSelect("demat_status", a.demat_status, "Demat status")}</label>
        <label>AOP for the current year received${ynaSelect("aop_status", a.aop_status, "AOP for the current year")}</label>
        <label>AOP note<input name="aop_note" value="${esc(a.aop_note || "")}" maxlength="300"></label>
        <label>DPDP consent captured${ynaSelect("dpdp_consent", d.consent, "DPDP consent captured")}</label>
        <label>Consent duration<input name="dpdp_consent_duration" value="${esc(d.consent_duration || "")}" maxlength="120" placeholder="e.g. Until the purpose ends"></label>
        <label>Renewal frequency<input name="dpdp_renewal" value="${esc(d.renewal || "")}" maxlength="120" list="cp-renewal-${uid}"></label>
        <label>DPDP consent annexure in the SHA${ynaSelect("dpdp_sha_annexure", d.sha_annexure, "DPDP consent annexure in the SHA")}</label>
      </div></section>` : ""}
      <section class="card"><h3>Credit lines</h3><div class="table-wrap"><table class="cp-table cp-edit-table"><thead><tr><th>Bank or lender</th><th>Instrument</th><th>Amount</th><th>Interest %</th><th>Note</th><th></th></tr></thead><tbody data-list="credit_line">${p.credit.credit_line.map((r) => creditRow("credit_line", r)).join("")}</tbody></table></div>
        <button class="btn ghost" type="button" data-cp="add" data-kind="credit_line">+ Add a credit line</button></section>
      <section class="card"><h3>Corporate credit cards</h3><div class="table-wrap"><table class="cp-table cp-edit-table"><thead><tr><th>Issuing bank</th><th>Card</th><th>Limit</th><th>Interest %</th><th>Note</th><th></th></tr></thead><tbody data-list="credit_card">${p.credit.credit_card.map((r) => creditRow("credit_card", r)).join("")}</tbody></table></div>
        <button class="btn ghost" type="button" data-cp="add" data-kind="credit_card">+ Add a credit card</button></section>
      <div class="row-actions cp-actions"><button class="btn primary" type="submit">Save profile</button><button class="btn ghost" type="button" data-cp="cancel">Cancel</button></div>
    </form>`;
  }

  function collect(form) {
    const v = (el, n) => (el.querySelector(`[name="${n}"]`)?.value || "").trim();
    const rows = (kind) => [...form.querySelectorAll(`[data-row="${kind}"]`)];
    const people = (kind) => rows(kind).map((r) => ({ full_name: v(r, "full_name"), role_note: v(r, "role_note") || null })).filter((x) => x.full_name);
    const credit = (kind) => rows(kind).map((r) => ({ lender: v(r, "lender") || null, instrument: v(r, "instrument") || null, amount: v(r, "amount") || null, interest_rate: v(r, "interest_rate") || null, note: v(r, "note") || null }))
      .filter((x) => x.lender || x.instrument || x.amount || x.interest_rate);
    return {
      legal_name: v(form, "legal_name") || null, auditor: v(form, "auditor") || null, auditor_appointed_on: v(form, "auditor_appointed_on") || null,
      company_secretary: v(form, "company_secretary") || null, legal_counsel: v(form, "legal_counsel") || null,
      bankers: rows("banker").map((r) => v(r, "bank")).filter(Boolean),
      board: people("board"), advisory: people("advisory"), independent: people("independent"),
      compliance: rows("compliance").map((r) => ({ item: v(r, "item"), status: v(r, "status") || null, certificate_no: v(r, "certificate_no") || null, issued_on: v(r, "issued_on") || null, expires_on: v(r, "expires_on") || null, note: v(r, "note") || null })).filter((x) => x.item && x.status),
      sha_custody: v(form, "sha_custody") || null, aop_status: v(form, "aop_status") || null, aop_note: v(form, "aop_note") || null,
      dpdp_consent: v(form, "dpdp_consent") || null, dpdp_consent_duration: v(form, "dpdp_consent_duration") || null,
      dpdp_renewal: v(form, "dpdp_renewal") || null, dpdp_sha_annexure: v(form, "dpdp_sha_annexure") || null,
      credit_lines: credit("credit_line"), credit_cards: credit("credit_card"),
      secretary_engaged_on: v(form, "secretary_engaged_on") || null, accounts_signed_on: v(form, "accounts_signed_on") || null,
      investment_bank: v(form, "investment_bank") || null, tax_advisor: v(form, "tax_advisor") || null,
      cloud_provider: v(form, "cloud_provider") || null, board_nominee: v(form, "board_nominee") || null,
      infosec_policy: v(form, "infosec_policy") || null, cos_name: v(form, "cos_name") || null, cos_joined_on: v(form, "cos_joined_on") || null,
      patents_filed: v(form, "patents_filed") || null, patents_granted: v(form, "patents_granted") || null,
      share_cert_custody: v(form, "share_cert_custody") || null, demat_status: v(form, "demat_status") || null,
    };
  }

  /* ---------------- Demo Ventures tracker (staff only: the workspace passes cfg.trackerUrl; founders never get one) */
  function trackerHtml(t, editing) {
    if (!t) return "";
    const val = (f) => t.values[f.key];
    const show = (f) => {
      const v = val(f);
      if (!v) return `<span class="muted">Not filled in</span>`;
      if (f.kind === "yna") return esc(YNA[v]);
      if (f.kind === "date") return esc(fmtDate(v));
      return esc(v).replace(/\n/g, "<br>");
    };
    const input = (f) => {
      const v = val(f) || "";
      if (f.kind === "yna") return ynaSelect(f.key, v, f.label);
      if (f.kind === "date") return `<input type="date" name="${f.key}" value="${esc(v)}" aria-label="${esc(f.label)}">`;
      if (f.max > 300) return `<textarea name="${f.key}" maxlength="${f.max}" rows="${f.max > 1000 ? 4 : 2}" aria-label="${esc(f.label)}">${esc(v)}</textarea>`;
      return `<input name="${f.key}" value="${esc(v)}" maxlength="${f.max}" aria-label="${esc(f.label)}">`;
    };
    const who = t.updated_at ? `Last updated ${esc(fmtDate(t.updated_at.slice(0, 10)))} by ${esc(t.updated_by || "")}` : "Not updated yet";
    const head = `<h3>Demo Ventures tracker <span class="cp-badge neutral">Staff only</span></h3><p class="muted">Exit discussions, SHA rights review, fundraise status, action points and founders' KYC. Founders never see this. Record only whether KYC is received: never type PAN, Aadhaar or passport numbers. ${who}.</p>`;
    if (!editing) {
      return `<section class="card cp-tracker">${head}${t.fields.map((f) => `<div class="cp-row"><span>${esc(f.label)}</span><span>${show(f)}</span></div>`).join("")}${t.can_edit ? `<div class="row-actions" style="margin-top:10px"><button class="btn ghost" type="button" data-cp="tracker-edit">Edit tracker</button></div>` : ""}</section>`;
    }
    return `<section class="card cp-tracker"><form class="cp-tracker-form" novalidate>${head}<div class="review-form">${t.fields.map((f) => `<label class="${f.max > 300 ? "full" : ""}">${esc(f.label)}${input(f)}</label>`).join("")}</div>
      <div class="row-actions" style="margin-top:10px"><button class="btn primary" type="submit">Save tracker</button><button class="btn ghost" type="button" data-cp="tracker-cancel">Cancel</button></div></form></section>`;
  }

  /* ---------------- mounting */
  function mount(host, cfg) {
    const st = { prof: null, firms: [], editing: false, busy: false, tracker: null, trackerEditing: false };
    host.innerHTML = `<p class="muted">Loading the company profile…</p>`;

    async function load() {
      try {
        st.prof = await PortalAPI.json(cfg.url);
        if (cfg.trackerUrl) {
          try { st.tracker = await PortalAPI.json(cfg.trackerUrl); } catch (_) { st.tracker = null; }
        }
        render();
      } catch (err) {
        host.innerHTML = `<p class="empty card">${esc(err.message)}</p>`;
      }
    }
    function render() {
      host.innerHTML = st.editing ? formHtml(st.prof, st.firms) : viewHtml(st.prof, trackerHtml(st.tracker, st.trackerEditing));
      const form = host.querySelector("form.cp-form");
      if (form) form.addEventListener("submit", save);
      const tform = host.querySelector("form.cp-tracker-form");
      if (tform) tform.addEventListener("submit", saveTracker);
    }
    async function saveTracker(e) {
      e.preventDefault();
      if (st.busy) return;
      st.busy = true;
      const form = e.target;
      const body = {};
      st.tracker.fields.forEach((f) => { body[f.key] = (form.querySelector(`[name="${f.key}"]`)?.value || "").trim() || null; });
      form.querySelectorAll('[type="submit"]').forEach((b) => (b.disabled = true));
      try {
        st.tracker = await PortalAPI.json(cfg.trackerUrl, { method: "PUT", body: JSON.stringify(body) });
        const n = (st.tracker.changed || []).length;
        say(n ? `Tracker saved: ${n} change${n === 1 ? "" : "s"}` : "Nothing changed");
        st.trackerEditing = false;
        render();
      } catch (err) {
        say(err.message);
        form.querySelectorAll('[type="submit"]').forEach((b) => (b.disabled = false));
      } finally {
        st.busy = false;
      }
    }
    async function edit() {
      try {
        st.firms = (await PortalAPI.json(cfg.firmsUrl)).firms || [];
      } catch (_) {
        st.firms = [];
      }
      st.editing = true;
      render();
      host.querySelector('[name="legal_name"]')?.focus();
    }
    async function save(e) {
      e.preventDefault();
      if (st.busy) return;
      const form = e.target;
      st.busy = true;
      form.querySelectorAll('[type="submit"]').forEach((b) => (b.disabled = true));
      try {
        const prof = await PortalAPI.json(cfg.url, { method: "PUT", body: JSON.stringify(collect(form)) });
        const n = (prof.changed || []).length;
        say(n ? `Profile saved: ${n} change${n === 1 ? "" : "s"}` : "Nothing changed");
        st.editing = false;
        await load();
        cfg.onSaved?.(st.prof);
      } catch (err) {
        say(err.message);
        form.querySelectorAll('[type="submit"]').forEach((b) => (b.disabled = false));
      } finally {
        st.busy = false;
      }
    }
    // A typed firm that matches one in the shared list takes the listed spelling.
    host.addEventListener("change", (e) => {
      const el = e.target.closest("[data-firm]");
      if (!el || !el.value.trim()) return;
      const key = firmKey(el.value);
      const hit = st.firms.find((f) => firmKey(f.name) === key);
      if (hit && hit.name !== el.value.trim()) {
        el.value = hit.name;
        say(`Using "${hit.name}" from the shared list`);
      }
    });
    host.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-cp]");
      if (!b || !host.contains(b)) return;
      const act = b.dataset.cp;
      if (act === "edit") edit();
      else if (act === "tracker-edit") { st.trackerEditing = true; render(); host.querySelector(".cp-tracker-form [name]")?.focus(); }
      else if (act === "tracker-cancel") { st.trackerEditing = false; render(); }
      else if (act === "cancel") { st.editing = false; render(); }
      else if (act === "pdf") {
        b.disabled = true;
        try { say(`Downloaded ${await PortalAPI.download(cfg.pdfUrl)}`); } catch (err) { say(err.message); } finally { b.disabled = false; }
      } else if (act === "confirm") {
        b.disabled = true;
        try {
          await PortalAPI.json(cfg.confirmUrl, { method: "POST" });
          await load();
          say("Thank you. The details are marked as current.");
          cfg.onSaved?.(st.prof);
        } catch (err) { say(err.message); b.disabled = false; }
      } else if (act === "remove") {
        b.closest("[data-row]")?.remove();
      } else if (act === "add") {
        const kind = b.dataset.kind;
        const list = host.querySelector(`[data-list="${kind}"]`);
        const html = kind === "banker" ? bankRow("") : kind === "compliance" ? complianceRow({ standard: false })
          : kind === "credit_line" || kind === "credit_card" ? creditRow(kind) : personRow(kind);
        list.insertAdjacentHTML("beforeend", html);
        list.lastElementChild.querySelector("input, select")?.focus();
      }
    });
    load();
    return { reload: load };
  }

  window.CompanyProfile = { mount, firmKey };
})();
