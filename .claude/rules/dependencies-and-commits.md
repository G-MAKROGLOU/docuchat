# Dependencies and commits

## Dependencies
- Pin exact versions: `==` in `backend/pyproject.toml`, no `^` or `~` in `frontend/package.json`.
- Pin Docker images and GitHub Actions to exact tags.
- Check the current version and setup syntax in the official documentation before you change configuration.
- Use LangChain 1.x and LangGraph 1.x APIs only. Do not use legacy chains.

## Naming
- Use neutral names only. No client or company name in repository names, descriptions, package names, commit messages or code comments.

## Commits
- One concern for each commit.
- Use Conventional Commits: `feat`, `fix`, `chore`, `build`, `ci`, `docs`, `test`, `refactor`.
