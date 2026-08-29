import re
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion
from typing import Optional, Tuple, Dict, Any, Set

class VersionMatcher:
    """
    Evaluates semantic package and runtime version constraints with mathematical interval intersection:
    - MATCH: Target dependency specified and non-empty intersection
    - MISMATCH: Target dependency specified with empty intersection
    - UNKNOWN: Target dependency not specified in request
    """

    @staticmethod
    def evaluate_environment(
        pkg_name: str,
        req_packages_dict: Optional[Dict[str, str]],
        affected_version_spec: Optional[str]
    ) -> Tuple[str, Optional[bool]]:
        """
        Evaluates epistemological status of environment:
        Returns (environmentStatus, versionConstraintMatched).
        """
        if not req_packages_dict or pkg_name.lower() not in {k.lower(): v for k, v in req_packages_dict.items()}:
            return ("UNKNOWN", None)

        # Normalize key lookup
        norm_map = {k.lower(): v for k, v in req_packages_dict.items()}
        req_version_spec = norm_map.get(pkg_name.lower())
        
        is_compat = VersionMatcher.check_version_compatibility(req_version_spec, affected_version_spec)
        if is_compat:
            return ("MATCH", True)
        else:
            return ("MISMATCH", False)

    @staticmethod
    def check_version_compatibility(
        requested_version_spec: Optional[str],
        affected_version_spec: Optional[str]
    ) -> bool:
        """
        Computes true mathematical interval intersection:
        Returns True iff (requestedRange ∩ affectedRange ≠ ∅).
        """
        if not requested_version_spec or not affected_version_spec:
            return False
            
        clean_req = requested_version_spec.strip()
        clean_aff = affected_version_spec.strip()
        
        # 1. Fast Path: Single exact version e.g. "1.5.3", "v1.5.3", "==1.5.3"
        clean_ver = clean_req.lstrip("v ").strip()
        if clean_ver.startswith("=="):
            clean_ver = clean_ver[2:].strip()
            
        if re.match(r"^[0-9]+(?:\.[0-9]+)*(?:[a-zA-Z0-9_.-]+)?$", clean_ver):
            try:
                v = Version(clean_ver)
                aff_spec = SpecifierSet(clean_aff)
                if v in aff_spec:
                    return True
                if v.is_prerelease:
                    base_v = Version(v.base_version)
                    if base_v in aff_spec:
                        return True
                return False
            except Exception:
                pass

        # 2. General Interval Intersection for Specifiers (e.g. '>=1.5,<2.0')
        try:
            normalized_clauses = []
            for clause in clean_req.split(","):
                c = clause.strip()
                if not any(c.startswith(op) for op in ("<", ">", "=", "~", "!")):
                    c = "==" + c.lstrip("v= ")
                normalized_clauses.append(c)
                
            req_spec = SpecifierSet(",".join(normalized_clauses))
            aff_spec = SpecifierSet(clean_aff)
        except (InvalidSpecifier, InvalidVersion, ValueError, TypeError):
            return False

        # Extract all boundary candidate version points from both constraints
        all_ver_strs = re.findall(r"[0-9]+(?:\.[0-9]+)*", clean_req + " " + clean_aff)
        test_versions: Set[Version] = set()
        for s in all_ver_strs:
            parts = [int(p) for p in s.split(".")]
            while len(parts) < 3:
                parts.append(0)
            maj, min_, pat = parts[0], parts[1], parts[2]
            
            # Boundary probe points
            test_versions.add(Version(f"{maj}.{min_}.{pat}"))
            test_versions.add(Version(f"{maj}.{min_}.{pat+1}"))
            test_versions.add(Version(f"{maj}.{min_+1}.0"))
            test_versions.add(Version(f"{maj+1}.0.0"))
            if pat > 0:
                test_versions.add(Version(f"{maj}.{min_}.{pat-1}"))
            if min_ > 0:
                test_versions.add(Version(f"{maj}.{min_-1}.99"))
            if maj > 0:
                test_versions.add(Version(f"{maj-1}.99.99"))

        if not test_versions:
            return False

        # If ANY probe version satisfies BOTH sets, intersection is non-empty
        for v in test_versions:
            if (v in req_spec) and (v in aff_spec):
                return True
                
        return False

    @staticmethod
    def matches_exact_observed_version(
        requested_version_spec: Optional[str],
        observed_version: Optional[str],
    ) -> bool:
        """Return true only when a request names the exact observed release.

        Ranges and prereleases do not inherit a run recorded for one concrete
        release, even when their constraints overlap the bundle's affected
        range.
        """
        if not isinstance(requested_version_spec, str) or not isinstance(observed_version, str):
            return False
        requested = requested_version_spec.strip()
        if requested.startswith("=="):
            requested = requested[2:].strip()
        requested = requested.lstrip("v").strip()
        if not requested or any(
            token in requested for token in ("<", ">", "~", "!", "*", ",")
        ):
            return False
        try:
            return Version(requested) == Version(observed_version.strip())
        except (InvalidVersion, TypeError, ValueError):
            return False
