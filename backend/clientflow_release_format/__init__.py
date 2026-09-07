"""Canonical ClientFlow release-format validation shared by backend and release tooling."""
from .constants import (
    ARTIFACT_TYPE_RUNTIME_RELEASE,
    CHANNEL,
    DOMAIN_NAMES,
    INSTALL_MODE_FRESH,
    INSTALL_MODE_UPDATE,
    INTEGRITY_ALGORITHM,
    MANIFEST_SCHEMA,
    MAX_BUNDLE_BYTES,
    PRODUCT,
)
from .manifest import ManifestError, load_json_object, validate_manifest
from .bundle import BundleFormatError, verify_bundle_structure
from .crypto import sha256_file

__all__ = [
    "ARTIFACT_TYPE_RUNTIME_RELEASE",
    "BundleFormatError",
    "CHANNEL",
    "DOMAIN_NAMES",
    "INSTALL_MODE_FRESH",
    "INSTALL_MODE_UPDATE",
    "INTEGRITY_ALGORITHM",
    "MANIFEST_SCHEMA",
    "MAX_BUNDLE_BYTES",
    "ManifestError",
    "PRODUCT",
    "load_json_object",
    "sha256_file",
    "validate_manifest",
    "verify_bundle_structure",
]
