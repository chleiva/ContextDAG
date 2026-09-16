# Security

## Credentials

The code calls Amazon Bedrock (bearer token) and, for one calibration pass, the OpenAI API. Both
credentials are read from a git-ignored `.env` at the repository root (`.env.example` lists the
variable names). They are never written to logs, ledgers, results files, or commit history; the
repository history has been scanned for key patterns and contains none.

If you fork this repository, use your own credentials and rotate any key you suspect has been
exposed. Cost guardrails (`budget:` in each phase's `manifest.yaml`) refuse to start model calls past
a hard limit, but they do not protect a leaked key.

## Data

All benchmark text is synthetic and generated for this project. It contains invented people,
organisations, and figures. No personal data, user conversations, or third-party benchmark content
is included; external datasets referenced in `DATA_SOURCES.md` are never redistributed here.

## Reporting a problem

Open a GitHub issue for non-sensitive problems. For anything involving credentials or data you
believe should not be public, email the maintainer listed in `CITATION.cff` instead of filing a
public issue.
