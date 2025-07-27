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

