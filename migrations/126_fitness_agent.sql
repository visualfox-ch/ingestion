-- Phase 22A-04: Fitness Agent (FitJarvis)
-- Date: 2026-03-19
-- Task: T-22A-04

-- =============================================================================
-- Workout Logging
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_workouts (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    workout_type VARCHAR(50) NOT NULL,  -- strength, cardio, hiit, yoga, stretching, sports
    activity VARCHAR(100) NOT NULL,      -- specific activity (e.g., "running", "bench press")
    duration_minutes INTEGER,
    intensity VARCHAR(20),               -- low, moderate, high, max
    calories_burned INTEGER,
    distance_km FLOAT,
    heart_rate_avg INTEGER,
    heart_rate_max INTEGER,
    sets_reps JSONB,                     -- For strength: [{"exercise": "...", "sets": 3, "reps": 10, "weight_kg": 50}]
    notes TEXT,
    mood_before VARCHAR(20),
    mood_after VARCHAR(20),
    energy_level INTEGER,                -- 1-10
    location VARCHAR(100),
    workout_date DATE DEFAULT CURRENT_DATE,
    started_at TIMESTAMP,
    ended_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workouts_user_date
ON jarvis_workouts(user_id, workout_date DESC);

CREATE INDEX IF NOT EXISTS idx_workouts_type
ON jarvis_workouts(workout_type);

-- =============================================================================
-- Nutrition Tracking
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_nutrition (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    meal_type VARCHAR(20) NOT NULL,      -- breakfast, lunch, dinner, snack
    food_items JSONB NOT NULL,           -- [{"name": "...", "calories": 200, "protein_g": 20, ...}]
    total_calories INTEGER,
    protein_g FLOAT,
    carbs_g FLOAT,
    fat_g FLOAT,
    fiber_g FLOAT,
    water_ml INTEGER,
    notes TEXT,
    meal_time TIMESTAMP DEFAULT NOW(),
    meal_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nutrition_user_date
ON jarvis_nutrition(user_id, meal_date DESC);

-- =============================================================================
-- Fitness Goals
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_fitness_goals (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    goal_type VARCHAR(50) NOT NULL,      -- weight, strength, endurance, habit, body_comp
    target_metric VARCHAR(50),           -- e.g., "weight_kg", "bench_press_kg", "run_5k_minutes"
    target_value FLOAT,
    current_value FLOAT,
    unit VARCHAR(20),
    target_date DATE,
    status VARCHAR(20) DEFAULT 'active', -- active, achieved, paused, abandoned
    progress_pct FLOAT DEFAULT 0,
    milestones JSONB DEFAULT '[]',
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fitness_goals_user_status
ON jarvis_fitness_goals(user_id, status);

-- =============================================================================
-- Body Metrics (weight, measurements, etc.)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_body_metrics (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(50) DEFAULT '1',
    weight_kg FLOAT,
    body_fat_pct FLOAT,
    muscle_mass_kg FLOAT,
    water_pct FLOAT,
    bmi FLOAT,
    measurements JSONB,                  -- {"chest_cm": 100, "waist_cm": 80, ...}
    measured_at DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_body_metrics_user_date
ON jarvis_body_metrics(user_id, measured_at DESC);

-- =============================================================================
-- Exercise Library (for suggestions)
-- =============================================================================

CREATE TABLE IF NOT EXISTS jarvis_exercise_library (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,       -- strength, cardio, flexibility, balance
    muscle_groups JSONB DEFAULT '[]',    -- ["chest", "triceps", "shoulders"]
    equipment JSONB DEFAULT '[]',        -- ["barbell", "bench"]
    difficulty VARCHAR(20),              -- beginner, intermediate, advanced
    calories_per_minute FLOAT,
    instructions TEXT,
    tips TEXT,
    alternatives JSONB DEFAULT '[]',     -- alternative exercises
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_exercise_library_category
ON jarvis_exercise_library(category);

-- =============================================================================
-- Seed Exercise Library
-- =============================================================================

INSERT INTO jarvis_exercise_library (name, category, muscle_groups, equipment, difficulty, calories_per_minute, instructions)
VALUES
    ('Running', 'cardio', '["legs", "core"]', '[]', 'beginner', 10, 'Maintain steady pace, focus on breathing'),
    ('Bench Press', 'strength', '["chest", "triceps", "shoulders"]', '["barbell", "bench"]', 'intermediate', 5, 'Lower bar to chest, press up'),
    ('Squats', 'strength', '["quadriceps", "glutes", "hamstrings"]', '["barbell"]', 'intermediate', 6, 'Keep back straight, go parallel'),
    ('Deadlift', 'strength', '["back", "glutes", "hamstrings"]', '["barbell"]', 'advanced', 7, 'Keep back straight, drive through heels'),
    ('Pull-ups', 'strength', '["back", "biceps"]', '["pull-up bar"]', 'intermediate', 5, 'Full extension, chin over bar'),
    ('Plank', 'strength', '["core", "shoulders"]', '[]', 'beginner', 3, 'Keep body straight, engage core'),
    ('Yoga Flow', 'flexibility', '["full body"]', '["yoga mat"]', 'beginner', 4, 'Flow through poses, focus on breath'),
    ('HIIT Circuit', 'cardio', '["full body"]', '[]', 'advanced', 12, 'High intensity intervals with rest'),
    ('Swimming', 'cardio', '["full body"]', '[]', 'intermediate', 8, 'Mix strokes for full body workout'),
    ('Cycling', 'cardio', '["legs", "core"]', '["bike"]', 'beginner', 7, 'Maintain cadence, vary resistance')
ON CONFLICT DO NOTHING;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE jarvis_workouts IS 'Phase 22A-04: FitJarvis workout logging';
COMMENT ON TABLE jarvis_nutrition IS 'Phase 22A-04: FitJarvis nutrition tracking';
COMMENT ON TABLE jarvis_fitness_goals IS 'Phase 22A-04: FitJarvis fitness goals';
COMMENT ON TABLE jarvis_body_metrics IS 'Phase 22A-04: FitJarvis body measurements';
COMMENT ON TABLE jarvis_exercise_library IS 'Phase 22A-04: FitJarvis exercise suggestions';
