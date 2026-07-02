Put VAST XSD files here.

Recommended naming:
- vast_2.0.xsd
- vast_3.0.xsd
- vast_4.0.xsd
- vast_4.1.xsd
- vast_4.2.xsd

**VAST 4.3** has no separate XSD from IAB. The validator automatically uses `vast_4.2.xsd` for 4.3 documents.

You can pass an explicit XSD via CLI (`--xsd`) or let the validator auto-resolve by VAST version (`--schema-dir`).
