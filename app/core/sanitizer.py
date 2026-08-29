import re
import ipaddress
from typing import Any, Dict, List, Union


class ZeroPiiSanitizer:
    """Sanitizes text and data structures to enforce Zero-PII by design (GDPR / EU AI Act)."""

    # Patterns
    EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
    IPV4_PATTERN = re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])')
    IPV6_CANDIDATE_PATTERN = re.compile(
        r'(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,8}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])'
    )
    
    # API Keys & Secrets
    TOKEN_PATTERNS = [
        re.compile(r'sk-[a-zA-Z0-9]{20,}'),                         # OpenAI-style keys
        re.compile(r'ghp_[a-zA-Z0-9]{30,}'),                        # GitHub personal tokens
        re.compile(r'AIza[0-9A-Za-z-_]{35}'),                       # Google API keys
        re.compile(r'Bearer\s+[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.?[A-Za-z0-9\-_=]*'), # JWT Bearer
        re.compile(r'(?:api_key|apikey|secret|password|auth_token)\s*[:=]\s*["\']?([^"\'\s]+)["\']?', re.IGNORECASE)
    ]
    
    # Prompt Injection & Dangerous Payload Patterns
    INJECTION_PATTERNS = [
        re.compile(r'(?i)\b(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:previous|prior|existing)\s+instructions\b'),
        re.compile(r'(?i)\b(?:system|assistant|human|user)\s*:\s*(?:you\s+are|you\s+must|do\s+not|act\s+as)\b'),
        re.compile(r'(?i)(?:curl|wget|nc|bash|sh|zsh)\s+[^|\n]+(?:\|\s*(?:ba)?sh|>|&)'),
        re.compile(r'(?i)<\s*script[\s\S]*?>[\s\S]*?<\s*/\s*script\s*>'),
        re.compile(r'(?i)\b(?:eval|exec|os\.system|subprocess\.Popen)\s*\('),
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

        # 1. Redact Prompt Injection & Command Execution Payloads
        for pattern in cls.INJECTION_PATTERNS:
            text = pattern.sub('[REDACTED_INJECTION_PAYLOAD]', text)

        # 2. Redact API tokens & secrets
        for pattern in cls.TOKEN_PATTERNS:
            text = pattern.sub('[REDACTED_SECRET]', text)

        # 3. Redact Emails
        text = cls.EMAIL_PATTERN.sub('[REDACTED_EMAIL]', text)

        # 4. Redact IPs (avoiding version strings like 1.2.3 by checking context or replacement)
        def redact_ipv4(match: re.Match) -> str:
            try:
                ipaddress.ip_address(match.group(0))
            except ValueError:
                return match.group(0)
            return '[REDACTED_IP]'

        def redact_ipv6(match: re.Match) -> str:
            candidate = match.group(0)
            try:
                parsed = ipaddress.ip_address(candidate)
            except ValueError:
                return candidate
            return '[REDACTED_IPV6]' if parsed.version == 6 else '[REDACTED_IP]'

        text = cls.IPV4_PATTERN.sub(redact_ipv4, text)
        text = cls.IPV6_CANDIDATE_PATTERN.sub(redact_ipv6, text)

        # 5. Redact User local directory paths
        for path_pat in cls.USER_PATH_PATTERNS:
            text = path_pat.sub('[REDACTED_PATH]', text)

        return text

    @classmethod
    def sanitize_data(cls, data: Union[Dict, List, str, Any]) -> Any:
        if isinstance(data, str):
            return cls.sanitize_text(data)
        elif isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                clean_key = cls.sanitize_text(key) if isinstance(key, str) else key
                if clean_key in sanitized:
                    # Do not let two redacted PII keys silently overwrite data.
                    suffix = 2
                    candidate = f"{clean_key}_{suffix}"
                    while candidate in sanitized:
                        suffix += 1
                        candidate = f"{clean_key}_{suffix}"
                    clean_key = candidate
                sanitized[clean_key] = cls.sanitize_data(value)
            return sanitized
        elif isinstance(data, list):
            return [cls.sanitize_data(item) for item in data]
        return data
