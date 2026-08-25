from pathlib import Path

p = Path("app/core/upstream_miner.py")
content = p.read_text(encoding="utf-8")

old_method = """    @classmethod
    def extract_error_signature(cls, text: str) -> Optional[str]:
        \"\"\"Extracts exact error signature pattern from changelog text.\"\"\"
        match = re.search(r'raises\s+`?([A-Za-z0-9_.]+(?:Exception|Error|Warning)[\w\s:()\'".,`\-]+)`?', text, re.IGNORECASE)
        if match:
            sig = match.group(1).strip("`\"' ")
            if len(sig) > 10:
                return sig

        match = re.search(r'(DeprecationWarning:[\w\s:()\'".,`\-]+)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip("`\"' ")

        return None"""

new_method = """    @classmethod
    def extract_error_signature(cls, text: str) -> Optional[str]:
        \"\"\"Extracts exact error signature pattern from changelog text.\"\"\"
        # 1. Match raise / raises / throws / direct Exception pattern in backticks or text
        match = re.search(r'(?:raise|raises|raising|throw|throws|threw|causes)?\s*`?([A-Za-z0-9_.]*(?:Exception|Error|Warning)[\w\s:()\'".,`\-]+)`?', text, re.IGNORECASE)
        if match:
            sig = match.group(1).strip("`\"' .")
            if len(sig) > 8:
                return sig

        # 2. Look for explicit DeprecationWarning
        match = re.search(r'(DeprecationWarning:[\w\s:()\'".,`\-]+)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip("`\"' .")

        return None"""

assert old_method in content
content = content.replace(old_method, new_method)
p.write_text(content, encoding="utf-8")
print("Updated extract_error_signature regex in upstream_miner.py.")
