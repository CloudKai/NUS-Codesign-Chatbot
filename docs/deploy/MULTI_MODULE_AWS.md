# Isolated module deployments

`infra/foundation.yaml` deliberately creates no ECR repository. It contains
only the versioned private AgentCore artifact bucket and GitHub OIDC deployment
role. Each module stack is physically isolated and uses a fresh EC2 build from
an explicitly selected full Git commit.

## Safe operator sequence

1. Use `aws cloudformation validate-template` and a change set for
   `infra/foundation.yaml`, then deploy it in `us-west-2`.
2. Copy `infra/modules/cde2300.example.json` to an operator-controlled
   parameter file. Replace every placeholder with a reviewed value. The Git
   commit must be a 40-character SHA from the repository named by
   `GitRepositoryUrl`.
3. Publish the AgentCore ZIP at a versioned object key in the foundation
   artifact bucket. It must come from the same Git SHA as the EC2 build.
4. Create and inspect a change set for `infra/module-stack.yaml`. Supply the
   regional AWS-managed CloudFront origin-facing prefix-list ID; do not open
   port 80 to the internet and never add port 22.
5. Execute the stack only after the change set confirms retained DSQL and S3
   resources. EC2 fetches the Git deploy key and Cognito client secret only at
   runtime, with restrictive file permissions; neither is a stack output.
6. From an approved deployment environment, run
   `scripts/init_dsql.py --runtime-iam-role-arn <exact-module-ec2-role-arn>`.
   This is the only job that uses DbConnectAdmin. Do not run it from EC2
   startup.
7. Sync reviewed content only into the module course bucket under the configured
   prefix, generate metadata sidecars, then start and wait for KB ingestion.
   Never copy or enumerate `users/` keys or production DSQL application rows.

## Validation and rollback

No AWS account was contacted while adding these templates. Validate CloudFormation
resource schemas in the target account before deployment, then run the approved,
cost-capped live smoke. A rollback returns users to the old URL; retained module
data is not copied back and the old account is untouched.

`scripts/deploy_module_host.sh` is the EC2 entrypoint. It consumes the
stack-generated SSM contract, fetches only the Cognito secret, labels the local
Docker image with the checked-out commit, and runs `compose.prod.yaml`. It does
not pull an image from ECR.
