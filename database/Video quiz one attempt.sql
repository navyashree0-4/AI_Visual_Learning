-- Video quiz: ONE ATTEMPT ONLY (database side)
-- Run this ONCE in MySQL (select your database first: USE ai_visual_learning;)
-- It is OPTIONAL: routes/video_quiz.py does the same automatically the first time
-- a quiz page is opened. Use this file only if you prefer to run it by hand.

-- Step 1: remove duplicate attempts (keeps the FIRST attempt of each user + video).
-- If there are no duplicates this deletes nothing.
DELETE a
FROM video_quiz_attempts a
JOIN video_quiz_attempts b
  ON a.user_id = b.user_id
 AND a.video_id = b.video_id
 AND a.id > b.id;

-- Step 2: add the unique key (same name as app.py uses: unique_user_video_attempt).
-- If you get "Duplicate key name 'unique_user_video_attempt'", the key already
-- exists and you are done: skip this step.
ALTER TABLE video_quiz_attempts
  ADD UNIQUE KEY unique_user_video_attempt (user_id, video_id);

-- Step 3 (only if you ran the OLD version of this file that created `uq_user_video`):
-- the two keys do the same job, so drop the old one.
-- If it says "Can't DROP 'uq_user_video'; check that column/key exists", ignore it.
-- ALTER TABLE video_quiz_attempts DROP INDEX uq_user_video;

-- Check: this should list one unique key on (user_id, video_id)
SHOW INDEX FROM video_quiz_attempts WHERE Non_unique = 0;