-- Additive compatibility migration: legacy subject-only fees remain NULL-grade fallbacks.
ALTER TABLE subject_fees ADD COLUMN IF NOT EXISTS grade VARCHAR(50) NULL AFTER subject_id;
CREATE INDEX ix_subject_fee_grade ON subject_fees (institution_id, grade, subject_id);
ALTER TABLE subject_fees DROP INDEX uq_subject_fee_effective;
ALTER TABLE subject_fees ADD UNIQUE KEY uq_subject_fee_grade_effective
  (institution_id, grade, subject_id, effective_from);
