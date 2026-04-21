const APP_NAME = "LoadSearch";
const STORAGE_KEY = "loadsearch-app-state";
const OTHER_CARGO_VALUE = "__other_cargo__";
const DEFAULT_PORT = 3000;

const equipmentOptions = [
  "Flatbed",
  "Drybox",
  "Dribox",
  "Fardier",
  "Benne",
  "Porte-autos",
  "Plateforme",
  "Remorque fermee",
  "Step deck",
  "Refrigere",
  "Citerne",
  "B-train",
  "Rideau coulissant",
  "Roll-tite",
];

const suggestedCargoOptions = [
  "Bois",
  "Billots",
  "Beton",
  "Autos",
  "Tuyaux",
  "Materiaux mixtes",
];

const provinceOptions = [
  "Quebec",
  "Ontario",
  "Nouveau-Brunswick",
  "Nouvelle-Ecosse",
  "Manitoba",
];

const companyExamplePrompt =
  "J'ai 3 voyages de beton a faire de Laval vers Quebec vendredi matin avec une benne. Le client veut une livraison avant 15h. Budget autour de 1800 CAD par voyage.";

const carrierExamplePrompt =
  "Je suis un petit transporteur avec 2 camions flatbed et drybox. Je cherche surtout des voyages autour de Montreal, Laval, Trois-Rivieres, Quebec ou Ottawa.";

const demoAnnouncements = [
  {
    id: "demo-1",
    title: "Bois d'oeuvre vers Laval",
    pickupCity: "Trois-Rivieres",
    deliveryCity: "Laval",
    cargoType: "Bois",
    equipment: "Flatbed",
    loadingDate: "2026-04-24",
    tripsTotal: 4,
    remainingTrips: 3,
    budget: 1650,
    notes: "Chargement matinal, arrimage obligatoire.",
    companyName: "Bois Martin Inc.",
  },
  {
    id: "demo-2",
    title: "Transport de tuyaux industriels",
    pickupCity: "Drummondville",
    deliveryCity: "Sherbrooke",
    cargoType: "Tuyaux",
    equipment: "Plateforme",
    loadingDate: "2026-04-26",
    tripsTotal: 2,
    remainingTrips: 2,
    budget: 1280,
    notes: "Dechargement sur rendez-vous seulement.",
    companyName: "Ateliers Nordex",
  },
  {
    id: "demo-3",
    title: "Livraison d'autos neuves",
    pickupCity: "Brossard",
    deliveryCity: "Ottawa",
    cargoType: "Autos",
    equipment: "Porte-autos",
    loadingDate: "2026-04-28",
    tripsTotal: 3,
    remainingTrips: 1,
    budget: 2450,
    notes: "Inspection photo avant depart demandee.",
    companyName: "AutoNova Distribution",
  },
];

let healthCheckPromise = null;

function createEmptyDraftAnnouncement() {
  return {
    title: "",
    pickupCity: "",
    deliveryCity: "",
    cargoType: "",
    cargoTypeOther: "",
    equipment: "",
    loadingDate: "",
    tripsTotal: "",
    budget: "",
    notes: "",
  };
}

function createDefaultCompanyAiState() {
  return {
    requestText: "",
    status: "idle",
    assistantMessage: "",
    missingFields: [],
    error: "",
  };
}

function createDefaultCarrierAiState() {
  return {
    requestText: "",
    status: "idle",
    assistantMessage: "",
    matches: [],
    suggestedFilters: {
      pickupCity: "",
      deliveryCity: "",
      cargoType: "",
      equipment: "",
    },
    error: "",
  };
}

function createDefaultServerState() {
  return {
    checked: false,
    available: false,
    geminiConfigured: false,
    model: "",
  };
}

function createDefaultState() {
  return {
    activeRole: null,
    profiles: {
      company: {
        legalName: "",
        businessNumber: "",
        contactName: "",
        email: "",
        phone: "",
        city: "",
        province: "",
        industry: "",
      },
      carrier: {
        transportCompany: "",
        businessNumber: "",
        contactName: "",
        email: "",
        phone: "",
        fleetSize: "",
        regions: "",
        equipmentTypes: [],
      },
    },
    announcements: demoAnnouncements.map((announcement) => ({ ...announcement })),
    filters: {
      pickupCity: "",
      deliveryCity: "",
      cargoType: "",
      equipment: "",
    },
    draftAnnouncement: createEmptyDraftAnnouncement(),
    companyAi: createDefaultCompanyAiState(),
    carrierAi: createDefaultCarrierAiState(),
    server: createDefaultServerState(),
  };
}

let state = loadState();

const appElement = document.querySelector("#app");
const topbarActionsElement = document.querySelector("#topbar-actions");

document.addEventListener("click", handleClick);
document.addEventListener("submit", handleSubmit);
document.addEventListener("change", handleChange);

render();
ensureServerHealth();

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return createDefaultState();
    }

    const parsed = JSON.parse(raw);
    const defaults = createDefaultState();

    return {
      ...defaults,
      ...parsed,
      profiles: {
        company: {
          ...defaults.profiles.company,
          ...(parsed.profiles?.company || {}),
        },
        carrier: {
          ...defaults.profiles.carrier,
          ...(parsed.profiles?.carrier || {}),
          equipmentTypes: Array.isArray(parsed.profiles?.carrier?.equipmentTypes)
            ? parsed.profiles.carrier.equipmentTypes
            : defaults.profiles.carrier.equipmentTypes,
        },
      },
      announcements:
        Array.isArray(parsed.announcements) && parsed.announcements.length
          ? parsed.announcements.map((announcement) => normalizeStoredAnnouncement(announcement))
          : defaults.announcements,
      filters: {
        ...defaults.filters,
        ...(parsed.filters || {}),
      },
      draftAnnouncement: {
        ...defaults.draftAnnouncement,
        ...(parsed.draftAnnouncement || {}),
      },
      companyAi: {
        ...defaults.companyAi,
        ...(parsed.companyAi || {}),
        status: "idle",
        error: "",
      },
      carrierAi: {
        ...defaults.carrierAi,
        ...(parsed.carrierAi || {}),
        status: "idle",
        error: "",
        matches: Array.isArray(parsed.carrierAi?.matches) ? parsed.carrierAi.matches : [],
      },
      server: defaults.server,
    };
  } catch (error) {
    return createDefaultState();
  }
}

function saveState() {
  const persisted = {
    ...state,
    companyAi: {
      ...state.companyAi,
      status: "idle",
      error: "",
    },
    carrierAi: {
      ...state.carrierAi,
      status: "idle",
      error: "",
    },
    server: createDefaultServerState(),
  };

  localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
}

function updateState(partial) {
  state = {
    ...state,
    ...partial,
  };
  saveState();
  render();
}

function render() {
  renderTopbarActions();

  if (!state.activeRole) {
    appElement.innerHTML = renderLanding();
    syncConditionalFields();
    return;
  }

  if (!isProfileComplete(state.activeRole)) {
    appElement.innerHTML = renderProfileSetup(state.activeRole);
    syncConditionalFields();
    return;
  }

  appElement.innerHTML =
    state.activeRole === "company"
      ? renderCompanyDashboard()
      : renderCarrierDashboard();

  syncConditionalFields();
}

function renderTopbarActions() {
  if (!state.activeRole) {
    topbarActionsElement.innerHTML = `
      <span class="pill-note">Choisissez votre interface de depart</span>
      <button class="ghost-button" type="button" data-action="reset-app">
        Reinitialiser la demo
      </button>
    `;
    return;
  }

  const currentSpace =
    state.activeRole === "company" ? "Espace entreprise" : "Espace transporteur";

  topbarActionsElement.innerHTML = `
    <span class="role-badge">${currentSpace}</span>
    <button class="ghost-button" type="button" data-action="go-home">
      Retour a l'accueil
    </button>
    <button class="ghost-button" type="button" data-action="reset-app">
      Reinitialiser la demo
    </button>
  `;
}

function renderLanding() {
  const aiCopy = state.server.geminiConfigured
    ? "Gemini peut aider a rediger les annonces et a classer les voyages compatibles."
    : "Ajoutez Gemini plus tard pour avoir un assistant d'annonce et un score de compatibilite intelligent.";

  return `
    <section class="hero-grid">
      <article class="hero-card">
        <div>
          <span class="eyebrow">Place de marche logistique</span>
          <h1 class="hero-title">Relier les PME aux petits transporteurs.</h1>
          <p class="hero-copy">
            ${APP_NAME} aide les entreprises a publier plusieurs voyages en une seule annonce
            et permet aux transporteurs de 1 a 4 camions de trouver des trajets adaptes a leur equipement.
          </p>

          <div class="hero-stats">
            <div class="summary-card">
              <span>Profils obligatoires</span>
              <strong>100%</strong>
              <small class="muted">avant de publier ou de chercher</small>
            </div>
            <div class="summary-card">
              <span>Annonces visibles</span>
              <strong>Actives</strong>
              <small class="muted">les annonces completes disparaissent cote transporteur</small>
            </div>
            <div class="summary-card">
              <span>Assistant IA</span>
              <strong>${state.server.geminiConfigured ? "Pret" : "Optionnel"}</strong>
              <small class="muted">${aiCopy}</small>
            </div>
          </div>
        </div>

        <div class="accent-block">
          <strong>Parcours deja testable</strong>
          <p class="muted">
            Choisissez un role, completez le profil demande, puis continuez vers l'interface correspondante.
          </p>
        </div>
      </article>

      <div class="hero-side">
        <article class="action-card active-card">
          <span class="card-icon">ENT</span>
          <div>
            <h2 class="section-title">Je suis une entreprise</h2>
            <p>
              Creez votre identite d'entreprise, publiez des besoins de transport et gerez le nombre
              de voyages restants depuis un seul tableau de bord.
            </p>
          </div>
          <ul class="helper-list">
            <li>Profil entreprise obligatoire avant publication</li>
            <li>Creation d'annonces avec plusieurs voyages</li>
            <li>Assistant IA pour transformer un texte libre en annonce</li>
          </ul>
          <div class="inline-actions">
            <button class="primary-button" type="button" data-action="choose-role" data-role="company">
              Commencer comme entreprise
            </button>
            <span class="pill-note">Pour PME et chargeurs locaux</span>
          </div>
        </article>

        <article class="action-card">
          <span class="card-icon">TRP</span>
          <div>
            <h2 class="section-title">Je suis un transporteur</h2>
            <p>
              Completez votre profil transporteur puis filtrez les annonces par ville, marchandise
              ou equipement requis pour trouver les voyages utiles.
            </p>
          </div>
          <ul class="helper-list">
            <li>Parfait pour les flottes de 1 a 4 camions</li>
            <li>Recherche guidee avec filtres</li>
            <li>Compatibilite locale et recommandations IA</li>
          </ul>
          <div class="inline-actions">
            <button class="ghost-button" type="button" data-action="choose-role" data-role="carrier">
              Entrer comme transporteur
            </button>
            <span class="pill-note">Trajets cibles, pas de bruit inutile</span>
          </div>
        </article>
      </div>
    </section>
  `;
}

function renderProfileSetup(role) {
  const profile = state.profiles[role];
  const isCompany = role === "company";
  const roleLabel = isCompany ? "Entreprise" : "Transporteur";

  return `
    <section class="profile-grid">
      <article class="form-card">
        <div class="section-head">
          <div>
            <span class="eyebrow">Etape 1</span>
            <h1 class="section-title">Completer votre profil ${roleLabel.toLowerCase()}.</h1>
            <p class="section-copy">
              Tant que ce profil n'est pas rempli, vous ne pouvez pas ${
                isCompany ? "publier d'annonce" : "chercher des voyages"
              }.
            </p>
          </div>

          <div class="status-box">
            <span class="status-badge pending">Profil requis</span>
            <p class="status-copy">
              ${
                isCompany
                  ? "Ajoutez les identifiants de votre entreprise et le contact principal."
                  : "Ajoutez la compagnie de transport, les regions couvertes et votre equipement."
              }
            </p>
          </div>
        </div>

        <form id="profile-form" class="profile-form">
          ${isCompany ? renderCompanyProfileFields(profile) : renderCarrierProfileFields(profile)}

          <div class="form-footer">
            <button class="primary-button" type="submit">
              Enregistrer le profil et continuer
            </button>
            <button class="ghost-button" type="button" data-action="go-home">
              Retour a l'accueil
            </button>
          </div>
        </form>
      </article>

      <aside class="form-card">
        <span class="eyebrow">Ce qui debloque la suite</span>
        <h2 class="section-title">${isCompany ? "Publier des annonces" : "Filtrer les voyages"}</h2>
        <p class="section-copy">
          Le profil sert a creer un niveau de confiance des la premiere utilisation et a preparer
          une interface adaptee au bon metier.
        </p>

        <div class="stack">
          <div class="accent-block">
            <strong>${isCompany ? "Apres ce formulaire" : "Une fois ce profil complete"}</strong>
            <p class="muted">
              ${
                isCompany
                  ? "Vous arriverez sur un tableau de bord pour creer des annonces, suivre vos voyages restants et utiliser l'assistant IA."
                  : "Vous arriverez sur une interface de recherche avec filtres, score de compatibilite et suggestions IA."
              }
            </p>
          </div>

          <div class="summary-card">
            <span>Champs cles</span>
            <strong>${isCompany ? "Identite" : "Flotte"}</strong>
            <small class="muted">
              ${
                isCompany
                  ? "Nom legal, numero d'entreprise, contact"
                  : "Compagnie, nombre de camions, equipements"
              }
            </small>
          </div>

          <div class="summary-card">
            <span>Experience visee</span>
            <strong>Simple</strong>
            <small class="muted">mobile, rapide, pensee pour le terrain</small>
          </div>
        </div>
      </aside>
    </section>
  `;
}

function renderCompanyProfileFields(profile) {
  return `
    <div class="field-grid">
      <div class="field">
        <label for="legalName">Nom legal de l'entreprise</label>
        <input id="legalName" name="legalName" value="${escapeHtml(profile.legalName)}" required />
      </div>

      <div class="field">
        <label for="businessNumber">Numero d'entreprise</label>
        <input id="businessNumber" name="businessNumber" value="${escapeHtml(profile.businessNumber)}" required />
      </div>

      <div class="field">
        <label for="contactName">Nom du responsable</label>
        <input id="contactName" name="contactName" value="${escapeHtml(profile.contactName)}" required />
      </div>

      <div class="field">
        <label for="email">Courriel</label>
        <input id="email" name="email" type="email" value="${escapeHtml(profile.email)}" required />
      </div>

      <div class="field">
        <label for="phone">Telephone</label>
        <input id="phone" name="phone" value="${escapeHtml(profile.phone)}" required />
      </div>

      <div class="field">
        <label for="city">Ville</label>
        <input id="city" name="city" value="${escapeHtml(profile.city)}" required />
      </div>

      <div class="field">
        <label for="province">Province</label>
        <select id="province" name="province" required>
          <option value="">Choisir</option>
          ${provinceOptions
            .map(
              (province) => `
                <option value="${province}" ${profile.province === province ? "selected" : ""}>${province}</option>
              `,
            )
            .join("")}
        </select>
      </div>

      <div class="field">
        <label for="industry">Secteur d'activite</label>
        <input
          id="industry"
          name="industry"
          value="${escapeHtml(profile.industry)}"
          placeholder="Bois, materiaux, beton, automobile..."
          required
        />
      </div>
    </div>
  `;
}

function renderCarrierProfileFields(profile) {
  return `
    <div class="field-grid">
      <div class="field">
        <label for="transportCompany">Nom de la compagnie de transport</label>
        <input
          id="transportCompany"
          name="transportCompany"
          value="${escapeHtml(profile.transportCompany)}"
          required
        />
      </div>

      <div class="field">
        <label for="carrierBusinessNumber">Numero d'entreprise</label>
        <input
          id="carrierBusinessNumber"
          name="businessNumber"
          value="${escapeHtml(profile.businessNumber)}"
          required
        />
      </div>

      <div class="field">
        <label for="carrierContactName">Nom du responsable</label>
        <input
          id="carrierContactName"
          name="contactName"
          value="${escapeHtml(profile.contactName)}"
          required
        />
      </div>

      <div class="field">
        <label for="carrierEmail">Courriel</label>
        <input id="carrierEmail" name="email" type="email" value="${escapeHtml(profile.email)}" required />
      </div>

      <div class="field">
        <label for="carrierPhone">Telephone</label>
        <input id="carrierPhone" name="phone" value="${escapeHtml(profile.phone)}" required />
      </div>

      <div class="field">
        <label for="fleetSize">Nombre de camions</label>
        <input
          id="fleetSize"
          name="fleetSize"
          type="number"
          min="1"
          max="4"
          value="${escapeHtml(profile.fleetSize)}"
          required
        />
      </div>

      <div class="field full">
        <label for="regions">Regions desservies</label>
        <input
          id="regions"
          name="regions"
          value="${escapeHtml(profile.regions)}"
          placeholder="Exemple: Montreal, Quebec, Ontario Est"
          required
        />
      </div>

      <fieldset class="field full">
        <legend>Equipements disponibles</legend>
        <div class="chip-group">
          ${equipmentOptions
            .map(
              (equipment) => `
                <label class="chip">
                  <input
                    type="checkbox"
                    name="equipmentTypes"
                    value="${equipment}"
                    ${profile.equipmentTypes.includes(equipment) ? "checked" : ""}
                  />
                  <span>${equipment}</span>
                </label>
              `,
            )
            .join("")}
        </div>
        <small class="field-help">
          Choisissez un ou plusieurs equipements de votre flotte, par exemple flatbed, drybox,
          dribox, fardier, benne ou porte-autos.
        </small>
      </fieldset>
    </div>
  `;
}

function renderCompanyDashboard() {
  const companyProfile = state.profiles.company;
  const companyAnnouncements = getCompanyAnnouncements();
  const activeCount = companyAnnouncements.filter((item) => item.remainingTrips > 0).length;
  const completeCount = companyAnnouncements.filter((item) => item.remainingTrips === 0).length;
  const remainingTrips = companyAnnouncements.reduce((total, item) => total + item.remainingTrips, 0);
  const draft = state.draftAnnouncement;

  return `
    <section class="dashboard-grid">
      <aside class="dashboard-stack">
        <article class="form-card">
          <div class="section-head">
            <div>
              <span class="eyebrow">Espace entreprise</span>
              <h1 class="section-title">Publier et suivre vos voyages.</h1>
              <p class="section-copy">
                ${escapeHtml(companyProfile.legalName)} peut maintenant creer des annonces, suivre le solde de voyages disponibles et se faire aider par Gemini.
              </p>
            </div>
            <span class="status-badge complete">Profil complete</span>
          </div>

          <div class="metrics-row">
            <div class="compact-card">
              <span>Annonces actives</span>
              <strong>${activeCount}</strong>
            </div>
            <div class="compact-card">
              <span>Voyages restants</span>
              <strong>${remainingTrips}</strong>
            </div>
            <div class="compact-card">
              <span>Annonces completees</span>
              <strong>${completeCount}</strong>
            </div>
          </div>
        </article>

        <article class="form-card ai-card">
          <div class="split-header">
            <div>
              <span class="eyebrow">Assistant Gemini</span>
              <h2 class="section-title">Transformer un texte libre en annonce</h2>
            </div>
            <span class="metric-badge">Entreprise</span>
          </div>

          ${renderAiAvailabilityNotice()}

          <form id="company-ai-form" class="profile-form">
            <div class="field full">
              <label for="companyAiPrompt">Decrivez le voyage comme vous le diriez au telephone</label>
              <textarea
                id="companyAiPrompt"
                class="ai-textarea"
                name="requestText"
                placeholder="Exemple: J'ai 2 voyages de tuyaux a faire de Drummondville vers Sherbrooke mardi avec une plateforme..."
                required
              >${escapeHtml(state.companyAi.requestText)}</textarea>
            </div>

            <div class="form-footer">
              <button class="primary-button" type="submit" ${isAiInteractive() ? "" : "disabled"}>
                ${state.companyAi.status === "loading" ? "Generation en cours..." : "Generer mon annonce avec Gemini"}
              </button>
              <button class="ghost-button" type="button" data-action="use-company-example">
                Inserer un exemple
              </button>
            </div>
          </form>

          ${renderCompanyAiFeedback()}
        </article>

        <article class="form-card">
          <div class="split-header">
            <div>
              <span class="eyebrow">Nouvelle annonce</span>
              <h2 class="section-title">Creer un besoin de transport</h2>
            </div>
            <span class="metric-badge">Plusieurs voyages par annonce</span>
          </div>

          <form id="announcement-form" class="announcement-form">
            <div class="field-grid">
              <div class="field full">
                <label for="title">Titre de l'annonce</label>
                <input id="title" name="title" value="${escapeHtml(draft.title)}" placeholder="Exemple: Bois vers Quebec" required />
              </div>

              <div class="field">
                <label for="pickupCity">Ville de chargement</label>
                <input id="pickupCity" name="pickupCity" value="${escapeHtml(draft.pickupCity)}" required />
              </div>

              <div class="field">
                <label for="deliveryCity">Ville de livraison</label>
                <input id="deliveryCity" name="deliveryCity" value="${escapeHtml(draft.deliveryCity)}" required />
              </div>

              <div class="field">
                <label for="cargoType">Type de marchandise</label>
                <select id="cargoType" name="cargoType" required>
                  <option value="">Choisir</option>
                  ${suggestedCargoOptions
                    .map(
                      (cargo) => `
                        <option value="${cargo}" ${getDraftCargoSelectValue(draft) === cargo ? "selected" : ""}>${cargo}</option>
                      `,
                    )
                    .join("")}
                  <option value="${OTHER_CARGO_VALUE}" ${getDraftCargoSelectValue(draft) === OTHER_CARGO_VALUE ? "selected" : ""}>
                    Autres (precisez)
                  </option>
                </select>
              </div>

              <div class="field full ${getDraftCargoSelectValue(draft) === OTHER_CARGO_VALUE ? "" : "hidden"}" id="cargoTypeOtherField">
                <label for="cargoTypeOther">Precisez la marchandise</label>
                <input
                  id="cargoTypeOther"
                  name="cargoTypeOther"
                  value="${escapeHtml(draft.cargoTypeOther)}"
                  placeholder="Exemple: acier, machinerie, grain, equipement specialise..."
                />
              </div>

              <div class="field">
                <label for="equipment">Equipement requis</label>
                <select id="equipment" name="equipment" required>
                  <option value="">Choisir</option>
                  ${equipmentOptions
                    .map(
                      (equipment) => `
                        <option value="${equipment}" ${draft.equipment === equipment ? "selected" : ""}>${equipment}</option>
                      `,
                    )
                    .join("")}
                </select>
              </div>

              <div class="field">
                <label for="loadingDate">Date de chargement</label>
                <input id="loadingDate" name="loadingDate" type="date" value="${escapeHtml(draft.loadingDate)}" required />
              </div>

              <div class="field">
                <label for="tripsTotal">Nombre de voyages disponibles</label>
                <input id="tripsTotal" name="tripsTotal" type="number" min="1" value="${escapeHtml(draft.tripsTotal)}" required />
              </div>

              <div class="field">
                <label for="budget">Budget propose (CAD)</label>
                <input id="budget" name="budget" type="number" min="0" step="50" value="${escapeHtml(draft.budget)}" required />
              </div>

              <div class="field full">
                <label for="notes">Consignes speciales</label>
                <textarea
                  id="notes"
                  name="notes"
                  placeholder="Exemple: Arrimage requis, appel 30 minutes avant arrivee..."
                >${escapeHtml(draft.notes)}</textarea>
              </div>
            </div>

            <div class="form-footer">
              <button class="primary-button" type="submit">Publier l'annonce</button>
              <button class="ghost-button" type="button" data-action="clear-announcement-draft">
                Vider le brouillon
              </button>
            </div>
          </form>
        </article>
      </aside>

      <section class="results-stack">
        <article class="form-card">
          <div class="split-header">
            <div>
              <span class="eyebrow">Vos annonces</span>
              <h2 class="section-title">Activite recente</h2>
            </div>
            <span class="metric-badge">${companyAnnouncements.length} annonce(s)</span>
          </div>

          ${
            companyAnnouncements.length
              ? companyAnnouncements
                  .slice()
                  .reverse()
                  .map(renderCompanyAnnouncementCard)
                  .join("")
              : `
                <div class="empty-card">
                  <strong>Encore aucune annonce</strong>
                  <p class="muted">
                    La premiere annonce creee ici apparaitra aussi dans l'espace transporteur si des voyages restent disponibles.
                  </p>
                </div>
              `
          }
        </article>
      </section>
    </section>
  `;
}

function renderCompanyAiFeedback() {
  const companyAi = state.companyAi;
  let html = "";

  if (companyAi.status === "loading") {
    html += `<div class="notice info">Gemini analyse votre description et prepare un brouillon d'annonce...</div>`;
  }

  if (companyAi.assistantMessage) {
    html += `<div class="notice success">${escapeHtml(companyAi.assistantMessage)}</div>`;
  }

  if (companyAi.missingFields.length) {
    html += `
      <div class="notice warning">
        <strong>Points a verifier avant publication</strong>
        <ul class="helper-list">
          ${companyAi.missingFields.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
        </ul>
      </div>
    `;
  }

  if (companyAi.error) {
    html += `<div class="notice error">${escapeHtml(companyAi.error)}</div>`;
  }

  return html;
}

function renderCompanyAnnouncementCard(announcement) {
  const statusClass = announcement.remainingTrips > 0 ? "active" : "complete";
  const statusLabel = announcement.remainingTrips > 0 ? "Active" : "Completee";
  const canAssignOne = announcement.remainingTrips >= 1;
  const canAssignTwo = announcement.remainingTrips >= 2;

  return `
    <article class="announcement-card">
      <div class="card-head">
        <div>
          <h3 class="card-title">${escapeHtml(announcement.title)}</h3>
          <div class="card-subtitle">${escapeHtml(announcement.companyName || state.profiles.company.legalName)}</div>
        </div>
        <span class="status-badge ${statusClass}">${statusLabel}</span>
      </div>

      <div class="route-line">
        <span>${escapeHtml(announcement.pickupCity)}</span>
        <span class="arrow">-></span>
        <span>${escapeHtml(announcement.deliveryCity)}</span>
      </div>

      <div class="meta-grid">
        <div>
          <span>Marchandise</span>
          <strong>${escapeHtml(announcement.cargoType)}</strong>
        </div>
        <div>
          <span>Equipement</span>
          <strong>${escapeHtml(announcement.equipment)}</strong>
        </div>
        <div>
          <span>Voyages restants</span>
          <strong>${announcement.remainingTrips} / ${announcement.tripsTotal}</strong>
        </div>
        <div>
          <span>Budget</span>
          <strong>${formatCurrency(announcement.budget)}</strong>
        </div>
      </div>

      <p class="muted">${escapeHtml(announcement.notes || "Aucune consigne speciale ajoutee.")}</p>

      <div class="card-actions">
        <button
          class="tiny-button primary ${canAssignOne ? "" : "hidden"}"
          type="button"
          data-action="assign-trips"
          data-id="${announcement.id}"
          data-amount="1"
        >
          Attribuer 1 voyage
        </button>
        <button
          class="tiny-button ${canAssignTwo ? "" : "hidden"}"
          type="button"
          data-action="assign-trips"
          data-id="${announcement.id}"
          data-amount="2"
        >
          Attribuer 2 voyages
        </button>
      </div>
    </article>
  `;
}

function renderCarrierDashboard() {
  const carrierProfile = state.profiles.carrier;
  const rankedResults = getRankedCarrierResults();

  return `
    <section class="dashboard-grid">
      <aside class="dashboard-stack">
        <article class="form-card">
          <div class="section-head">
            <div>
              <span class="eyebrow">Espace transporteur</span>
              <h1 class="section-title">Trouver des voyages compatibles.</h1>
              <p class="section-copy">
                ${escapeHtml(carrierProfile.transportCompany)} peut filtrer les annonces encore actives, puis utiliser Gemini pour trouver les voyages les plus pertinents.
              </p>
            </div>
            <span class="status-badge complete">Profil complete</span>
          </div>

          <div class="metrics-row">
            <div class="compact-card">
              <span>Camions declares</span>
              <strong>${escapeHtml(carrierProfile.fleetSize)}</strong>
            </div>
            <div class="compact-card">
              <span>Equipements</span>
              <strong>${carrierProfile.equipmentTypes.length || 0}</strong>
            </div>
            <div class="compact-card">
              <span>Annonces disponibles</span>
              <strong>${getActiveAnnouncements().length}</strong>
            </div>
          </div>
        </article>

        <article class="form-card ai-card">
          <div class="split-header">
            <div>
              <span class="eyebrow">Assistant Gemini</span>
              <h2 class="section-title">Trouver vos meilleurs matchs</h2>
            </div>
            <span class="metric-badge">Transporteur</span>
          </div>

          ${renderAiAvailabilityNotice()}

          <form id="carrier-ai-form" class="profile-form">
            <div class="field full">
              <label for="carrierAiPrompt">Dites a Gemini ce que vous cherchez</label>
              <textarea
                id="carrierAiPrompt"
                class="ai-textarea"
                name="requestText"
                placeholder="Exemple: Je veux surtout des voyages flatbed ou drybox entre Montreal, Quebec et Ottawa."
                required
              >${escapeHtml(state.carrierAi.requestText)}</textarea>
            </div>

            <div class="form-footer">
              <button class="primary-button" type="submit" ${isAiInteractive() ? "" : "disabled"}>
                ${state.carrierAi.status === "loading" ? "Analyse en cours..." : "Trouver mes meilleurs voyages"}
              </button>
              <button class="ghost-button" type="button" data-action="use-carrier-example">
                Inserer un exemple
              </button>
            </div>
          </form>

          ${renderCarrierAiFeedback()}
        </article>

        <article class="form-card">
          <div class="split-header">
            <div>
              <span class="eyebrow">Recherche</span>
              <h2 class="section-title">Filtrer les annonces</h2>
            </div>
            <button class="ghost-button" type="button" data-action="clear-filters">
              Reinitialiser
            </button>
          </div>

          <form class="filters-form" id="filters-form">
            <div class="field">
              <label for="filterPickupCity">Ville de chargement</label>
              <input
                id="filterPickupCity"
                name="pickupCity"
                value="${escapeHtml(state.filters.pickupCity)}"
                placeholder="Exemple: Montreal"
              />
            </div>

            <div class="field">
              <label for="filterDeliveryCity">Ville de livraison</label>
              <input
                id="filterDeliveryCity"
                name="deliveryCity"
                value="${escapeHtml(state.filters.deliveryCity)}"
                placeholder="Exemple: Quebec"
              />
            </div>

            <div class="field">
              <label for="filterCargoType">Marchandise</label>
              <select id="filterCargoType" name="cargoType">
                <option value="">Toutes</option>
                ${getCargoFilterOptions()
                  .map(
                    (cargo) => `
                      <option value="${cargo}" ${state.filters.cargoType === cargo ? "selected" : ""}>${cargo}</option>
                    `,
                  )
                  .join("")}
              </select>
            </div>

            <div class="field">
              <label for="filterEquipment">Equipement requis</label>
              <select id="filterEquipment" name="equipment">
                <option value="">Tous</option>
                ${equipmentOptions
                  .map(
                    (equipment) => `
                      <option value="${equipment}" ${state.filters.equipment === equipment ? "selected" : ""}>${equipment}</option>
                    `,
                  )
                  .join("")}
              </select>
            </div>

            <div class="filters-actions">
              <span class="metric-badge">${rankedResults.length} resultat(s)</span>
              <span class="pill-note">Les annonces avec 0 voyage restant n'apparaissent pas.</span>
            </div>
          </form>
        </article>

        <article class="form-card">
          <span class="eyebrow">Votre flotte</span>
          <h2 class="section-title">Resume du profil</h2>
          <p class="muted">Regions : ${escapeHtml(carrierProfile.regions)}</p>
          <div class="chip-group">
            ${carrierProfile.equipmentTypes
              .map((equipment) => `<span class="metric-badge">${escapeHtml(equipment)}</span>`)
              .join("")}
          </div>
        </article>
      </aside>

      <section class="results-stack">
        <article class="form-card">
          <div class="split-header">
            <div>
              <span class="eyebrow">Resultats actifs</span>
              <h2 class="section-title">Annonces disponibles</h2>
            </div>
            <span class="metric-badge">${rankedResults.length} correspondance(s)</span>
          </div>

          ${
            rankedResults.length
              ? rankedResults.map(renderCarrierResultCard).join("")
              : `
                <div class="empty-card">
                  <strong>Aucune annonce ne correspond pour l'instant</strong>
                  <p class="muted">
                    Ajustez les filtres pour elargir la recherche ou revenez plus tard quand de nouvelles annonces seront creees.
                  </p>
                </div>
              `
          }
        </article>
      </section>
    </section>
  `;
}

function renderCarrierAiFeedback() {
  const carrierAi = state.carrierAi;
  let html = "";

  if (carrierAi.status === "loading") {
    html += `<div class="notice info">Gemini compare votre profil avec les annonces actives...</div>`;
  }

  if (carrierAi.assistantMessage) {
    html += `<div class="notice success">${escapeHtml(carrierAi.assistantMessage)}</div>`;
  }

  if (hasSuggestedFilters(carrierAi.suggestedFilters)) {
    html += `
      <div class="notice info">
        <strong>Filtres proposes par Gemini</strong>
        <div class="chip-group">
          ${renderSuggestedFilterTags(carrierAi.suggestedFilters)}
        </div>
        <div class="form-footer">
          <button class="tiny-button primary" type="button" data-action="apply-ai-filters">
            Appliquer les filtres proposes
          </button>
        </div>
      </div>
    `;
  }

  if (carrierAi.matches.length) {
    html += `
      <div class="ai-response-list">
        ${carrierAi.matches
          .slice(0, 5)
          .map(
            (match) => `
              <div class="ai-match-card">
                <div class="score-row">
                  <span class="score-pill ai">Gemini ${clampScore(match.score)}%</span>
                  <span class="pill-note">${escapeHtml(findAnnouncementTitle(match.announcementId))}</span>
                </div>
                <p class="small-copy">${escapeHtml(match.reasoning || "Compatibilite analysee par Gemini.")}</p>
              </div>
            `,
          )
          .join("")}
      </div>
    `;
  }

  if (carrierAi.error) {
    html += `<div class="notice error">${escapeHtml(carrierAi.error)}</div>`;
  }

  return html;
}

function renderCarrierResultCard(result) {
  const announcement = result.announcement;

  return `
    <article class="result-card">
      <div class="card-head">
        <div>
          <h3 class="card-title">${escapeHtml(announcement.title)}</h3>
          <div class="card-subtitle">${escapeHtml(announcement.companyName)}</div>
        </div>
        <span class="status-badge active">${announcement.remainingTrips} voyage(s) restant(s)</span>
      </div>

      <div class="route-line">
        <span>${escapeHtml(announcement.pickupCity)}</span>
        <span class="arrow">-></span>
        <span>${escapeHtml(announcement.deliveryCity)}</span>
      </div>

      <div class="score-row">
        <span class="score-pill local">Compatibilite locale ${result.localScore}%</span>
        ${
          result.aiScore !== null
            ? `<span class="score-pill ai">Gemini ${result.aiScore}%</span>`
            : ""
        }
      </div>

      <div class="meta-grid">
        <div>
          <span>Chargement</span>
          <strong>${formatDate(announcement.loadingDate)}</strong>
        </div>
        <div>
          <span>Marchandise</span>
          <strong>${escapeHtml(announcement.cargoType)}</strong>
        </div>
        <div>
          <span>Equipement</span>
          <strong>${escapeHtml(announcement.equipment)}</strong>
        </div>
        <div>
          <span>Budget</span>
          <strong>${formatCurrency(announcement.budget)}</strong>
        </div>
      </div>

      ${
        result.aiReasoning
          ? `<p class="small-copy">${escapeHtml(result.aiReasoning)}</p>`
          : ""
      }
      <p class="muted">${escapeHtml(announcement.notes || "Aucune consigne speciale ajoutee.")}</p>
    </article>
  `;
}

function renderAiAvailabilityNotice() {
  if (!state.server.checked) {
    return `<div class="notice info">Verification du serveur local en cours...</div>`;
  }

  if (!state.server.available) {
    return `
      <div class="notice warning">
        L'assistant IA a besoin du serveur local. Lancez <code>node server.js</code> puis ouvrez
        <code>http://localhost:${DEFAULT_PORT}</code>.
      </div>
    `;
  }

  if (!state.server.geminiConfigured) {
    return `
      <div class="notice warning">
        Le serveur local fonctionne, mais Gemini n'est pas encore configure. Ajoutez votre cle dans
        <code>.env</code> avec <code>GEMINI_API_KEY=...</code>.
      </div>
    `;
  }

  return `
    <div class="notice success">
      Gemini est pret sur le serveur local${state.server.model ? ` (${escapeHtml(state.server.model)})` : ""}.
    </div>
  `;
}

function isAiInteractive() {
  return state.server.available && state.server.geminiConfigured;
}

function getCompanyAnnouncements() {
  const companyName = state.profiles.company.legalName;
  if (!companyName) {
    return [];
  }

  return state.announcements.filter((announcement) => announcement.companyName === companyName);
}

function getActiveAnnouncements() {
  return state.announcements.filter((announcement) => announcement.remainingTrips > 0);
}

function getCargoFilterOptions() {
  const cargoSet = new Set(suggestedCargoOptions);

  state.announcements.forEach((announcement) => {
    if (announcement.cargoType) {
      cargoSet.add(announcement.cargoType);
    }
  });

  return Array.from(cargoSet).sort((left, right) =>
    left.localeCompare(right, "fr-CA", { sensitivity: "base" }),
  );
}

function getFilteredAnnouncements() {
  const filters = state.filters;

  return getActiveAnnouncements().filter((announcement) => {
    return (
      matchesFilter(announcement.pickupCity, filters.pickupCity) &&
      matchesFilter(announcement.deliveryCity, filters.deliveryCity) &&
      matchesFilter(announcement.cargoType, filters.cargoType) &&
      matchesEquipmentFilter(announcement.equipment, filters.equipment)
    );
  });
}

function getRankedCarrierResults() {
  const aiMatchMap = getCarrierAiMatchMap();

  return getFilteredAnnouncements()
    .map((announcement) => {
      const aiMatch = aiMatchMap.get(announcement.id) || null;
      const localScore = calculateLocalCompatibility(state.profiles.carrier, announcement);

      return {
        announcement,
        localScore,
        aiScore: aiMatch ? clampScore(aiMatch.score) : null,
        aiReasoning: aiMatch?.reasoning || "",
      };
    })
    .sort((left, right) => {
      const leftRank = left.aiScore !== null ? left.aiScore : left.localScore;
      const rightRank = right.aiScore !== null ? right.aiScore : right.localScore;
      return rightRank - leftRank;
    });
}

function getCarrierAiMatchMap() {
  const map = new Map();

  state.carrierAi.matches.forEach((match) => {
    if (match && match.announcementId) {
      map.set(match.announcementId, match);
    }
  });

  return map;
}

function calculateLocalCompatibility(profile, announcement) {
  if (!profile || !profile.transportCompany) {
    return 0;
  }

  let score = 30;

  if (equipmentMatches(announcement.equipment, profile.equipmentTypes)) {
    score += 40;
  } else {
    score -= 15;
  }

  if (regionMatches(profile.regions, announcement.pickupCity) || regionMatches(profile.regions, announcement.deliveryCity)) {
    score += 18;
  }

  if (Number(profile.fleetSize) >= 2 && Number(announcement.remainingTrips) >= 2) {
    score += 8;
  }

  if (matchesFilter(profile.regions, announcement.pickupCity)) {
    score += 6;
  }

  if (matchesFilter(profile.regions, announcement.deliveryCity)) {
    score += 6;
  }

  return clampScore(score);
}

function equipmentMatches(requiredEquipment, availableEquipmentList) {
  if (!Array.isArray(availableEquipmentList) || !availableEquipmentList.length) {
    return false;
  }

  const required = normalizeEquipmentForMatch(requiredEquipment);
  return availableEquipmentList.some((equipment) => normalizeEquipmentForMatch(equipment) === required);
}

function matchesEquipmentFilter(value, filter) {
  if (!filter) {
    return true;
  }

  return normalizeEquipmentForMatch(value) === normalizeEquipmentForMatch(filter);
}

function regionMatches(regionsText, city) {
  if (!regionsText || !city) {
    return false;
  }

  return normalizeText(regionsText).includes(normalizeText(city));
}

function matchesFilter(value, filter) {
  if (!filter) {
    return true;
  }

  return normalizeText(value).includes(normalizeText(filter));
}

function normalizeText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function normalizeEquipmentForMatch(value) {
  const normalized = normalizeText(value);

  if (!normalized) {
    return "";
  }

  if (["dry box", "drybox", "dribox", "dry van", "remorque fermee"].includes(normalized)) {
    return "drybox";
  }

  if (["flatbed", "plateforme"].includes(normalized)) {
    return "flatbed";
  }

  if (["reefer", "refrigere", "refrigerated"].includes(normalized)) {
    return "refrigere";
  }

  if (["porte-autos", "porte autos", "car hauler", "auto"].includes(normalized)) {
    return "porte-autos";
  }

  return normalized;
}

function normalizeEquipmentOption(value) {
  const normalized = normalizeText(value);

  if (!normalized) {
    return "";
  }

  const found = equipmentOptions.find((equipment) => normalizeEquipmentForMatch(equipment) === normalizeEquipmentForMatch(normalized));
  return found || "";
}

function normalizeCargoOption(value) {
  const normalized = normalizeText(value);

  if (!normalized) {
    return { cargoType: "", cargoTypeOther: "" };
  }

  const found = suggestedCargoOptions.find((cargo) => normalizeText(cargo) === normalized);

  if (found) {
    return {
      cargoType: found,
      cargoTypeOther: "",
    };
  }

  return {
    cargoType: OTHER_CARGO_VALUE,
    cargoTypeOther: value,
  };
}

function normalizeDateInputValue(value) {
  const clean = cleanText(value);
  if (!clean) {
    return "";
  }

  const exactIsoDate = /^\d{4}-\d{2}-\d{2}$/;
  if (exactIsoDate.test(clean)) {
    return clean;
  }

  const parsedDate = new Date(clean);
  if (Number.isNaN(parsedDate.getTime())) {
    return "";
  }

  return parsedDate.toISOString().slice(0, 10);
}

function getDraftCargoSelectValue(draft) {
  if (draft.cargoType === OTHER_CARGO_VALUE || draft.cargoTypeOther) {
    return OTHER_CARGO_VALUE;
  }

  return draft.cargoType;
}

function resolveDraftCargoValue(draft) {
  if (draft.cargoType === OTHER_CARGO_VALUE) {
    return cleanText(draft.cargoTypeOther);
  }

  return cleanText(draft.cargoType);
}

function isProfileComplete(role) {
  const profile = state.profiles[role];
  const requiredFields =
    role === "company"
      ? ["legalName", "businessNumber", "contactName", "email", "phone", "city", "province", "industry"]
      : ["transportCompany", "businessNumber", "contactName", "email", "phone", "fleetSize", "regions"];

  const baseFieldsFilled = requiredFields.every((field) => String(profile[field] || "").trim());

  if (role === "carrier") {
    return baseFieldsFilled && Array.isArray(profile.equipmentTypes) && profile.equipmentTypes.length > 0;
  }

  return baseFieldsFilled;
}

function handleClick(event) {
  const target = event.target.closest("[data-action]");
  if (!target) {
    return;
  }

  const { action, role, id, amount } = target.dataset;

  if (action === "choose-role") {
    event.preventDefault();
    updateState({ activeRole: role });
    return;
  }

  if (action === "go-home") {
    event.preventDefault();
    updateState({ activeRole: null });
    return;
  }

  if (action === "reset-app") {
    event.preventDefault();
    localStorage.removeItem(STORAGE_KEY);
    state = createDefaultState();
    render();
    ensureServerHealth(true);
    return;
  }

  if (action === "clear-filters") {
    event.preventDefault();
    updateState({
      filters: {
        pickupCity: "",
        deliveryCity: "",
        cargoType: "",
        equipment: "",
      },
      carrierAi: {
        ...state.carrierAi,
        suggestedFilters: {
          pickupCity: "",
          deliveryCity: "",
          cargoType: "",
          equipment: "",
        },
      },
    });
    return;
  }

  if (action === "assign-trips") {
    event.preventDefault();
    assignTrips(id, Number(amount));
    return;
  }

  if (action === "clear-announcement-draft") {
    event.preventDefault();
    updateState({ draftAnnouncement: createEmptyDraftAnnouncement() });
    return;
  }

  if (action === "use-company-example") {
    event.preventDefault();
    updateState({
      companyAi: {
        ...state.companyAi,
        requestText: companyExamplePrompt,
      },
    });
    return;
  }

  if (action === "use-carrier-example") {
    event.preventDefault();
    updateState({
      carrierAi: {
        ...state.carrierAi,
        requestText: carrierExamplePrompt,
      },
    });
    return;
  }

  if (action === "apply-ai-filters") {
    event.preventDefault();
    updateState({
      filters: {
        ...state.filters,
        ...normalizeSuggestedFilters(state.carrierAi.suggestedFilters),
      },
    });
  }
}

async function handleSubmit(event) {
  if (event.target.id === "profile-form") {
    event.preventDefault();
    submitProfile(event.target);
    return;
  }

  if (event.target.id === "announcement-form") {
    event.preventDefault();
    submitAnnouncement(event.target);
    return;
  }

  if (event.target.id === "company-ai-form") {
    event.preventDefault();
    await submitCompanyAi(event.target);
    return;
  }

  if (event.target.id === "carrier-ai-form") {
    event.preventDefault();
    await submitCarrierAi(event.target);
  }
}

function handleChange(event) {
  syncConditionalFields();

  const formId = event.target.form?.id;
  if (!formId) {
    return;
  }

  if (formId === "filters-form") {
    const formData = new FormData(event.target.form);
    updateState({
      filters: {
        pickupCity: cleanText(formData.get("pickupCity")),
        deliveryCity: cleanText(formData.get("deliveryCity")),
        cargoType: cleanText(formData.get("cargoType")),
        equipment: cleanText(formData.get("equipment")),
      },
    });
    return;
  }

  if (formId === "announcement-form") {
    updateState({
      draftAnnouncement: readAnnouncementDraft(event.target.form),
    });
    return;
  }

  if (formId === "company-ai-form") {
    const formData = new FormData(event.target.form);
    updateState({
      companyAi: {
        ...state.companyAi,
        requestText: cleanText(formData.get("requestText")),
      },
    });
    return;
  }

  if (formId === "carrier-ai-form") {
    const formData = new FormData(event.target.form);
    updateState({
      carrierAi: {
        ...state.carrierAi,
        requestText: cleanText(formData.get("requestText")),
      },
    });
  }
}

function submitProfile(form) {
  const formData = new FormData(form);

  if (state.activeRole === "company") {
    updateState({
      profiles: {
        ...state.profiles,
        company: {
          legalName: cleanText(formData.get("legalName")),
          businessNumber: cleanText(formData.get("businessNumber")),
          contactName: cleanText(formData.get("contactName")),
          email: cleanText(formData.get("email")),
          phone: cleanText(formData.get("phone")),
          city: cleanText(formData.get("city")),
          province: cleanText(formData.get("province")),
          industry: cleanText(formData.get("industry")),
        },
      },
    });
    return;
  }

  updateState({
    profiles: {
      ...state.profiles,
      carrier: {
        transportCompany: cleanText(formData.get("transportCompany")),
        businessNumber: cleanText(formData.get("businessNumber")),
        contactName: cleanText(formData.get("contactName")),
        email: cleanText(formData.get("email")),
        phone: cleanText(formData.get("phone")),
        fleetSize: cleanText(formData.get("fleetSize")),
        regions: cleanText(formData.get("regions")),
        equipmentTypes: formData.getAll("equipmentTypes").map(cleanText).filter(Boolean),
      },
    },
  });
}

function submitAnnouncement(form) {
  const draft = readAnnouncementDraft(form);
  const tripsTotal = Number(draft.tripsTotal);
  const budget = Number(draft.budget);
  const cargoType = resolveDraftCargoValue(draft);

  if (
    !cleanText(draft.title) ||
    !cleanText(draft.pickupCity) ||
    !cleanText(draft.deliveryCity) ||
    !cargoType ||
    !cleanText(draft.equipment) ||
    !normalizeDateInputValue(draft.loadingDate) ||
    !tripsTotal ||
    tripsTotal < 1
  ) {
    return;
  }

  const nextAnnouncement = normalizeStoredAnnouncement({
    id: `user-${Date.now()}`,
    title: cleanText(draft.title),
    pickupCity: cleanText(draft.pickupCity),
    deliveryCity: cleanText(draft.deliveryCity),
    cargoType,
    equipment: cleanText(draft.equipment),
    loadingDate: normalizeDateInputValue(draft.loadingDate),
    tripsTotal,
    remainingTrips: tripsTotal,
    budget: budget || 0,
    notes: cleanText(draft.notes),
    companyName: state.profiles.company.legalName,
  });

  updateState({
    announcements: [...state.announcements, nextAnnouncement],
    draftAnnouncement: createEmptyDraftAnnouncement(),
    companyAi: {
      ...state.companyAi,
      assistantMessage: "Annonce publiee. Le brouillon a ete reinitialise.",
      missingFields: [],
      error: "",
    },
  });
}

async function submitCompanyAi(form) {
  const formData = new FormData(form);
  const requestText = cleanText(formData.get("requestText"));

  if (!requestText) {
    return;
  }

  updateState({
    companyAi: {
      ...state.companyAi,
      requestText,
      status: "loading",
      assistantMessage: "",
      missingFields: [],
      error: "",
    },
  });

  try {
    const response = await postJson("/api/ai/company-assistant", {
      profile: state.profiles.company,
      requestText,
      currentDraft: readAnnouncementDraft(document.querySelector("#announcement-form")) || state.draftAnnouncement,
    });

    const nextDraft = buildDraftFromAiResponse(response.announcement);

    updateState({
      draftAnnouncement: nextDraft,
      companyAi: {
        ...state.companyAi,
        requestText,
        status: "success",
        assistantMessage: cleanText(response.assistantMessage) || "Gemini a prepare un brouillon. Verifiez-le avant de publier.",
        missingFields: Array.isArray(response.missingFields) ? response.missingFields.map(cleanText).filter(Boolean) : [],
        error: "",
      },
    });
  } catch (error) {
    updateState({
      companyAi: {
        ...state.companyAi,
        requestText,
        status: "error",
        assistantMessage: "",
        missingFields: [],
        error: error.message || "Impossible de contacter Gemini pour le moment.",
      },
    });
  }
}

async function submitCarrierAi(form) {
  const formData = new FormData(form);
  const requestText = cleanText(formData.get("requestText"));

  if (!requestText) {
    return;
  }

  updateState({
    carrierAi: {
      ...state.carrierAi,
      requestText,
      status: "loading",
      assistantMessage: "",
      error: "",
    },
  });

  try {
    const response = await postJson("/api/ai/carrier-assistant", {
      profile: state.profiles.carrier,
      requestText,
      currentFilters: state.filters,
      announcements: getActiveAnnouncements().map((announcement) => ({
        id: announcement.id,
        title: announcement.title,
        companyName: announcement.companyName,
        pickupCity: announcement.pickupCity,
        deliveryCity: announcement.deliveryCity,
        cargoType: announcement.cargoType,
        equipment: announcement.equipment,
        loadingDate: announcement.loadingDate,
        remainingTrips: announcement.remainingTrips,
        budget: announcement.budget,
        notes: announcement.notes,
      })),
    });

    const validIds = new Set(getActiveAnnouncements().map((announcement) => announcement.id));
    const matches = Array.isArray(response.matches)
      ? response.matches
          .map((match) => ({
            announcementId: cleanText(match.announcementId),
            score: clampScore(match.score),
            reasoning: cleanText(match.reasoning),
          }))
          .filter((match) => validIds.has(match.announcementId))
      : [];

    updateState({
      carrierAi: {
        ...state.carrierAi,
        requestText,
        status: "success",
        assistantMessage: cleanText(response.assistantMessage) || "Gemini a classe les meilleurs voyages pour votre flotte.",
        matches,
        suggestedFilters: normalizeSuggestedFilters(response.suggestedFilters),
        error: "",
      },
    });
  } catch (error) {
    updateState({
      carrierAi: {
        ...state.carrierAi,
        requestText,
        status: "error",
        assistantMessage: "",
        matches: [],
        error: error.message || "Impossible de contacter Gemini pour le moment.",
      },
    });
  }
}

function readAnnouncementDraft(form) {
  if (!form) {
    return { ...state.draftAnnouncement };
  }

  const formData = new FormData(form);

  return {
    title: cleanText(formData.get("title")),
    pickupCity: cleanText(formData.get("pickupCity")),
    deliveryCity: cleanText(formData.get("deliveryCity")),
    cargoType: cleanText(formData.get("cargoType")),
    cargoTypeOther: cleanText(formData.get("cargoTypeOther")),
    equipment: cleanText(formData.get("equipment")),
    loadingDate: cleanText(formData.get("loadingDate")),
    tripsTotal: cleanText(formData.get("tripsTotal")),
    budget: cleanText(formData.get("budget")),
    notes: cleanText(formData.get("notes")),
  };
}

function buildDraftFromAiResponse(announcement) {
  const draft = createEmptyDraftAnnouncement();
  const cargo = normalizeCargoOption(cleanText(announcement?.cargoType));

  draft.title = cleanText(announcement?.title);
  draft.pickupCity = cleanText(announcement?.pickupCity);
  draft.deliveryCity = cleanText(announcement?.deliveryCity);
  draft.cargoType = cargo.cargoType;
  draft.cargoTypeOther = cargo.cargoTypeOther;
  draft.equipment = normalizeEquipmentOption(cleanText(announcement?.equipment));
  draft.loadingDate = normalizeDateInputValue(announcement?.loadingDate);
  draft.tripsTotal = cleanText(announcement?.tripsTotal || "");
  draft.budget = cleanText(announcement?.budget || "");
  draft.notes = cleanText(announcement?.notes);

  return draft;
}

function normalizeStoredAnnouncement(announcement) {
  return {
    ...announcement,
    title: cleanText(announcement.title),
    pickupCity: cleanText(announcement.pickupCity),
    deliveryCity: cleanText(announcement.deliveryCity),
    cargoType: cleanText(announcement.cargoType),
    equipment: cleanText(announcement.equipment),
    loadingDate: normalizeDateInputValue(announcement.loadingDate),
    tripsTotal: Number(announcement.tripsTotal) || 0,
    remainingTrips: Math.max(Number(announcement.remainingTrips) || 0, 0),
    budget: Number(announcement.budget) || 0,
    notes: cleanText(announcement.notes),
    companyName: cleanText(announcement.companyName),
  };
}

function assignTrips(id, amount) {
  const announcements = state.announcements.map((announcement) => {
    if (announcement.id !== id) {
      return announcement;
    }

    const nextRemaining = Math.max(announcement.remainingTrips - amount, 0);
    return {
      ...announcement,
      remainingTrips: nextRemaining,
    };
  });

  updateState({ announcements });
}

function syncConditionalFields() {
  const cargoSelect = document.querySelector("#cargoType");
  const cargoOtherField = document.querySelector("#cargoTypeOtherField");
  const cargoOtherInput = document.querySelector("#cargoTypeOther");

  if (!cargoSelect || !cargoOtherField || !cargoOtherInput) {
    return;
  }

  const isOtherSelected = cargoSelect.value === OTHER_CARGO_VALUE;
  cargoOtherField.classList.toggle("hidden", !isOtherSelected);
  cargoOtherInput.required = isOtherSelected;
}

async function ensureServerHealth(force = false) {
  if (healthCheckPromise && !force) {
    return healthCheckPromise;
  }

  if (state.server.checked && !force) {
    return Promise.resolve(state.server);
  }

  healthCheckPromise = fetchJson("/api/health")
    .then((payload) => {
      updateState({
        server: {
          checked: true,
          available: true,
          geminiConfigured: Boolean(payload.geminiConfigured),
          model: cleanText(payload.model),
        },
      });
    })
    .catch(() => {
      updateState({
        server: {
          checked: true,
          available: false,
          geminiConfigured: false,
          model: "",
        },
      });
    })
    .finally(() => {
      healthCheckPromise = null;
    });

  return healthCheckPromise;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const body = await parseJsonResponse(response);
  if (!response.ok) {
    throw new Error(body.error || "La requete a echoue.");
  }

  return body;
}

async function fetchJson(url) {
  const response = await fetch(url);
  const body = await parseJsonResponse(response);
  if (!response.ok) {
    throw new Error(body.error || "La requete a echoue.");
  }

  return body;
}

async function parseJsonResponse(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch (error) {
    return {
      error: text,
    };
  }
}

function hasSuggestedFilters(filters) {
  if (!filters) {
    return false;
  }

  return ["pickupCity", "deliveryCity", "cargoType", "equipment"].some((key) => cleanText(filters[key]));
}

function renderSuggestedFilterTags(filters) {
  return ["pickupCity", "deliveryCity", "cargoType", "equipment"]
    .filter((key) => cleanText(filters[key]))
    .map((key) => `<span class="metric-badge">${escapeHtml(renderFilterLabel(key, filters[key]))}</span>`)
    .join("");
}

function renderFilterLabel(key, value) {
  const labels = {
    pickupCity: "Chargement",
    deliveryCity: "Livraison",
    cargoType: "Marchandise",
    equipment: "Equipement",
  };

  return `${labels[key]}: ${value}`;
}

function normalizeSuggestedFilters(filters) {
  const next = {
    pickupCity: cleanText(filters?.pickupCity),
    deliveryCity: cleanText(filters?.deliveryCity),
    cargoType: cleanText(filters?.cargoType),
    equipment: normalizeEquipmentOption(filters?.equipment),
  };

  return next;
}

function findAnnouncementTitle(announcementId) {
  const announcement = state.announcements.find((item) => item.id === announcementId);
  return announcement ? announcement.title : "Annonce";
}

function clampScore(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return 0;
  }

  return Math.max(0, Math.min(100, Math.round(number)));
}

function cleanText(value) {
  return String(value || "").trim();
}

function formatCurrency(value) {
  return new Intl.NumberFormat("fr-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(Number(value) || 0);
}

function formatDate(value) {
  if (!value) {
    return "Date a confirmer";
  }

  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("fr-CA", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
