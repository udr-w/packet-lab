# Security Policy

## Supported Versions

Packet Lab is currently under active development.

Security fixes are applied to the latest version on the `main` branch. Older
commits, forks, and archived versions are not actively supported.

## Reporting a Vulnerability

Please do not report security vulnerabilities through public GitHub issues,
pull requests, or discussions.

Use GitHub's private vulnerability reporting feature for this repository:

1. Open the repository's **Security and quality** tab.
2. Select **Report a vulnerability**.
3. Include:
   - a description of the vulnerability
   - affected files or components
   - steps to reproduce it
   - potential impact
   - any suggested mitigation, if known

Please avoid including real credentials, private packet captures, personal
information, or unrelated system data.

Reports will be reviewed on a best-effort basis. Confirmed vulnerabilities may
be handled through a private GitHub security advisory until a fix is available.

## Scope

Security-relevant areas include:

- generated-tool validation and execution
- command and filesystem policy enforcement
- learner-state isolation
- trace integrity
- path traversal or symlink escapes
- prompt injection through command output, files, or packet data
- secret or sensitive-data exposure
- resource-limit bypasses

The restricted runner reduces risk but is not an operating-system sandbox.
Known limitations are documented in the repository README and threat model.
