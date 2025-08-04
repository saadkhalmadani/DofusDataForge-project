-- Table for storing Archimonsters data
CREATE TABLE IF NOT EXISTS archimonsters (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    level TEXT,
    url_image TEXT,
    local_image TEXT,
    UNIQUE(name, url_image)
);

-- Table for storing user information
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL -- Store hashed passwords in production
);

-- Table for storing which monsters users own and their quantities
CREATE TABLE IF NOT EXISTS user_monsters (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    monster_name TEXT NOT NULL,
    quantity INTEGER DEFAULT 0,
    UNIQUE(user_id, monster_name)
);
