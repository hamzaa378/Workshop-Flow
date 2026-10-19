-- Read-only inspection after seed_demo and after exercising the API.
USE gdg_workshops;
SHOW TABLES;
SHOW TRIGGERS;
SHOW PROCEDURE STATUS WHERE Db='gdg_workshops';
SHOW FUNCTION STATUS WHERE Db='gdg_workshops';
SELECT * FROM v_workshop_metrics ORDER BY workshop_id DESC;
SELECT * FROM v_notification_queue_summary ORDER BY status,event_type;
SELECT * FROM v_member_registrations ORDER BY registration_id DESC LIMIT 25;
SELECT id,event_key,status,attempts,next_attempt_at,last_http_status
  FROM notification_outbox ORDER BY id DESC LIMIT 30;
SELECT outbox_id,attempt_number,outcome,http_status,latency_ms,created_at
  FROM delivery_attempts ORDER BY id DESC LIMIT 30;
