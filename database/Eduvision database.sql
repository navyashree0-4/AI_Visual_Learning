-- EduVision full database (MySQL)
-- Save in:  database/eduvision_database.sql
-- Run with: mysql -u root -p < database/eduvision_database.sql
-- (Optional: app.py -> initialize_database() creates the same tables automatically
--  when you start the app. Existing data is never deleted by this file.)
-- Note: the Aptitude Arena table (aptitude_attempts) is created by routes/aptitude_backend.py.

CREATE DATABASE IF NOT EXISTS `ai_visual_learning`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE `ai_visual_learning`;

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    credits INT NOT NULL DEFAULT 50,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS learning_progress (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL UNIQUE,
    videos_generated INT NOT NULL DEFAULT 0,
    quizzes_completed INT NOT NULL DEFAULT 0,
    games_played INT NOT NULL DEFAULT 0,
    total_score INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_learning_progress_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS generated_videos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(150) NOT NULL DEFAULT 'Educational Lesson',
    description TEXT,
    video_style VARCHAR(80) DEFAULT 'Educational',
    language VARCHAR(40) DEFAULT 'English',
    filename VARCHAR(255),
    video_url VARCHAR(500),
    thumbnail VARCHAR(500),
    difficulty VARCHAR(30) NULL,
    audience VARCHAR(40) NULL,
    aspect_ratio VARCHAR(10) NULL DEFAULT '16:9',
    duration_seconds INT NOT NULL DEFAULT 0,
    subtitles TINYINT(1) NOT NULL DEFAULT 0,
    highlights TINYINT(1) NOT NULL DEFAULT 0,
    music TINYINT(1) NOT NULL DEFAULT 0,
    script_text LONGTEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_generated_videos_user_created (user_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_activity (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    activity_date DATE NOT NULL,
    activity_type VARCHAR(60) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_activity_day_type (user_id, activity_date, activity_type),
    INDEX idx_user_activity_user_date (user_id, activity_date)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS game_plays (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    game_key VARCHAR(100) NOT NULL,
    score_pct INT NOT NULL DEFAULT 0,
    seconds INT NOT NULL DEFAULT 0,
    credits_earned INT NOT NULL DEFAULT 0,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_game_plays_user_day (user_id, played_at),
    INDEX idx_game_plays_user_game_day (user_id, game_key, played_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS game_progress (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    game_key VARCHAR(100) NOT NULL,
    unlocked_level INT NOT NULL DEFAULT 1,
    completed_levels INT NOT NULL DEFAULT 0,
    best_score INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_game_progress (user_id, game_key)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS game_level_rewards (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    game_key VARCHAR(100) NOT NULL,
    level_number INT NOT NULL,
    score INT NOT NULL DEFAULT 0,
    credits_earned INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_user_game_level (user_id, game_key, level_number),
    INDEX idx_level_rewards_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS registration_otp_pending (
    email VARCHAR(150) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    otp_hash VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS login_otp_pending (
    email VARCHAR(150) PRIMARY KEY,
    otp_hash VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS password_reset_pending (
    email VARCHAR(150) PRIMARY KEY,
    otp_hash VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS video_quizzes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    video_id INT NOT NULL,
    user_id INT NOT NULL,
    questions LONGTEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_video_quiz (video_id),
    INDEX idx_video_quizzes_user (user_id),
    CONSTRAINT fk_video_quizzes_video FOREIGN KEY (video_id)
        REFERENCES generated_videos(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ONE ATTEMPT ONLY: UNIQUE (user_id, video_id) makes MySQL refuse a second attempt.
CREATE TABLE IF NOT EXISTS video_quiz_attempts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    video_id INT NOT NULL,
    quiz_id INT NOT NULL,
    answers TEXT NOT NULL,
    score INT NOT NULL DEFAULT 0,
    total_questions INT NOT NULL DEFAULT 0,
    percentage INT NOT NULL DEFAULT 0,
    credits_earned INT NOT NULL DEFAULT 0,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_vqa_user_quiz (user_id, quiz_id),
    UNIQUE KEY unique_user_video_attempt (user_id, video_id),
    CONSTRAINT fk_vqa_video FOREIGN KEY (video_id)
        REFERENCES generated_videos(id) ON DELETE CASCADE,
    CONSTRAINT fk_vqa_quiz FOREIGN KEY (quiz_id)
        REFERENCES video_quizzes(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS game_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    game_name VARCHAR(100) NOT NULL,
    score INT NOT NULL DEFAULT 0,
    credits_earned INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_game_results_user (user_id)
) ENGINE=InnoDB;

-- Every existing account gets a progress row
INSERT IGNORE INTO learning_progress (user_id, videos_generated, quizzes_completed, games_played, total_score)
SELECT id, 0, 0, 0, 0 FROM users;