-- MySQL 8.0+; creates the entire application schema; idempotent.
-- Run AFTER 00_database.sql and BEFORE 02_programmability.sql.
USE gdg_workshops;

CREATE TABLE IF NOT EXISTS accounts (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  full_name VARCHAR(120) NOT NULL,
  email VARCHAR(254) NOT NULL,
  role ENUM('ORGANIZER','MEMBER') NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_accounts_email (email),
  KEY idx_accounts_role (role)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS workshops (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  created_by_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(180) NOT NULL,
  description TEXT NOT NULL,
  starts_at DATETIME(6) NOT NULL,
  capacity INT UNSIGNED DEFAULT NULL,
  status ENUM('OPEN','CANCELLED') NOT NULL DEFAULT 'OPEN',
  cancelled_at DATETIME(6) DEFAULT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_workshop_organizer FOREIGN KEY (created_by_id) REFERENCES accounts(id),
  CONSTRAINT ck_workshop_capacity CHECK (capacity IS NULL OR capacity > 0),
  KEY idx_workshops_status_date (status, starts_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS registrations (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  workshop_id BIGINT UNSIGNED NOT NULL,
  member_id BIGINT UNSIGNED NOT NULL,
  registered_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_registration_workshop FOREIGN KEY (workshop_id) REFERENCES workshops(id),
  CONSTRAINT fk_registration_member FOREIGN KEY (member_id) REFERENCES accounts(id),
  UNIQUE KEY uq_workshop_member (workshop_id, member_id),
  KEY idx_registrations_member (member_id, registered_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS notification_outbox (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  event_key VARCHAR(150) NOT NULL,
  event_type ENUM('REGISTRATION_CONFIRMED','WORKSHOP_CANCELLED') NOT NULL,
  workshop_id BIGINT UNSIGNED NOT NULL,
  registration_id BIGINT UNSIGNED NOT NULL,
  member_id BIGINT UNSIGNED NOT NULL,
  payload JSON NOT NULL,
  status ENUM('PENDING','INFLIGHT','RETRY','DELIVERED') NOT NULL DEFAULT 'PENDING',
  attempts INT UNSIGNED NOT NULL DEFAULT 0,
  next_attempt_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  lease_until DATETIME(6) DEFAULT NULL,
  claimed_by VARCHAR(100) DEFAULT NULL,
  delivered_at DATETIME(6) DEFAULT NULL,
  last_http_status SMALLINT UNSIGNED DEFAULT NULL,
  last_error TEXT DEFAULT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_outbox_workshop FOREIGN KEY (workshop_id) REFERENCES workshops(id),
  CONSTRAINT fk_outbox_registration FOREIGN KEY (registration_id) REFERENCES registrations(id),
  CONSTRAINT fk_outbox_member FOREIGN KEY (member_id) REFERENCES accounts(id),
  UNIQUE KEY uq_outbox_event_key (event_key),
  UNIQUE KEY uq_outbox_registration_event (registration_id, event_type),
  KEY idx_outbox_due (status, next_attempt_at, id),
  KEY idx_outbox_lease (status, lease_until),
  KEY idx_outbox_member (member_id, workshop_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS delivery_attempts (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  outbox_id BIGINT UNSIGNED NOT NULL,
  attempt_number INT UNSIGNED NOT NULL,
  outcome ENUM('SUCCESS','HTTP_ERROR','TIMEOUT','NETWORK_ERROR') NOT NULL,
  http_status SMALLINT UNSIGNED DEFAULT NULL,
  latency_ms INT UNSIGNED NOT NULL,
  error_message VARCHAR(500) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_attempt_outbox FOREIGN KEY (outbox_id) REFERENCES notification_outbox(id),
  UNIQUE KEY uq_attempt_outbox_number (outbox_id, attempt_number),
  KEY idx_attempt_created_at (created_at)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS activity_audit (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  actor_id BIGINT UNSIGNED DEFAULT NULL,
  action VARCHAR(100) NOT NULL,
  entity_type VARCHAR(60) NOT NULL,
  entity_id BIGINT UNSIGNED NOT NULL,
  details JSON NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_audit_actor FOREIGN KEY (actor_id) REFERENCES accounts(id),
  KEY idx_audit_created (created_at),
  KEY idx_audit_entity (entity_type, entity_id)
) ENGINE=InnoDB;
