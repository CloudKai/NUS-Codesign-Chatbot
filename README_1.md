# CDE2300 Design Thinking Coach 

## What's in scope vs deferred

**In scope now:** phase-specific prompts (5 DT stages), mixed Socratic+critique model
(switches to critique every 4 turns), image upload (sketches/posters via Bedrock vision),
per-student/per-project persistent history.

**Deliberately deferred:** Cognito auth (single shared demo for now), vector-search RAG
over course materials (framework text is pasted directly into prompts in `phases.py` --
add real retrieval once this loop is validated), DynamoDB (using local JSON file first;
storage.py has a commented DynamoDB variant ready to uncomment).

---

## Step 1 (5-10 min): One-time Anthropic model usage form

AWS retired the old "Model access" page in late 2025 -- serverless models are now
auto-enabled account-wide. Anthropic models still need a one-time usage-details form
before first use:

1. AWS Console -> Bedrock -> Model catalog -> pick a Claude model (e.g. Claude Sonnet) ->
   open it in the **Playground**.
2. Send a test prompt. If this is the account's first use of an Anthropic model, you'll
   be prompted to fill in the one-time usage form (use case description) -- submit it.
3. Once the playground responds successfully, copy the exact **model ID** shown on that
   model's catalog page (e.g. something like `anthropic.claude-sonnet-4-...`) -- paste it
   into the `MODEL_ID` env var below. Don't assume the ID in `main.py` is current; model
   IDs shift over time, so always copy the live one from the catalog.
4. Pick a region while you're there (us-east-1 or us-west-2 typically have the widest
   model availability) -- you'll reuse this in `AWS_REGION` below.

Separately, your Lambda execution role (Step 3) still needs an IAM policy allowing
`bedrock:InvokeModel` and `bedrock:Converse` on that model -- the auto-enablement above
doesn't replace that permission grant.

## Step 2 (15 min): Run it locally first

```bash
cd poc
python -m venv .venv
# PowerShell
.venv\Scripts\Activate.ps1
# Command Prompt
.venv\Scripts\activate
python -m pip install -r requirements.txt
set AWS_REGION=us-east-1        # match wherever you enabled model access
set MODEL_ID=anthropic.claude-haiku-4-5-20251001-v1:0
# make sure your AWS credentials are configured (aws configure, or env vars, or SSO)
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000 -- test all 5 phases, send >4 messages in one phase to see
critique mode kick in, try uploading an image. Fix anything broken *here* before touching
AWS deploy -- much faster debug loop than redeploying each time.

## Step 3 (45-60 min): Deploy to Lambda with a Function URL (no API Gateway needed)

This is the fastest real-AWS deploy path -- skips API Gateway config entirely.

```bash
# Package dependencies + code into a zip
mkdir package
# Activate your virtual environment first
.venv\Scripts\Activate.ps1      # PowerShell
# or
.venv\Scripts\activate          # Command Prompt
python -m pip install -r requirements.txt -t package/
cp main.py phases.py storage.py package/
cp -r static package/
cd package && zip -r ../lambda_deploy.zip . && cd ..
```

In the AWS Console:
1. Lambda -> Create function -> Python 3.12 runtime -> upload `lambda_deploy.zip`
2. Set handler to `main.handler`
3. Configuration -> Environment variables: add `AWS_REGION`, `MODEL_ID`
4. Configuration -> Permissions -> attach a policy allowing `bedrock:InvokeModel` and
   `bedrock:Converse` on the model you're using (a scoped inline policy is fine for POC)
5. Configuration -> Function URL -> Create -> Auth type: NONE for now (fine for a personal
   demo you control the link to; switch to AWS_IAM or add a shared-secret check before
   sharing the link with your team/professor)
6. Increase timeout to ~30s (Configuration -> General configuration) since Bedrock calls
   can take a few seconds

Hit the Function URL in a browser -- same UI as local.

**Known limitation to say out loud in your demo:** Lambda's `/tmp` (where the local JSON
store lives) is ephemeral per-instance, so history can reset on cold starts or if AWS
spins up a second concurrent instance. Fine for a live single-session walkthrough; swap in
the DynamoDB variant in `storage.py` (uncomment, create one table, ~30 min) before anyone
tests this unsupervised across multiple sessions.

## Step 4 (if time remains): Real retrieval over course materials

Replace the static `framework_context` strings in `phases.py` with retrieved chunks:
embed your actual (public-safe) CDE2300 materials with Bedrock Titan Embeddings, store
vectors as JSON in S3, do cosine similarity in Lambda at request time. No vector DB needed
at this scale -- skip OpenSearch Serverless, it has real minimum costs unsuited to a POC.