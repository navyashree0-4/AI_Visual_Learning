-- Run once in MySQL (database: ai_visual_learning).
-- Safe to re-run: every statement checks before creating.

-- Dates the user was active (feeds the learning streak).
CREATE TABLE IF NOT EXISTS user_activity (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    user_id       INT NOT NULL,
    activity_date DATE NOT NULL,
    activity_type VARCHAR(30) NOT NULL,
    UNIQUE KEY one_per_day_type (user_id, activity_date, activity_type)
);

-- Only needed if you do NOT already have this table.
CREATE TABLE IF NOT EXISTS generated_videos (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    title       VARCHAR(150),
    description VARCHAR(255),
    video_style VARCHAR(40),
    language    VARCHAR(30),
    filename    VARCHAR(255),
    video_url   VARCHAR(500),
    thumbnail   VARCHAR(500),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (user_id)
);

-- If generated_videos ALREADY exists with other columns, add the missing ones.
-- Run only the lines for columns you do not have (MySQL will say "Duplicate column" if you do):
-- ALTER TABLE generated_videos ADD COLUMN title VARCHAR(150);
-- ALTER TABLE generated_videos ADD COLUMN description VARCHAR(255);
-- ALTER TABLE generated_videos ADD COLUMN video_style VARCHAR(40);
-- ALTER TABLE generated_videos ADD COLUMN language VARCHAR(30);
-- ALTER TABLE generated_videos ADD COLUMN filename VARCHAR(255);

-- Every finished game (used for daily limits and the profile page).
CREATE TABLE IF NOT EXISTS game_plays (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id        INT NOT NULL,
    game_key       VARCHAR(40) NOT NULL,
    score_pct      INT NOT NULL,
    seconds        INT NOT NULL,
    credits_earned INT NOT NULL DEFAULT 0,
    played_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX (user_id, played_at)
);