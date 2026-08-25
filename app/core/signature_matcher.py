import re
from typing import Dict, Any, Tuple, Optional, Set

class SignatureMatcher:
    """
    High-precision structural error signature parser and matcher.
    Distinguishes between:
    - Exception classes (e.g. AttributeError, ImportError, ArgumentError)
    - Target entities (e.g. DataFrame, module 'numpy', Query)
    - Critical discriminating attributes/symbols (e.g. 'append', 'NAN', 'SELECT 1')
    - Quoted literals and method calls ('foo', `bar`, baz())
    """

    STOPWORDS: Set[str] = {
        "the", "was", "has", "been", "and", "for", "with", "from", "that", "this", 
        "use", "instead", "you", "tried", "access", "error", "warning", "exception",
        "cannot", "could", "not", "module", "object", "type", "value", "out", "while",
        "when", "into", "over", "time", "timed", "mode", "render", "rendering",
        "passed", "instead", "only", "must", "should", "some", "like", "such", "than",
        "after", "failed", "processing", "unrelated", "while", "object", "has", "no", "attribute"
    }

    # Common structural error patterns
    ATTR_ERROR_PATTERN = re.compile(
        r"(?:attributeerror|typeerror):\s*(?:(?:'|`|\")?([a-zA-Z0-9_\.]+)(?:'|`|\")?\s*(?:object|module)\s*has\s*no\s*attribute\s*(?:'|`|\")?([a-zA-Z0-9_]+)(?:'|`|\")?|"
        r"(?:'|`|\")?([a-zA-Z0-9_\.]+)(?:'|`|\")?\s*(?:object|module)?\s*has\s*no\s*attribute\s*(?:'|`|\")?([a-zA-Z0-9_]+)(?:'|`|\")?)",
        re.IGNORECASE
    )

    IMPORT_ERROR_PATTERN = re.compile(
        r"(?:importerror|modulenotfounderror):\s*(?:cannot\s*import\s*name\s*(?:'|`|\")?([a-zA-Z0-9_]+)(?:'|`|\")?\s*from\s*(?:'|`|\")?([a-zA-Z0-9_\.]+)(?:'|`|\")?|"
        r"no\s*module\s*named\s*(?:'|`|\")?([a-zA-Z0-9_\.]+)(?:'|`|\")?)",
        re.IGNORECASE
    )

    REMOVED_IN_PATTERN = re.compile(
        r"(?:attributeerror|deprecationwarning|legacyapiwarning|removedin\w+warning):\s*[`'\"]?([a-zA-Z0-9_\.]+(?:\(\))?)[`'\"]?\s*(?:was|is|has\s*been)\s*(?:removed|deprecated|legacy)",
        re.IGNORECASE
    )

    @classmethod
    def extract_structure(cls, text: str) -> Dict[str, Any]:
        """Extracts structured semantic fields from an error signature."""
        clean = text.strip()
        
        # 1. Quoted literals ('foo', `bar`, "baz")
        quoted = set(re.findall(r"['`\"]([a-zA-Z0-9_\.\s\-]+)['`\"]", clean))
        
        # 2. Method calls (foo())
        methods = set(re.findall(r"\b([a-zA-Z0-9_]+)\(\)", clean))
        
        # 3. Exception Class
        exc_match = re.search(r"\b([a-zA-Z0-9_]+(?:Error|Warning|Exception))\b", clean)
        exc_class = exc_match.group(1).lower() if exc_match else None

        # 4. Pattern: AttributeError (target, attribute)
        attr_match = cls.ATTR_ERROR_PATTERN.search(clean)
        target_obj = None
        missing_attr = None
        if attr_match:
            g = [x for x in attr_match.groups() if x]
            if len(g) >= 2:
                target_obj, missing_attr = g[0].lower(), g[1].lower()
            elif len(g) == 1:
                missing_attr = g[0].lower()

        # 5. Pattern: ImportError (symbol, module)
        import_match = cls.IMPORT_ERROR_PATTERN.search(clean)
        import_symbol = None
        import_mod = None
        if import_match:
            g = [x for x in import_match.groups() if x]
            if len(g) >= 2:
                import_symbol, import_mod = g[0].lower(), g[1].lower()
            elif len(g) == 1:
                import_symbol = g[0].lower()

        # 6. Pattern: Removed in Version
        removed_match = cls.REMOVED_IN_PATTERN.search(clean)
        removed_sym = removed_match.group(1).lower() if removed_match else None

        # 7. Whole word tokens
        all_words = set(re.findall(r"[a-zA-Z0-9_]+", clean.lower()))
        distinctive_tokens = {w for w in all_words if len(w) > 3 and w not in cls.STOPWORDS}

        return {
            "raw": clean.lower(),
            "exc_class": exc_class,
            "target_obj": target_obj,
            "missing_attr": missing_attr,
            "import_symbol": import_symbol,
            "import_mod": import_mod,
            "removed_sym": removed_sym,
            "quoted": {q.lower() for q in quoted},
            "methods": {m.lower() for m in methods},
            "distinctive_tokens": distinctive_tokens
        }

    @classmethod
    def compute_match(
        cls,
        query_text: str,
        target_text: str,
        target_regex: Optional[str] = None,
        variants: Optional[list] = None
    ) -> Tuple[bool, float]:
        """
        Computes structured match and matchConfidence between query error and candidate recipe error.
        If variants are supplied, evaluates query against all declared variants.
        Returns (is_match, match_confidence).
        """
        # 1. Evaluate primary signature
        is_match, conf = cls._evaluate_single_match(query_text, target_text, target_regex)
        if is_match:
            return (True, conf)

        # 2. Evaluate variants if present
        if variants:
            for v in variants:
                v_sig = v.get("errorSignature", "")
                v_regex = v.get("regex")
                v_match, v_conf = cls._evaluate_single_match(query_text, v_sig, v_regex)
                if v_match:
                    return (True, v_conf)

        return (False, 0.0)

    @classmethod
    def _evaluate_single_match(
        cls,
        query_text: str,
        target_text: str,
        target_regex: Optional[str] = None
    ) -> Tuple[bool, float]:
        q = cls.extract_structure(query_text)
        t = cls.extract_structure(target_text)

        # A. Exact full string match
        if q["raw"] == t["raw"] or q["raw"] in t["raw"] or t["raw"] in q["raw"]:
            return (True, 1.0)

        # B. Regex Fingerprint Match
        if target_regex:
            try:
                if re.search(target_regex, query_text, re.IGNORECASE):
                    return (True, 1.0)
            except Exception:
                pass

        # C. Structural AttributeError Gate (CRITICAL DISCRIMINATOR)
        if q["missing_attr"] or t["missing_attr"]:
            # If both have missing attribute parsed, they MUST match!
            if q["missing_attr"] and t["missing_attr"]:
                if q["missing_attr"] != t["missing_attr"]:
                    # frobnicate != append -> STRICT REJECT
                    return (False, 0.0)
                if q["target_obj"] and t["target_obj"] and q["target_obj"] != t["target_obj"]:
                    return (False, 0.0)
                return (True, 0.98)
            elif q["missing_attr"] and not t["missing_attr"]:
                # Query specified an attribute 'frobnicate', but target is not about that attribute
                if q["missing_attr"] not in t["distinctive_tokens"] and q["missing_attr"] not in t["quoted"]:
                    return (False, 0.0)

        # D. Structural ImportError / ModuleNotFoundError Gate
        if q["import_symbol"] and t["import_symbol"]:
            if q["import_symbol"] != t["import_symbol"]:
                return (False, 0.0)
            return (True, 0.98)

        # E. Structural Removed Symbol Gate (e.g. np.NAN vs Query.get)
        if q["removed_sym"] and t["removed_sym"]:
            q_clean = q["removed_sym"].replace("()", "")
            t_clean = t["removed_sym"].replace("()", "")
            if q_clean == t_clean:
                return (True, 0.98)
            return (False, 0.0)

        # F. Quoted Literal / Method Invocations Gate
        if q["quoted"]:
            if not any(ql in t["raw"] or ql in t["quoted"] for ql in q["quoted"]):
                return (False, 0.0)

        if q["methods"]:
            if not any(qm in t["raw"] or qm in t["methods"] for qm in q["methods"]):
                return (False, 0.0)

        # G. High-Entropy Token Overlap (General Fallback)
        common_tokens = q["distinctive_tokens"].intersection(t["distinctive_tokens"])
        if len(common_tokens) >= 3:
            ratio = len(common_tokens) / max(len(q["distinctive_tokens"]), 1)
            if ratio >= 0.6:
                return (True, min(0.95, round(0.5 + ratio * 0.45, 2)))

        return (False, 0.0)
