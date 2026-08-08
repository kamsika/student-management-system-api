-- Additive MySQL migration for subject-wise tuition billing.
-- Existing student_payments remains unchanged and readable as the legacy fee source.

ALTER TABLE subjects ADD COLUMN IF NOT EXISTS description TEXT NULL;
ALTER TABLE subjects ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS subject_fees (
  id INT AUTO_INCREMENT PRIMARY KEY, institution_id INT NOT NULL, subject_id INT NOT NULL,
  monthly_fee DECIMAL(12,2) NOT NULL, currency VARCHAR(3) NOT NULL DEFAULT 'LKR',
  effective_from DATE NOT NULL, effective_to DATE NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  description TEXT NULL, created_by INT NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  CONSTRAINT fk_subject_fee_institution FOREIGN KEY (institution_id) REFERENCES institutions(id),
  CONSTRAINT fk_subject_fee_subject FOREIGN KEY (subject_id) REFERENCES subjects(id),
  CONSTRAINT fk_subject_fee_creator FOREIGN KEY (created_by) REFERENCES users(id),
  UNIQUE KEY uq_subject_fee_effective (institution_id, subject_id, effective_from),
  KEY ix_subject_fee_lookup (institution_id, subject_id, effective_from, effective_to)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS student_subject_enrollments (
  id INT AUTO_INCREMENT PRIMARY KEY, institution_id INT NOT NULL, student_id INT NOT NULL,
  subject_id INT NOT NULL, start_date DATE NOT NULL, end_date DATE NULL,
  fee_snapshot DECIMAL(12,2) NULL, discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  discount_note VARCHAR(255) NULL, is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  FOREIGN KEY (institution_id) REFERENCES institutions(id), FOREIGN KEY (student_id) REFERENCES students(id),
  FOREIGN KEY (subject_id) REFERENCES subjects(id),
  UNIQUE KEY uq_student_subject_start (student_id, subject_id, start_date),
  KEY ix_student_enrollment_active (institution_id, student_id, is_active)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS monthly_invoices (
  id INT AUTO_INCREMENT PRIMARY KEY, institution_id INT NOT NULL, student_id INT NOT NULL,
  billing_period VARCHAR(7) NOT NULL, currency VARCHAR(3) NOT NULL DEFAULT 'LKR',
  subject_charges DECIMAL(12,2) NOT NULL DEFAULT 0, previous_balance DECIMAL(12,2) NOT NULL DEFAULT 0,
  discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0, waived_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  net_total DECIMAL(12,2) NOT NULL DEFAULT 0, paid_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  applied_credit DECIMAL(12,2) NOT NULL DEFAULT 0, balance_due DECIMAL(12,2) NOT NULL DEFAULT 0,
  status VARCHAR(24) NOT NULL DEFAULT 'UNPAID', notes TEXT NULL, created_by INT NOT NULL,
  created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
  FOREIGN KEY (institution_id) REFERENCES institutions(id), FOREIGN KEY (student_id) REFERENCES students(id),
  FOREIGN KEY (created_by) REFERENCES users(id),
  UNIQUE KEY uq_monthly_invoice (institution_id, student_id, billing_period),
  KEY ix_invoice_tenant_period_status (institution_id, billing_period, status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS invoice_line_items (
  id INT AUTO_INCREMENT PRIMARY KEY, invoice_id INT NOT NULL, institution_id INT NOT NULL,
  enrollment_id INT NULL, subject_id INT NOT NULL, subject_name VARCHAR(120) NOT NULL,
  fee_amount DECIMAL(12,2) NOT NULL, discount_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
  waived_amount DECIMAL(12,2) NOT NULL DEFAULT 0, net_amount DECIMAL(12,2) NOT NULL,
  paid_amount DECIMAL(12,2) NOT NULL DEFAULT 0, status VARCHAR(24) NOT NULL DEFAULT 'UNPAID',
  FOREIGN KEY (invoice_id) REFERENCES monthly_invoices(id), FOREIGN KEY (institution_id) REFERENCES institutions(id),
  FOREIGN KEY (enrollment_id) REFERENCES student_subject_enrollments(id), FOREIGN KEY (subject_id) REFERENCES subjects(id),
  UNIQUE KEY uq_invoice_subject_line (invoice_id, subject_id),
  KEY ix_invoice_line_subject (institution_id, subject_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS tuition_payments (
  id INT AUTO_INCREMENT PRIMARY KEY, institution_id INT NOT NULL, student_id INT NOT NULL,
  invoice_id INT NULL, billing_period VARCHAR(7) NULL, subject_id INT NULL, amount DECIMAL(12,2) NOT NULL,
  payment_method VARCHAR(24) NOT NULL, reference_number VARCHAR(120) NULL, receipt_number VARCHAR(80) NULL,
  payment_date DATE NOT NULL, notes TEXT NULL, recorded_by INT NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'COMPLETED',
  idempotency_key VARCHAR(100) NOT NULL, parent_payment_id INT NULL, created_at DATETIME NOT NULL,
  FOREIGN KEY (institution_id) REFERENCES institutions(id), FOREIGN KEY (student_id) REFERENCES students(id),
  FOREIGN KEY (invoice_id) REFERENCES monthly_invoices(id), FOREIGN KEY (subject_id) REFERENCES subjects(id),
  FOREIGN KEY (recorded_by) REFERENCES users(id), FOREIGN KEY (parent_payment_id) REFERENCES tuition_payments(id),
  UNIQUE KEY uq_payment_idempotency (institution_id, idempotency_key), UNIQUE KEY uq_tuition_receipt (receipt_number),
  KEY ix_tuition_payment_tenant_date (institution_id, payment_date, status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS payment_allocations (
  id INT AUTO_INCREMENT PRIMARY KEY, institution_id INT NOT NULL, payment_id INT NOT NULL,
  invoice_id INT NOT NULL, invoice_line_id INT NULL, amount DECIMAL(12,2) NOT NULL, created_at DATETIME NOT NULL,
  FOREIGN KEY (institution_id) REFERENCES institutions(id), FOREIGN KEY (payment_id) REFERENCES tuition_payments(id),
  FOREIGN KEY (invoice_id) REFERENCES monthly_invoices(id), FOREIGN KEY (invoice_line_id) REFERENCES invoice_line_items(id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS advance_credit_ledger (
  id INT AUTO_INCREMENT PRIMARY KEY, institution_id INT NOT NULL, student_id INT NOT NULL,
  payment_id INT NULL, invoice_id INT NULL, entry_type VARCHAR(20) NOT NULL, amount DECIMAL(12,2) NOT NULL,
  notes VARCHAR(255) NULL, created_by INT NOT NULL, created_at DATETIME NOT NULL,
  FOREIGN KEY (institution_id) REFERENCES institutions(id), FOREIGN KEY (student_id) REFERENCES students(id),
  FOREIGN KEY (payment_id) REFERENCES tuition_payments(id), FOREIGN KEY (invoice_id) REFERENCES monthly_invoices(id),
  FOREIGN KEY (created_by) REFERENCES users(id), KEY ix_credit_student_created (institution_id, student_id, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS financial_audit_logs (
  id INT AUTO_INCREMENT PRIMARY KEY, institution_id INT NOT NULL, actor_id INT NOT NULL,
  action VARCHAR(60) NOT NULL, entity_type VARCHAR(40) NOT NULL, entity_id INT NULL,
  details JSON NULL, created_at DATETIME NOT NULL,
  FOREIGN KEY (institution_id) REFERENCES institutions(id), FOREIGN KEY (actor_id) REFERENCES users(id),
  KEY ix_financial_audit_tenant_action (institution_id, action, created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS fee_receipts (
  id INT AUTO_INCREMENT PRIMARY KEY, institution_id INT NOT NULL, payment_id INT NOT NULL,
  receipt_number VARCHAR(80) NOT NULL, snapshot JSON NOT NULL, created_at DATETIME NOT NULL,
  FOREIGN KEY (institution_id) REFERENCES institutions(id), FOREIGN KEY (payment_id) REFERENCES tuition_payments(id),
  UNIQUE KEY uq_fee_receipt_payment (payment_id), UNIQUE KEY uq_fee_receipt_number (receipt_number)
) ENGINE=InnoDB;
