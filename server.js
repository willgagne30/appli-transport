const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const ROOT_DIR = __dirname;

loadEnvFile(path.join(ROOT_DIR, ".env"));

const PORT = Number(process.env.PORT || 3000);
const MODEL = process.env.GEMINI_MODEL || "gemini-2.5-flash";
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || "";

const STATIC_FILES = {
  "/": "index.html",
  "/index.html": "index.html",
  "/styles.css": "styles.css",
  "/app.js": "app.js",
};

const server = http.createServer(async (request, response) => {
  try {
    const currentUrl = new URL(request.url, `http://${request.headers.host}`);

    if (request.method === "GET" && currentUrl.pathname === "/api/health") {
      return sendJson(response, 200, {
        ok: true,
        geminiConfigured: Boolean(GEMINI_API_KEY),
        model: MODEL,
      });
    }

    if (request.method === "POST" && currentUrl.pathname === "/api/ai/company-assistant") {
      return handleCompanyAssistant(request, response);
    }

    if (request.method === "POST" && currentUrl.pathname === "/api/ai/carrier-assistant") {
      return handleCarrierAssistant(request, response);
    }

    if (request.method === "GET" && STATIC_FILES[currentUrl.pathname]) {
      return serveStaticFile(response, STATIC_FILES[currentUrl.pathname]);
    }

    return sendJson(response, 404, {
      error: "Route introuvable.",
    });
  } catch (error) {
    return sendJson(response, 500, {
      error: error.message || "Erreur interne du serveur.",
    });
  }
});

server.listen(PORT, () => {
  process.stdout.write(`LoadSearch local server running on http://localhost:${PORT}\n`);
});

async function handleCompanyAssistant(request, response) {
  try {
    assertGeminiConfigured();

    const body = await readJsonBody(request);
    const payload = await callGeminiForJson({
      systemInstruction: buildCompanySystemInstruction(),
      userPrompt: buildCompanyPrompt(body),
    });

    return sendJson(response, 200, normalizeCompanyAssistantResponse(payload));
  } catch (error) {
    return sendJson(response, getStatusCode(error), {
      error: error.message || "Impossible de generer le brouillon d'annonce.",
    });
  }
}

async function handleCarrierAssistant(request, response) {
  try {
    assertGeminiConfigured();

    const body = await readJsonBody(request);
    const payload = await callGeminiForJson({
      systemInstruction: buildCarrierSystemInstruction(),
      userPrompt: buildCarrierPrompt(body),
    });

    return sendJson(response, 200, normalizeCarrierAssistantResponse(payload, body.announcements));
  } catch (error) {
    return sendJson(response, getStatusCode(error), {
      error: error.message || "Impossible d'analyser les annonces pour le transporteur.",
    });
  }
}

function assertGeminiConfigured() {
  if (!GEMINI_API_KEY) {
    const error = new Error("Gemini n'est pas configure. Ajoutez GEMINI_API_KEY dans .env.");
    error.statusCode = 503;
    throw error;
  }
}

async function callGeminiForJson({ systemInstruction, userPrompt }) {
  const apiResponse = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(MODEL)}:generateContent`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
      },
      body: JSON.stringify({
        systemInstruction: {
          parts: [{ text: systemInstruction }],
        },
        contents: [
          {
            role: "user",
            parts: [{ text: userPrompt }],
          },
        ],
        generationConfig: {
          responseMimeType: "application/json",
          temperature: 0.35,
        },
      }),
    },
  );

  const rawPayload = await apiResponse.json().catch(() => ({}));
  if (!apiResponse.ok) {
    const message =
      rawPayload.error?.message ||
      rawPayload.error ||
      "Requete Gemini echouee.";
    const error = new Error(message);
    error.statusCode = apiResponse.status;
    throw error;
  }

  const text = extractGeminiText(rawPayload);
  if (!text) {
    const error = new Error("Gemini n'a pas renvoye de contenu exploitable.");
    error.statusCode = 502;
    throw error;
  }

  const parsed = safeParseJson(text);
  if (!parsed) {
    const error = new Error("La reponse Gemini n'etait pas un JSON valide.");
    error.statusCode = 502;
    throw error;
  }

  return parsed;
}

function buildCompanySystemInstruction() {
  return [
    "Tu es un assistant logistique pour une marketplace de transport entre PME et petits transporteurs.",
    "Tu aides une entreprise a transformer une description libre en annonce structuree.",
    "Tu dois repondre avec un JSON valide uniquement, sans markdown ni texte avant ou apres.",
    "N'invente pas une ville, une date ou un budget si ce n'est pas mentionne.",
    "Si une information est inconnue, renvoie une chaine vide ou 0 selon le champ, puis mentionne-la dans missingFields.",
  ].join("\n");
}

function buildCarrierSystemInstruction() {
  return [
    "Tu es un assistant logistique pour de petits transporteurs ayant 1 a 4 camions.",
    "Tu dois analyser les annonces disponibles et proposer les meilleurs matchs.",
    "Tu dois repondre avec un JSON valide uniquement, sans markdown ni texte avant ou apres.",
    "Tu peux suggerer des filtres si cela aide a reduire la liste.",
    "Base ton score sur l'equipement, les zones, le volume de voyages et l'intention exprimee par le transporteur.",
  ].join("\n");
}

function buildCompanyPrompt(body) {
  return [
    "Contexte entreprise:",
    JSON.stringify(body.profile || {}, null, 2),
    "",
    "Brouillon actuel:",
    JSON.stringify(body.currentDraft || {}, null, 2),
    "",
    "Demande libre de l'entreprise:",
    String(body.requestText || ""),
    "",
    "Retourne exactement un objet JSON avec cette structure:",
    JSON.stringify(
      {
        announcement: {
          title: "",
          pickupCity: "",
          deliveryCity: "",
          cargoType: "",
          equipment: "",
          loadingDate: "",
          tripsTotal: 0,
          budget: 0,
          notes: "",
        },
        assistantMessage: "",
        missingFields: ["", ""],
      },
      null,
      2,
    ),
    "",
    "Conseils:",
    "- title doit etre court et utile.",
    "- loadingDate doit etre au format YYYY-MM-DD si une date claire est mentionnee, sinon chaine vide.",
    "- tripsTotal doit representer le nombre total de voyages si l'information existe, sinon 0.",
    "- budget doit etre un nombre entier en CAD si l'information existe, sinon 0.",
  ].join("\n");
}

function buildCarrierPrompt(body) {
  return [
    "Profil transporteur:",
    JSON.stringify(body.profile || {}, null, 2),
    "",
    "Filtres actuels:",
    JSON.stringify(body.currentFilters || {}, null, 2),
    "",
    "Demande libre du transporteur:",
    String(body.requestText || ""),
    "",
    "Annonces actives:",
    JSON.stringify(body.announcements || [], null, 2),
    "",
    "Retourne exactement un objet JSON avec cette structure:",
    JSON.stringify(
      {
        assistantMessage: "",
        suggestedFilters: {
          pickupCity: "",
          deliveryCity: "",
          cargoType: "",
          equipment: "",
        },
        matches: [
          {
            announcementId: "",
            score: 0,
            reasoning: "",
          },
        ],
      },
      null,
      2,
    ),
    "",
    "Regles:",
    "- matches doit contenir jusqu'a 5 annonces maximum.",
    "- score est un entier de 0 a 100.",
    "- announcementId doit correspondre exactement a un id d'annonce fourni.",
    "- reasoning doit etre bref et concret.",
  ].join("\n");
}

function normalizeCompanyAssistantResponse(payload) {
  return {
    announcement: {
      title: cleanText(payload.announcement?.title),
      pickupCity: cleanText(payload.announcement?.pickupCity),
      deliveryCity: cleanText(payload.announcement?.deliveryCity),
      cargoType: cleanText(payload.announcement?.cargoType),
      equipment: cleanText(payload.announcement?.equipment),
      loadingDate: cleanText(payload.announcement?.loadingDate),
      tripsTotal: toSafeInteger(payload.announcement?.tripsTotal),
      budget: toSafeInteger(payload.announcement?.budget),
      notes: cleanText(payload.announcement?.notes),
    },
    assistantMessage: cleanText(payload.assistantMessage) || "Gemini a prepare un brouillon d'annonce.",
    missingFields: Array.isArray(payload.missingFields)
      ? payload.missingFields.map(cleanText).filter(Boolean)
      : [],
  };
}

function normalizeCarrierAssistantResponse(payload, announcements) {
  const validIds = new Set(
    Array.isArray(announcements) ? announcements.map((announcement) => announcement.id) : [],
  );

  return {
    assistantMessage:
      cleanText(payload.assistantMessage) ||
      "Gemini a classe les annonces les plus compatibles.",
    suggestedFilters: {
      pickupCity: cleanText(payload.suggestedFilters?.pickupCity),
      deliveryCity: cleanText(payload.suggestedFilters?.deliveryCity),
      cargoType: cleanText(payload.suggestedFilters?.cargoType),
      equipment: cleanText(payload.suggestedFilters?.equipment),
    },
    matches: Array.isArray(payload.matches)
      ? payload.matches
          .map((match) => ({
            announcementId: cleanText(match.announcementId),
            score: clampScore(match.score),
            reasoning: cleanText(match.reasoning),
          }))
          .filter((match) => validIds.has(match.announcementId))
      : [],
  };
}

async function readJsonBody(request) {
  const chunks = [];

  for await (const chunk of request) {
    chunks.push(chunk);
  }

  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) {
    return {};
  }

  try {
    return JSON.parse(raw);
  } catch (error) {
    const parseError = new Error("Le corps de requete JSON est invalide.");
    parseError.statusCode = 400;
    throw parseError;
  }
}

function serveStaticFile(response, relativeFilePath) {
  const absoluteFilePath = path.join(ROOT_DIR, relativeFilePath);

  if (!fs.existsSync(absoluteFilePath)) {
    return sendJson(response, 404, {
      error: "Fichier introuvable.",
    });
  }

  const contentType = getContentType(absoluteFilePath);
  const fileBuffer = fs.readFileSync(absoluteFilePath);

  response.writeHead(200, {
    "Content-Type": contentType,
  });
  response.end(fileBuffer);
}

function sendJson(response, statusCode, payload) {
  response.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  response.end(JSON.stringify(payload));
}

function getContentType(filePath) {
  if (filePath.endsWith(".html")) {
    return "text/html; charset=utf-8";
  }

  if (filePath.endsWith(".css")) {
    return "text/css; charset=utf-8";
  }

  if (filePath.endsWith(".js")) {
    return "application/javascript; charset=utf-8";
  }

  return "text/plain; charset=utf-8";
}

function extractGeminiText(payload) {
  return (
    payload.candidates?.[0]?.content?.parts?.find((part) => typeof part.text === "string")?.text ||
    ""
  );
}

function safeParseJson(text) {
  try {
    return JSON.parse(text);
  } catch (error) {
    const fenced = text.match(/```json\s*([\s\S]*?)```/i)?.[1] || text.match(/```([\s\S]*?)```/i)?.[1];
    if (fenced) {
      try {
        return JSON.parse(fenced);
      } catch (innerError) {
        return tryBraces(fenced);
      }
    }

    return tryBraces(text);
  }
}

function tryBraces(text) {
  const firstBrace = text.indexOf("{");
  const lastBrace = text.lastIndexOf("}");
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    try {
      return JSON.parse(text.slice(firstBrace, lastBrace + 1));
    } catch (error) {
      return null;
    }
  }

  return null;
}

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) {
    return;
  }

  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      return;
    }

    const separatorIndex = trimmed.indexOf("=");
    if (separatorIndex === -1) {
      return;
    }

    const key = trimmed.slice(0, separatorIndex).trim();
    let value = trimmed.slice(separatorIndex + 1).trim();

    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }

    if (key && !process.env[key]) {
      process.env[key] = value;
    }
  });
}

function getStatusCode(error) {
  const status = Number(error.statusCode || error.status || 500);
  return Number.isFinite(status) && status >= 400 ? status : 500;
}

function toSafeInteger(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return 0;
  }

  return Math.max(0, Math.round(parsed));
}

function clampScore(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return 0;
  }

  return Math.max(0, Math.min(100, Math.round(parsed)));
}

function cleanText(value) {
  return String(value || "").trim();
}
