-- Schema minimal 2SIN : users + droits (capacité 5 : permission control)
-- Modèle doc 60 : le user est logique (BD), les droits sont logiques (BD).

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    login         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    profil        TEXT NOT NULL DEFAULT 'residentiel',  -- module le métier (profils.json)
    niveau_acces  INTEGER NOT NULL DEFAULT 1,            -- matrice de droits (doc 42)
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index sur login (lookup à chaque auth)
CREATE INDEX IF NOT EXISTS idx_users_login ON users(login);

-- Seed de démonstration : 2 cabinets, 2 profils distincts
-- Montre le CLOISONNEMENT : cabinet_a (residentiel) ne voit pas la mémoire de cabinet_b (commercial)
-- Mots de passe : hashés côté Node au premier boot si absents (voir seed.js).
-- Ici on laisse les hash vides, le seed Node les remplira (bcrypt).
INSERT INTO users (login, password_hash, profil, niveau_acces) VALUES
    ('cabinet_a', '', 'residentiel', 1),
    ('cabinet_b', '', 'commercial',  1),
    ('admin_2sin', '', 'residentiel', 9)
ON CONFLICT (login) DO NOTHING;
