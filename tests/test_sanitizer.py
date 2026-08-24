from app.core.sanitizer import ZeroPiiSanitizer


def test_sanitize_emails():
    raw = "Contact dev@example.com or admin@synapsemesh.dev for info."
    cleaned = ZeroPiiSanitizer.sanitize_text(raw)
    assert "dev@example.com" not in cleaned
    assert "[REDACTED_EMAIL]" in cleaned


def test_sanitize_ips():
    raw = "Server crashed at 192.168.1.100 and 10.0.0.1"
    cleaned = ZeroPiiSanitizer.sanitize_text(raw)
    assert "192.168.1.100" not in cleaned
    assert "[REDACTED_IP]" in cleaned


def test_sanitize_secrets():
    raw = "Key: sk-abcdef12345678901234567890 and token ghp_123456789012345678901234567890123456"
    cleaned = ZeroPiiSanitizer.sanitize_text(raw)
    assert "sk-" not in cleaned
    assert "ghp_" not in cleaned
    assert "[REDACTED_SECRET]" in cleaned


def test_sanitize_user_paths():
    raw = "Traceback in file /Users/johndoe/projects/app/main.py or /home/ubuntu/service.py"
    cleaned = ZeroPiiSanitizer.sanitize_text(raw)
    assert "johndoe" not in cleaned
    assert "/Users/" not in cleaned
    assert "[REDACTED_PATH]" in cleaned
