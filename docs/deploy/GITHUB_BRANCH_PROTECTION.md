# GitHub branch protection (manual Console steps)

Coding agents cannot reliably change repository settings. Before student
cutover, configure GitHub for the production branch
(`Production-RemoveData` or the eventual default production branch):

1. Open **Settings → Branches → Add branch protection rule**.
2. Require a pull request before merging.
3. Require status checks to pass, including **Mock CI** / `mock-suite`.
4. Do not allow bypassing required checks for administrators during cutover.
5. Require branches to be up to date before merging when practical.
6. Restrict force pushes.
7. Restrict branch deletion.
8. Keep secrets (Cognito client secret, host `.env`) out of the repository;
   use EC2 host files / GitHub Actions secrets only where needed for non-prod
   automation.

PR CI must remain mock-only: no Cognito, DSQL, S3, OpenAI, or Bedrock live
calls. Live AWS smoke remains a separate manual gate documented in
`docs/deploy/AWS_STATELESS_EC2.md`.
