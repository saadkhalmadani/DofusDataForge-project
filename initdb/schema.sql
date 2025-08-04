CREATE TABLE IF NOT EXISTS archimonsters (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT,
    url_image TEXT,
    local_image TEXT,
    UNIQUE(name, url_image)
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS user_monsters (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    monster_name TEXT NOT NULL,
    quantity INTEGER DEFAULT 0,
    UNIQUE(user_id, monster_name)
);

-- Fix SERIAL sequence for user_monsters to prevent duplicate key errors
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'user_monsters_id_seq') THEN
    PERFORM setval('user_monsters_id_seq', COALESCE((SELECT MAX(id) FROM user_monsters), 0) + 1, false);
  END IF;
END
$$;
