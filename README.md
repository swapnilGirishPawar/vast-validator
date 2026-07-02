# VAST Validate

Python utility to validate VAST XML files against XSD schemas using `lxml`.

## What this gives you

- Validates VAST XML against an explicit XSD.
- Supports auto schema selection based on `<VAST version="...">`.
- Works with multiple VAST versions (`2.0`, `3.0`, `4.0`, `4.1`, `4.2`, `4.3`) if corresponding XSD files are present.
- Returns line/column-level validation errors.
- CLI + JSON output mode for easy integration with backend services.

## Project structure

- `vast_validate/validator.py`: core validation logic
- `vast_validate/cli.py`: command-line interface
- `schemas/`: keep your versioned XSD files here

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

or install as package:

```bash
pip install -e .
```

## Add XSD files

Place your XSD files in `schemas/` with this naming:

- `schemas/vast_2.0.xsd`
- `schemas/vast_3.0.xsd`
- `schemas/vast_4.0.xsd`
- `schemas/vast_4.1.xsd`
- `schemas/vast_4.2.xsd`
- `schemas/vast_4.3.xsd`

You can use official VAST schemas from IAB Tech Lab and/or your own customized schemas.

Schema auto-detection is flexible. It can parse versions from names like:
- `vast_3.0.xsd`
- `VAST_3.0.xsd`
- `vast4.0.xsd`
- `vast_2.0.1.xsd`

Fallback behavior when exact version is missing:
- first try exact version
- then same major+minor patch (example: `2.0` -> `2.0.1`)
- then latest schema within same major
- then latest schema overall

The chosen behavior is shown as `SCHEMA-NOTE` in output.

## Usage

### 0) Extract `vast.xml` from OpenRTB response JSON

Your partner response usually has VAST in:
- `raw_bid_response.seatbid[<i>].bid[<j>].adm` (inline VAST XML string)

Extract and save it:

```bash
vast-extract .\response.json --output .\samples\vast.xml
```

If it is a wrapper and you want to follow `VASTAdTagURI` URL and save the downstream VAST:

```bash
vast-extract .\response.json --output .\samples\vast.xml --follow-wrapper-uri
```

### 1) Explicit XSD

```bash
vast-validate .\samples\vast.xml --xsd .\schemas\vast_4.2.xsd
```

### 2) Auto-detect by version

If your XML root has version attribute, e.g. `<VAST version="4.2">`, then:

```bash
vast-validate .\samples\vast.xml --schema-dir .\schemas
```

If `--schema-dir` is omitted, it defaults to `schemas` next to the XML file.

### 3) JSON response

```bash
vast-validate .\samples\vast.xml --schema-dir .\schemas --json
```

### 4) Pretty summary with OpenRTB context

Include partner + bid context in output:

```bash
vast-validate .\vast.xml --schema-dir .\schemas --response-json .\response.json
```

With JSON output:

```bash
vast-validate .\vast.xml --schema-dir .\schemas --response-json .\response.json --json
```

Disable color (plain text):

```bash
vast-validate .\vast.xml --schema-dir .\schemas --response-json .\response.json --no-color
```

### 5) Save report file (overwrites every run)

By default, each run writes a formatted report to:
- `.\vast_validation_report.txt`

Custom report filename:

```bash
vast-validate .\vast.xml --schema-dir .\schemas --response-json .\response.json --report-file .\team_report.txt
```

Example output:

```json
{
  "is_valid": false,
  "vast_version": "4.2",
  "schema_path": "C:\\path\\schemas\\vast_4.2.xsd",
  "errors": [
    {
      "line": 18,
      "column": 0,
      "domain": "SCHEMASV",
      "type": "SCHEMAV_ELEMENT_CONTENT",
      "message": "Element 'Creatives': Missing child element(s). Expected is ..."
    }
  ]
}
```

## Exit codes

- `0`: valid VAST
- `1`: invalid VAST (schema errors found)
- `2`: fatal error (missing files, malformed XML/XSD, schema resolution error)

## Integrating into your adserver flow

Typical backend flow:

1. Receive VAST XML from demand partner or generated line item logic.
2. Detect version from XML root attribute.
3. Validate against matching schema.
4. Store validation status and full error list for debugging/auditing.
5. Reject bad payloads early before serving.
