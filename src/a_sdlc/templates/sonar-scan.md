# /sdlc:sonar-scan - SonarQube Scan & Auto-Fix

Run a SonarQube analysis on the codebase and automatically fix issues based on configured severity thresholds.

## Prerequisites

- SonarQube configured: `a-sdlc sonarqube configure`
- pysonar installed: `uv tool install pysonar`
- `.sdlc/` directory must exist (run `/sdlc:init` first)

## Execution Steps

### Phase 1: Run Scan

Execute the SonarQube scanner on the project:

```bash
a-sdlc sonarqube scan
```

Wait for the scan to complete. If it fails, report the error and stop.

### Phase 2: Fetch Results

Retrieve analysis results and generate the code quality artifact:

```bash
a-sdlc sonarqube results
```

This creates `.sdlc/artifacts/code-quality.md` with quality gate status, metrics, and issues.

### Phase 3: Load Configuration

Read `.sdlc/config.yaml` to get the `fix_severities` setting:

```yaml
sonarqube:
  fix_severities:
    - BLOCKER
    - CRITICAL
    - MAJOR
```

Only issues matching these severity levels should be auto-fixed.

### Phase 4: Parse Issues

Read `.sdlc/artifacts/code-quality.md` and extract issues that match the configured severity threshold. Build a list of fixable issues ordered by severity (BLOCKER first, then CRITICAL, then MAJOR, etc.).

For each issue, collect:
- File path
- Line number
- Issue message
- Issue type (BUG, VULNERABILITY, CODE_SMELL)

### Phase 5: Confirm with User

Present the scan summary to the user and ask whether they want to proceed with auto-fixing:

- Show quality gate status, total issues found, and count matching the fix threshold
- List the fixable issues grouped by severity
- **Ask the user**: "Would you like me to start fixing these issues now, or stop here?"
- If the user declines or says "later", skip to Phase 8 and report the scan-only summary
- If `--scan-only` was passed, skip this prompt and go directly to Phase 8

### Phase 6: Fix Issues

For each fixable issue (in severity order):

1. **Read the file** at the specified path
2. **Understand the issue** based on its type and message:
   - **BUG**: Logic errors, null pointer dereferences, resource leaks
   - **VULNERABILITY**: SQL injection, XSS, hardcoded credentials, insecure crypto
   - **CODE_SMELL**: Unused variables, duplicate code, overly complex methods
3. **Apply the fix** using appropriate code changes
4. **Run existing tests** to verify no regression:
   ```bash
   # For Python projects
   pytest tests/ -x --tb=short

   # For Node projects
   npm test
   ```
5. **If tests fail**, revert the fix and note it as "could not auto-fix"

### Phase 7: Re-scan (Optional)

If fixes were applied, offer to re-run the scan to verify improvements:

```bash
a-sdlc sonarqube scan
a-sdlc sonarqube results
```

Compare before/after metrics.

### Phase 8: Summary

Report what was done:

```
SonarQube Scan & Fix Summary
=============================

Quality Gate: PASSED/FAILED
Issues Found: X (Y matching fix threshold)

Fixed:
  ✓ src/handler.py:45 - SQL injection vulnerability (CRITICAL)
  ✓ src/utils.py:12 - Unused import (MAJOR)

Could Not Fix:
  ✗ src/complex.py:100 - Cognitive complexity too high (MAJOR)
    Reason: Requires architectural refactoring

Remaining Issues: Z
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--scan-only` | Run scan without auto-fixing | false |
| `--severity <level>` | Override fix severity threshold | from config |
| `--dry-run` | Show what would be fixed without applying changes | false |

## Examples

```
/sdlc:sonar-scan                           # Full scan + auto-fix
/sdlc:sonar-scan --scan-only               # Scan without fixing
/sdlc:sonar-scan --severity CRITICAL       # Only fix CRITICAL+
/sdlc:sonar-scan --dry-run                 # Preview fixes
```

## Notes

- Token is passed as a CLI argument to pysonar
- The scanner creates a `.scannerwork/` directory (add to `.gitignore`)
- Auto-fix only modifies files for issues matching the configured severity threshold
- Each fix is verified with tests before moving to the next issue
- Issues requiring architectural changes are reported but not auto-fixed
