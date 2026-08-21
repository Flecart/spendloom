# Repository style guide

Keep production code easy to review and change.

- Format TypeScript and TSX with one declaration or statement per line; do not
  compress component state, handlers, or JSX into dense one-liners.
- Give page/component props and non-trivial callback inputs explicit types.
- Keep page components focused on orchestration. Extract repeated or substantial
  UI sections into named components or clearly named render variables.
- Prefer small, named helpers for parsing, validation, and transformations over
  deeply nested inline expressions.
- Keep API boundaries explicit: validate request data on the server, return
  actionable errors, and do not trust client-provided filesystem data.
- Preserve existing behavior when refactoring, and add focused tests for new
  API behavior and error cases.
- Before handing off, run the relevant Python tests and the frontend build or
  type check. Mention any environment-caused verification limitation.
