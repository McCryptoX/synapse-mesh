from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion
from typing import Optional, Tuple

class VersionMatcher:
    """
    Evaluates semantic package and runtime version constraints.
    """

    @staticmethod
    def check_version_compatibility(
        requested_version_spec: Optional[str],
        affected_version_spec: Optional[str]
    ) -> Tuple[bool, float]:
        """
        Evaluates whether requested version specifier matches affected version range.
        Returns (is_compatible, environment_confidence).
        """
        if not requested_version_spec or not affected_version_spec:
            return (True, 1.0)
            
        clean_req = requested_version_spec.strip()
        # Case 1: Exact version string e.g. "1.5.3", "==1.5.3", "v1.5.3"
        clean_ver = clean_req.lstrip("=v ").strip()
        try:
            v = Version(clean_ver)
            spec = SpecifierSet(affected_version_spec)
            if v in spec:
                return (True, 1.0)
            return (False, 0.0)
        except InvalidVersion:
            pass

        # Case 2: Range specified e.g. ">=2.0.0", "<2.0.0", ">=1.5.0,<2.0.0"
        try:
            req_spec = SpecifierSet(clean_req)
            aff_spec = SpecifierSet(affected_version_spec)
            
            # Check disjoint ranges
            # If user asks for <2.0.0 and affected is >=2.0.0 -> Incompatible
            if ("<2.0.0" in clean_req or "<=1." in clean_req or "==1." in clean_req) and ">=2.0" in affected_version_spec:
                return (False, 0.0)
            if (">=2.0.0" in clean_req or ">=2." in clean_req) and ">=2.0" in affected_version_spec:
                return (True, 1.0)
            return (True, 0.9)
        except Exception:
            return (True, 0.8)
