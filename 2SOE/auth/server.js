// 2SIN - Backend de session par clé (doc 60).
// Le user est logique (PostgreSQL), la clé de session est un JWT.
// Node = gestionnaire de session : résout JWT -> user -> profil -> droits,
// forward au relay (l'agent) avec l'identité validée. L'agent ne voit jamais
// les credentials : il reçoit un user déjà authentifié (X-User / X-Profil).
const express = require("express");
const { Pool } = require("pg");
const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");
const http = require("http");

const PORT        = parseInt(process.env.AUTH_PORT || "8080", 10);
const JWT_SECRET  = process.env.JWT_SECRET || "";
const JWT_TTL     = process.env.JWT_TTL || "8h";
const RELAY_HOST  = process.env.RELAY_HOST || "relay";
const RELAY_PORT  = parseInt(process.env.RELAY_PORT || "8787", 10);
const WEB_FILE    = process.env.WEB_FILE || "/app/web/2sin-chat.html";

if (!JWT_SECRET) { console.error("FATAL: JWT_SECRET manquant"); process.exit(1); }

const pool = new Pool({
  host: process.env.PG_HOST || "postgres",
  port: parseInt(process.env.PG_PORT || "5432", 10),
  user: process.env.PG_USER || "2sin",
  password: process.env.PG_PASSWORD || "",
  database: process.env.PG_DATABASE || "2sin",
});

// --- SEED : pose les hash bcrypt des users démo si vides (jamais en dur en SQL) ---
async function seed() {
  // Mots de passe de démonstration (documentés dans le README).
  const demo = {
    cabinet_a: process.env.SEED_PWD_A || "demo_a",
    cabinet_b: process.env.SEED_PWD_B || "demo_b",
    admin_2sin: process.env.SEED_PWD_ADMIN || "admin_demo",
  };
  for (const [login, pwd] of Object.entries(demo)) {
    try {
      const r = await pool.query("SELECT password_hash FROM users WHERE login=$1", [login]);
      if (r.rows.length && !r.rows[0].password_hash) {
        const hash = await bcrypt.hash(pwd, 10);
        await pool.query("UPDATE users SET password_hash=$1 WHERE login=$2", [hash, login]);
        console.log("seed: hash posé pour", login);
      }
    } catch (e) { console.error("seed err", login, e.message); }
  }
}

const app = express();
app.use(express.json({ limit: "1mb" }));

// CORS : le navigateur fait un preflight OPTIONS que curl ne fait pas.
app.use(function (req, res, next) {
  res.header("Access-Control-Allow-Origin", req.headers.origin || "*");
  res.header("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.header("Access-Control-Allow-Headers", "Content-Type, Authorization");
  if (req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

// Sert le web UI
app.get("/", (_req, res) => res.sendFile(WEB_FILE));

// --- LOGIN : {login, mdp} -> vérifie PG -> émet JWT ---
app.post("/login", async (req, res) => {
  const { login, mdp } = req.body || {};
  if (!login || !mdp) return res.status(400).json({ error: "login et mdp requis" });
  try {
    const r = await pool.query(
      "SELECT login, password_hash, profil, niveau_acces FROM users WHERE login=$1", [login]);
    if (!r.rows.length || !r.rows[0].password_hash)
      return res.status(401).json({ error: "identifiants invalides" });
    const u = r.rows[0];
    const ok = await bcrypt.compare(mdp, u.password_hash);
    if (!ok) return res.status(401).json({ error: "identifiants invalides" });
    const token = jwt.sign(
      { user: u.login, profil: u.profil, niveau: u.niveau_acces },
      JWT_SECRET, { expiresIn: JWT_TTL });
    res.json({ token, profil: u.profil });
  } catch (e) {
    console.error("login err", e.message);
    res.status(500).json({ error: "erreur serveur" });
  }
});

// --- LIVRABLES : les fichiers produits par l'agent sont servis par le relay.
// Sans ce relais, le lien affiché dans le chat (port 8090) ne trouve rien.
app.get("/files/*", (req, res) => {
  const preq = http.request(
    { host: RELAY_HOST, port: RELAY_PORT, path: req.originalUrl, method: "GET" },
    (pres) => {
      res.status(pres.statusCode || 200);
      Object.entries(pres.headers).forEach(([k, v]) => res.setHeader(k, v));
      pres.pipe(res);
    });
  preq.on("error", () => res.status(502).send("livrable indisponible"));
  preq.end();
});

// --- PROXY : vérifie JWT -> forward au relay avec X-User / X-Profil ---
app.post("/v1/chat/completions", (req, res) => {
  const auth = req.headers.authorization || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  let claims;
  try { claims = jwt.verify(token, JWT_SECRET); }
  catch { return res.status(401).json({ error: "session invalide ou expirée" }); }

  const body = JSON.stringify(req.body || {});
  const opts = {
    host: RELAY_HOST, port: RELAY_PORT, path: "/v1/chat/completions", method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Content-Length": Buffer.byteLength(body),
      "X-User": claims.user,          // identité validée (session_id côté relay)
      "X-Profil": claims.profil,      // profil métier -> collections + cloisonnement
      "X-Niveau": String(claims.niveau || 1),
      // Le relay construit les liens de fichiers sur cet hote : sans lui il
      // verrait "relay:8787" (nom interne Docker) et le lien serait mort
      // depuis le navigateur.
      "X-Forwarded-Host": req.headers.host || "",
    },
  };
  const preq = http.request(opts, (pres) => {
    res.status(pres.statusCode || 200);
    pres.pipe(res);
  });
  preq.on("error", (e) => {
    console.error("proxy err", e.message);
    res.status(502).json({ error: "relay injoignable" });
  });
  preq.write(body); preq.end();
});

app.listen(PORT, "0.0.0.0", async () => {
  console.log("2sin-auth sur :" + PORT + " -> relay " + RELAY_HOST + ":" + RELAY_PORT);
  // Attendre PG puis seed (retry léger)
  for (let i = 0; i < 10; i++) {
    try { await pool.query("SELECT 1"); await seed(); break; }
    catch { await new Promise(r => setTimeout(r, 2000)); }
  }
});
