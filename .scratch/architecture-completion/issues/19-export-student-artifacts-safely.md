# 19: Export student artifacts safely

**What to build:** Export usable Markdown, plaintext and JSON with references, provenance and revision metadata; provide safe print output where useful.

**Blocked by:** 16: Manage course-aligned artifact types; 18: Preview and restore artifact versions.

**Status:** ready-for-agent

- [ ] A student exports the chosen artifact as meaningful Markdown, plaintext and canonical structured JSON with title, project/revision, references and required AI provenance.
- [ ] Exports and optional print-friendly rendering exclude hidden prompts, operational data and unapproved private sources; unsafe content/URLs remain inert.
- [ ] Owner checks, bounded output and restored-version content are verified through public download/browser behavior.
- [ ] Use the approved public testing seams and deterministic external adapters; for behavior changes demonstrate one red test then its minimal green implementation per cycle, with no speculative tests or code.
- [ ] Update affected guidance and the authoritative implementation ledger with executed evidence, compatibility/migration/rollback, risks and the next exact action; complete this ticket in one fresh writer session without staging, committing, deploying or paid calls.
