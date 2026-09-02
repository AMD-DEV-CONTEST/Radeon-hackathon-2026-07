# Technical design: Project showcase landing page

- Level: S1
- Status: implemented

## Implementation

- Build a dependency-free static HTML/CSS page at `showcase/index.html`.
- Use semantic sections with hash links for workflow, architecture, and proof.
- Use CSS-only terminal, workflow, and product-screen illustrations so the page remains portable and does not require image licensing or network access.
- Keep repository navigation as the only external link.

## Safety and privacy

- Do not render credentials, user data, filesystem paths, or API endpoints.
- Describe integrations as controlled and avoid claiming that GitHub/Jira writes are live.

## Rollback

Delete the `showcase/` directory; application behavior is unaffected.
