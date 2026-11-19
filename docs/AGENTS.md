# Docs agent guide

Start with the [documentation index](README.md). Keep each instruction in the
guide that owns it. Use the existing guide and link to it from related pages.

- **Architecture and backend:** Read [the architecture](LOCAL_DEMO_IMPLEMENTATION.md)
  first, then the relevant code map, database, RAG, prompt, or security guide.
- **AWS deployment and rollback:** Use the [runbook](deploy/AWS_STATELESS_EC2.md)
  and [release checklist](PRODUCTION_RELEASE_CHECKLIST.md).
- **Tickets and domain terms:** Use [Contributing](CONTRIBUTING.md) and the
  [glossary](../GLOSSARY.md).
- **Interface design:** Use [React design](../frontend/DESIGN.md) or
  [Streamlit design](../DESIGN.md) for the surface being changed.

Update [implementation status](IMPLEMENTATION_STATUS.md) at the end of each
phase. Record changed behavior, validation evidence, compatibility and
rollback, unresolved risks, and the next exact action. Link to detailed
evidence where it belongs. Use the [testing guide](TESTING.md) when runtime
behavior changes. For documentation-only changes, verify links and any
commands or tools changed by the edit.
