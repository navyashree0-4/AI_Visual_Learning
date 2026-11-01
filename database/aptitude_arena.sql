
USE ai_visual_learning;

-- =====================================================
-- 1. APTITUDE QUESTIONS
-- =====================================================

CREATE TABLE IF NOT EXISTS aptitude_questions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category VARCHAR(30) NOT NULL,
    question_text TEXT NOT NULL,
    options_json TEXT NOT NULL,
    correct_option TINYINT NOT NULL,
    explanation TEXT,
    active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_aptitude_category (category)
) ENGINE=InnoDB;


-- =====================================================
-- 2. APTITUDE TEST ATTEMPTS
-- =====================================================

CREATE TABLE IF NOT EXISTS aptitude_attempts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NULL,
    guest_token VARCHAR(100) NULL,
    category VARCHAR(30) NOT NULL,
    question_count INT NOT NULL,
    started_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    submitted_at DATETIME NULL,
    score INT NOT NULL DEFAULT 0,
    percentage DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    time_taken_seconds INT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_attempt_user (user_id),
    INDEX idx_attempt_guest (guest_token),
    INDEX idx_attempt_status (status),

    CONSTRAINT fk_aptitude_attempt_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE SET NULL
) ENGINE=InnoDB;


-- =====================================================
-- 3. APTITUDE ANSWERS
-- =====================================================

CREATE TABLE IF NOT EXISTS aptitude_attempt_answers (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    attempt_id BIGINT NOT NULL,
    question_id INT NOT NULL,
    selected_option TINYINT NULL,
    is_correct TINYINT(1) NOT NULL DEFAULT 0,

    INDEX idx_answer_attempt (attempt_id),
    INDEX idx_answer_question (question_id),

    CONSTRAINT fk_aptitude_answer_attempt
        FOREIGN KEY (attempt_id)
        REFERENCES aptitude_attempts(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_aptitude_answer_question
        FOREIGN KEY (question_id)
        REFERENCES aptitude_questions(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;


-- =====================================================
-- 4. QUANTITATIVE APTITUDE QUESTIONS
--
-- correct_option:
-- 0 = A
-- 1 = B
-- 2 = C
-- 3 = D
-- =====================================================

INSERT INTO aptitude_questions
(category, question_text, options_json, correct_option, explanation)
SELECT
    'quantitative',
    q.question_text,
    q.options_json,
    q.correct_option,
    q.explanation
FROM (
    SELECT
        'What is 25% of 240?' AS question_text,
        '["40","50","60","70"]' AS options_json,
        2 AS correct_option,
        '25% of 240 = 240 × 25 / 100 = 60.' AS explanation

    UNION ALL SELECT
        'A number is increased from 80 to 100. What is the percentage increase?',
        '["20%","25%","30%","35%"]',
        1,
        'Increase = 100 - 80 = 20. Percentage = 20/80 × 100 = 25%.'

    UNION ALL SELECT
        'Find the average of 10, 20, 30, 40 and 50.',
        '["25","30","35","40"]',
        1,
        'Average = (10 + 20 + 30 + 40 + 50) / 5 = 30.'

    UNION ALL SELECT
        'If 5 pens cost ₹100, what is the cost of 8 pens?',
        '["₹120","₹140","₹160","₹180"]',
        2,
        'One pen costs ₹100/5 = ₹20. Eight pens cost ₹160.'

    UNION ALL SELECT
        'Find the simple interest on ₹2000 at 5% per year for 2 years.',
        '["₹100","₹150","₹200","₹250"]',
        2,
        'Simple Interest = P × R × T / 100 = 2000 × 5 × 2 / 100 = ₹200.'

    UNION ALL SELECT
        'A car travels 240 km in 4 hours. Find its average speed.',
        '["40 km/h","50 km/h","60 km/h","80 km/h"]',
        2,
        'Speed = Distance / Time = 240 / 4 = 60 km/h.'

    UNION ALL SELECT
        'What is the LCM of 12 and 18?',
        '["24","30","36","48"]',
        2,
        'The smallest number divisible by both 12 and 18 is 36.'

    UNION ALL SELECT
        'What is the HCF of 24 and 36?',
        '["6","8","12","18"]',
        2,
        'The greatest common factor of 24 and 36 is 12.'

    UNION ALL SELECT
        'A product costs ₹500 and is sold for ₹600. Find the profit percentage.',
        '["10%","15%","20%","25%"]',
        2,
        'Profit = 100. Profit percentage = 100/500 × 100 = 20%.'

    UNION ALL SELECT
        'A shirt marked at ₹1000 is sold at a 10% discount. Find its selling price.',
        '["₹800","₹850","₹900","₹950"]',
        2,
        'Discount = ₹100. Selling price = ₹1000 - ₹100 = ₹900.'

    UNION ALL SELECT
        'Simplify the ratio 20:30.',
        '["1:2","2:3","3:4","4:5"]',
        1,
        'Divide both terms by 10. The simplified ratio is 2:3.'

    UNION ALL SELECT
        'If x + 15 = 35, find x.',
        '["10","15","20","25"]',
        2,
        'x = 35 - 15 = 20.'

    UNION ALL SELECT
        'What is the square of 15?',
        '["125","200","225","250"]',
        2,
        '15 × 15 = 225.'

    UNION ALL SELECT
        'What is the cube of 4?',
        '["16","32","48","64"]',
        3,
        '4 × 4 × 4 = 64.'

    UNION ALL SELECT
        'A person completes a job in 10 days. What part of the job is completed in one day?',
        '["1/5","1/10","1/15","1/20"]',
        1,
        'One-day work = 1/10 of the total work.'

    UNION ALL SELECT
        'A train travels at 72 km/h. Convert this speed into metres per second.',
        '["15 m/s","18 m/s","20 m/s","25 m/s"]',
        2,
        '72 × 5/18 = 20 m/s.'

    UNION ALL SELECT
        'Find the next number: 2, 4, 8, 16, __.',
        '["20","24","30","32"]',
        3,
        'Each number is multiplied by 2. The next number is 32.'

    UNION ALL SELECT
        'What is 3/4 of 200?',
        '["100","125","150","175"]',
        2,
        '200 × 3/4 = 150.'

    UNION ALL SELECT
        'A sum of ₹5000 earns 10% simple interest in one year. Find the interest.',
        '["₹250","₹400","₹500","₹600"]',
        2,
        'Interest = 5000 × 10 × 1 / 100 = ₹500.'

    UNION ALL SELECT
        'If 12 workers complete a task in 10 days, how many worker-days are required?',
        '["100","110","120","130"]',
        2,
        'Total worker-days = 12 × 10 = 120.'

    UNION ALL SELECT
        'Find the value of 15 × 12.',
        '["160","170","180","190"]',
        2,
        '15 × 12 = 180.'

    UNION ALL SELECT
        'What is the percentage equivalent of 0.75?',
        '["7.5%","25%","50%","75%"]',
        3,
        '0.75 × 100 = 75%.'

    UNION ALL SELECT
        'The perimeter of a square is 40 cm. Find its side.',
        '["5 cm","8 cm","10 cm","12 cm"]',
        2,
        'Side = Perimeter / 4 = 40 / 4 = 10 cm.'

    UNION ALL SELECT
        'Find the area of a rectangle with length 12 cm and width 5 cm.',
        '["50 cm²","55 cm²","60 cm²","65 cm²"]',
        2,
        'Area = Length × Width = 12 × 5 = 60 cm².'

    UNION ALL SELECT
        'What is the value of 2⁵?',
        '["16","24","32","64"]',
        2,
        '2 × 2 × 2 × 2 × 2 = 32.'

    UNION ALL SELECT
        'A shopkeeper buys an item for ₹800 and sells it for ₹720. Find the loss percentage.',
        '["5%","10%","15%","20%"]',
        1,
        'Loss = ₹80. Loss percentage = 80/800 × 100 = 10%.'

    UNION ALL SELECT
        'Find the next number: 5, 10, 15, 20, __.',
        '["22","24","25","30"]',
        2,
        'The sequence increases by 5. The next number is 25.'

    UNION ALL SELECT
        'If 6 books cost ₹360, what is the cost of 10 books?',
        '["₹500","₹550","₹600","₹650"]',
        2,
        'One book costs ₹60. Ten books cost ₹600.'

    UNION ALL SELECT
        'What is the value of 144 divided by 12?',
        '["10","11","12","14"]',
        2,
        '144 / 12 = 12.'

    UNION ALL SELECT
        'A person spends 60% of ₹5000. How much money is left?',
        '["₹1500","₹1800","₹2000","₹2500"]',
        2,
        'Spent = ₹3000. Remaining = ₹5000 - ₹3000 = ₹2000.'
) AS q
WHERE NOT EXISTS (
    SELECT 1
    FROM aptitude_questions existing
    WHERE existing.category = 'quantitative'
      AND existing.question_text = q.question_text
);


-- =====================================================
-- 5. CHECK INSERTED QUESTIONS
-- =====================================================

SELECT
    category,
    COUNT(*) AS total_active_questions
FROM aptitude_questions
WHERE active = 1
GROUP BY category;

