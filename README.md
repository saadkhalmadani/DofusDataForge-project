-- Insert test users with plaintext passwords
INSERT INTO users (username, password) VALUES
('user_1', 'pass123'),
('user_2', 'secret456')
ON CONFLICT (username) DO NOTHING;
