-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);

-- Archimonsters table
CREATE TABLE IF NOT EXISTS archimonsters (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    level TEXT,
    url_image TEXT,
    local_image TEXT
);

-- User monsters ownership table
CREATE TABLE IF NOT EXISTS user_monsters (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    monster_name TEXT NOT NULL REFERENCES archimonsters(name) ON DELETE CASCADE,
    quantity INTEGER DEFAULT 0 CHECK (quantity >= 0),
    UNIQUE(user_id, monster_name)
);
