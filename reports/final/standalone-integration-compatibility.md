# Standalone PathLab compatibility

The adapter opens MC-V1 directly, lists level-0 tile addresses, reads a requested packet,
checks the container and candidate digests, decodes without source WSI pixels, and verifies
the embedded self-verifying HE-V1 certificate. It is a standalone demonstration; no PathLab
Viewer or Forge repository was modified.

Cold and warm latency measurements are runtime outputs and are not claimed from synthetic CI.
Browser delivery would require an HTTP range-capable service preserving packet bytes and the
certificate contract. Clinical use is not established.
