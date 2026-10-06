---
description: Write pytest tests for a module or function, following this service's testing rules
argument-hint: "<path or symbol to test>"
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(make test), Bash(./dev.ps1 test)
---

Write tests for: $ARGUMENTS

Follow the testing rules in `CLAUDE.md` and `AI_USAGE.md`:

1. Read the code under test and its existing tests first. Extend the existing test file for that module rather than creating a parallel one.
2. Cover the happy path, boundary values and error cases. Test behaviour through the public interface (HTTP endpoints via `TestClient`, or public functions), not private helpers.
3. One behaviour per test. Name tests `test_<unit>_<expected_behaviour>`.
4. No network, no real credentials, no sleeping. Use fake values that are obviously fake (for example `"test-token-not-real"`).
5. Never weaken an existing assertion or delete a test to make the suite pass. If you think existing behaviour is wrong, stop and say so.
6. Run the test suite (`make test` on Linux/macOS, `./dev.ps1 test` on Windows) and iterate until it passes, including the coverage threshold.

Finish with a list of the cases you covered and any behaviour you think is untested or suspicious.
