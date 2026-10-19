-- Idempotent MySQL triggers, functions, procedures (including a real cursor) and views.
-- Applied after 01_schema.sql. Use the mysql CLI, not the Django SQL executor.
USE gdg_workshops;

DROP TRIGGER IF EXISTS trg_registration_guard;
DROP TRIGGER IF EXISTS trg_registration_outbox;
DROP TRIGGER IF EXISTS trg_cancel_outbox;
DROP PROCEDURE IF EXISTS sp_register_member;
DROP PROCEDURE IF EXISTS sp_cancel_workshop;
DROP PROCEDURE IF EXISTS sp_repair_missing_cancellation_events;
DROP FUNCTION IF EXISTS fn_seats_remaining;
DROP FUNCTION IF EXISTS fn_retry_delay_seconds;
DROP VIEW IF EXISTS v_workshop_metrics;
DROP VIEW IF EXISTS v_notification_queue_summary;
DROP VIEW IF EXISTS v_member_registrations;

DELIMITER $$

CREATE FUNCTION fn_seats_remaining(p_workshop_id BIGINT UNSIGNED)
RETURNS BIGINT
READS SQL DATA
BEGIN
  DECLARE v_capacity BIGINT DEFAULT NULL;
  DECLARE v_used BIGINT DEFAULT 0;
  DECLARE v_exists INT DEFAULT 0;
  SELECT COUNT(*), MAX(capacity) INTO v_exists, v_capacity
  FROM workshops WHERE id = p_workshop_id;
  IF v_exists = 0 THEN RETURN -2; END IF;
  IF v_capacity IS NULL THEN RETURN -1; END IF;
  SELECT COUNT(*) INTO v_used FROM registrations WHERE workshop_id = p_workshop_id;
  RETURN GREATEST(0, v_capacity - v_used);
END$$

CREATE FUNCTION fn_retry_delay_seconds(p_attempt INT UNSIGNED)
RETURNS INT UNSIGNED
DETERMINISTIC NO SQL
BEGIN
  RETURN LEAST(300, CAST(POW(2, LEAST(GREATEST(p_attempt, 1), 9)) AS UNSIGNED));
END$$

CREATE TRIGGER trg_registration_guard
BEFORE INSERT ON registrations FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(20) DEFAULT NULL;
  DECLARE v_role VARCHAR(20) DEFAULT NULL;
  DECLARE v_capacity INT UNSIGNED DEFAULT NULL;
  DECLARE v_used BIGINT DEFAULT 0;
  SELECT status, capacity INTO v_status, v_capacity
    FROM workshops WHERE id = NEW.workshop_id;
  IF v_status IS NULL OR v_status <> 'OPEN' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='WORKSHOP_NOT_OPEN';
  END IF;
  SELECT role INTO v_role FROM accounts WHERE id = NEW.member_id;
  IF v_role IS NULL OR v_role <> 'MEMBER' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='MEMBER_ROLE_REQUIRED';
  END IF;
  IF v_capacity IS NOT NULL THEN
    SELECT COUNT(*) INTO v_used FROM registrations WHERE workshop_id = NEW.workshop_id;
    IF v_used >= v_capacity THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='WORKSHOP_FULL';
    END IF;
  END IF;
END$$

-- Trigger writes the event in the SAME DB transaction as the registration.
CREATE TRIGGER trg_registration_outbox
AFTER INSERT ON registrations FOR EACH ROW
BEGIN
  DECLARE v_title VARCHAR(180);
  DECLARE v_email VARCHAR(254);
  DECLARE v_name VARCHAR(120);
  SELECT title INTO v_title FROM workshops WHERE id = NEW.workshop_id;
  SELECT email, full_name INTO v_email, v_name FROM accounts WHERE id = NEW.member_id;
  INSERT INTO notification_outbox
    (event_key, event_type, workshop_id, registration_id, member_id, payload)
  VALUES (
    CONCAT('registration:', NEW.id, ':confirmed'), 'REGISTRATION_CONFIRMED',
    NEW.workshop_id, NEW.id, NEW.member_id,
    JSON_OBJECT('type','REGISTRATION_CONFIRMED','workshop_id',NEW.workshop_id,
                'workshop_title',v_title,'registration_id',NEW.id,
                'recipient_email',v_email,'recipient_name',v_name)
  );
  INSERT INTO activity_audit (actor_id, action, entity_type, entity_id, details)
  VALUES (NEW.member_id,'REGISTRATION_CREATED','registration',NEW.id,
    JSON_OBJECT('workshop_id',NEW.workshop_id));
END$$

-- Cancellation fanout is transactionally atomic with changing workshop status.
CREATE TRIGGER trg_cancel_outbox
AFTER UPDATE ON workshops FOR EACH ROW
BEGIN
  IF OLD.status <> 'CANCELLED' AND NEW.status = 'CANCELLED' THEN
    INSERT INTO notification_outbox
      (event_key, event_type, workshop_id, registration_id, member_id, payload)
    SELECT CONCAT('registration:',r.id,':cancelled'), 'WORKSHOP_CANCELLED',
           NEW.id, r.id, r.member_id,
           JSON_OBJECT('type','WORKSHOP_CANCELLED','workshop_id',NEW.id,
                       'workshop_title',NEW.title,'registration_id',r.id,
                       'recipient_email',a.email,'recipient_name',a.full_name)
    FROM registrations r JOIN accounts a ON a.id = r.member_id
    WHERE r.workshop_id = NEW.id;
    INSERT INTO activity_audit (actor_id, action, entity_type, entity_id, details)
    VALUES (NEW.created_by_id,'WORKSHOP_CANCELLED','workshop',NEW.id,
      JSON_OBJECT('title',NEW.title));
  END IF;
END$$

-- The calling application owns the transaction. Serialize on the workshop row.
CREATE PROCEDURE sp_register_member(
  IN p_member_id BIGINT UNSIGNED, IN p_workshop_id BIGINT UNSIGNED,
  OUT p_registration_id BIGINT UNSIGNED)
BEGIN
  DECLARE v_status VARCHAR(20) DEFAULT NULL;
  DECLARE v_capacity INT UNSIGNED DEFAULT NULL;
  DECLARE v_used BIGINT DEFAULT 0;
  DECLARE v_role VARCHAR(20) DEFAULT NULL;
  IF NOT EXISTS (SELECT 1 FROM workshops WHERE id = p_workshop_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='WORKSHOP_NOT_FOUND';
  END IF;
  SELECT status, capacity INTO v_status, v_capacity
    FROM workshops WHERE id = p_workshop_id FOR UPDATE;
  IF v_status <> 'OPEN' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='WORKSHOP_NOT_OPEN';
  END IF;
  SELECT role INTO v_role FROM accounts WHERE id = p_member_id;
  IF v_role IS NULL OR v_role <> 'MEMBER' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='MEMBER_ROLE_REQUIRED';
  END IF;
  IF v_capacity IS NOT NULL THEN
    SELECT COUNT(*) INTO v_used FROM registrations WHERE workshop_id=p_workshop_id;
    IF v_used >= v_capacity THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='WORKSHOP_FULL';
    END IF;
  END IF;
  INSERT INTO registrations (workshop_id, member_id) VALUES(p_workshop_id,p_member_id);
  SET p_registration_id = LAST_INSERT_ID();
END$$

CREATE PROCEDURE sp_cancel_workshop(
  IN p_workshop_id BIGINT UNSIGNED, IN p_organizer_id BIGINT UNSIGNED,
  OUT p_changed BOOLEAN)
BEGIN
  DECLARE v_owner BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_status VARCHAR(20) DEFAULT NULL;
  IF NOT EXISTS (SELECT 1 FROM workshops WHERE id = p_workshop_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='WORKSHOP_NOT_FOUND';
  END IF;
  SELECT created_by_id, status INTO v_owner, v_status
    FROM workshops WHERE id=p_workshop_id FOR UPDATE;
  IF v_owner <> p_organizer_id THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='NOT_WORKSHOP_OWNER';
  END IF;
  SET p_changed = FALSE;
  IF v_status = 'OPEN' THEN
    UPDATE workshops SET status='CANCELLED', cancelled_at=UTC_TIMESTAMP(6)
      WHERE id=p_workshop_id;
    SET p_changed = TRUE;
  END IF;
END$$

-- Cursor-based repair is safe to rerun: UNIQUE(event_key) prevents duplicates.
-- Use only after cancellation if an older/external integration missed the trigger.
CREATE PROCEDURE sp_repair_missing_cancellation_events(IN p_workshop_id BIGINT UNSIGNED)
BEGIN
  DECLARE v_done BOOLEAN DEFAULT FALSE;
  DECLARE v_reg BIGINT UNSIGNED;
  DECLARE v_member BIGINT UNSIGNED;
  DECLARE v_email VARCHAR(254);
  DECLARE v_name VARCHAR(120);
  DECLARE v_title VARCHAR(180);
  DECLARE reg_cursor CURSOR FOR
    SELECT r.id,r.member_id,a.email,a.full_name,w.title
    FROM registrations r
    JOIN accounts a ON a.id=r.member_id
    JOIN workshops w ON w.id=r.workshop_id
    WHERE r.workshop_id=p_workshop_id AND w.status='CANCELLED';
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done=TRUE;
  OPEN reg_cursor;
  read_loop: LOOP
    FETCH reg_cursor INTO v_reg,v_member,v_email,v_name,v_title;
    IF v_done THEN LEAVE read_loop; END IF;
    INSERT IGNORE INTO notification_outbox
      (event_key,event_type,workshop_id,registration_id,member_id,payload)
    VALUES(CONCAT('registration:',v_reg,':cancelled'),'WORKSHOP_CANCELLED',
      p_workshop_id,v_reg,v_member,
      JSON_OBJECT('type','WORKSHOP_CANCELLED','workshop_id',p_workshop_id,
                  'workshop_title',v_title,'registration_id',v_reg,
                  'recipient_email',v_email,'recipient_name',v_name));
  END LOOP;
  CLOSE reg_cursor;
END$$

DELIMITER ;

CREATE VIEW v_workshop_metrics AS
SELECT w.id AS workshop_id,w.title,w.status,w.capacity,w.starts_at,
  (SELECT COUNT(*) FROM registrations r WHERE r.workshop_id=w.id) AS registrations,
  fn_seats_remaining(w.id) AS seats_remaining,
  (SELECT COUNT(*) FROM notification_outbox o WHERE o.workshop_id=w.id AND o.status='DELIVERED') AS delivered_notifications,
  (SELECT COUNT(*) FROM notification_outbox o WHERE o.workshop_id=w.id AND o.status<>'DELIVERED') AS outstanding_notifications
FROM workshops w;

CREATE VIEW v_notification_queue_summary AS
SELECT status, event_type, COUNT(*) AS event_count,
       COALESCE(SUM(attempts),0) AS total_delivery_attempts,
       MIN(next_attempt_at) AS earliest_retry
FROM notification_outbox GROUP BY status,event_type;

CREATE VIEW v_member_registrations AS
SELECT r.id AS registration_id,r.member_id,a.full_name,a.email,
       w.id AS workshop_id,w.title,w.status AS workshop_status,r.registered_at
FROM registrations r JOIN accounts a ON a.id=r.member_id
JOIN workshops w ON w.id=r.workshop_id;
