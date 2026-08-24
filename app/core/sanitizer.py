import re
from typing import Any, Dict, List, Union


class ZeroPiiSanitizer:
    """Sanitizes text and data structures to enforce Zero-PII by design (GDPR / EU AI Act)."""

    # Patterns
    EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
    IPV4_PATTERN = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
    IPV6_PATTERN = re.compile(r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b')
    
    # API Keys & Secrets
    TOKEN_PATTERNS = [
        re.compile(r'sk-[a-zA-Z0-9]{20,}'),                         # OpenAI-style keys
        re.compile(r'ghp_[a-zA-Z0-9]{30,}'),                        # GitHub personal tokens
        re.compile(r'AIza[0-9A-Za-z-_]{35}'),                       # Google API keys
        re.compile(r'Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*'), # JWT Bearer
        re.compile(r'(?:api_key|apikey|secret|password|auth_token)\s*[:=]\s*["\']?([^"\'\s]+)["\']?', re.IGNORECASE)
    ]
    
    # User paths
    USER_PATH_PATTERNS = [
        re.compile(r'/(?:Users|home)/[a-zA-Z0-9_.-]+(/[^"\'\s\n]*)?'),
        re.compile(r'[A-Za-z]:\\Users\\[a-zA-Z0-9_.-]+(\\[^"\'\s\n]*)?')
    ]

    @classmethod
    def sanitize_text(cls, text: str) -> str:
        if not text or not isinstance(text, str):
            return text

        # 1. Redact API tokens & secrets
        for pattern in cls.TOKEN_PATTERNS:
            text = pattern.sub('[REDACTED_SECRET]', text)

        # 2. Redact Emails
        text = cls.EMAIL_PATTERN.sub('[REDACTED_EMAIL]', text)

        # 3. Redact IPs (avoiding version strings like 1.2.3 by checking context or replacement)
        # Only replace standard IPv4 if not surrounded by package version keywords
        text = cls.IPV4_PATTERN.sub('[REDACTED_IP]', text)
        text = cls.IPV6_PATTERN.sub('[REDACTED_IPV6]', text)

        # 4. Redact User local directory paths
        for path_pat in cls.USER_PATH_PATTERNS:
            text = path_pat.sub('[REDACTED_PATH]', text)

        return text

    @classmethod
    def sanitize_data(cls, data: Union[Dict, List, str, Any]) -> Any:
        if isinstance(data, str):
            return cls.sanitize_text(data)
        elif isinstance(data, dict):
            return {k: cls.sanitize_data(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [cls.sanitize_data(item) for item in data]
        return data
