"""Provision / update the Galen serverless backend on AWS.

    AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
        python3 -m scripts.deploy_aws

Steps:
  1. upload galen_lambda.zip to S3 (multipart, retried — direct control-plane
     uploads from this network are flaky),
  2. create or update the ``galen-backend`` Lambda from that S3 object,
  3. push configuration (handler, env vars, DynamoDB backend),
  4. wire a {proxy+} API Gateway stage and print the public base URL.

Requires ``galen_lambda.zip`` — build it first with
``python3 -m scripts.build_lambda``.
"""
import json
import os
import sys
import time
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig

ROOT = Path(__file__).resolve().parent.parent
ZIPFILE = ROOT / "galen_lambda.zip"
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET = os.environ.get("GALEN_BUCKET", "pesaguard-deploy-c57beb15")
S3_KEY = "galen_lambda.zip"
FUNCTION = "galen-backend"
ROLE = "arn:aws:iam::454207980635:role/pesaguard-lambda-role"
API_NAME = "galen-api"
DYNAMO_TABLE = "galen-kb"

ENV_VARS = {
    "STORAGE_BACKEND": "dynamodb",
    "DYNAMO_TABLE": DYNAMO_TABLE,
    "LLM_MODEL": "qwen3.5-4b-32k-fast",
    "TTS_PROVIDER": "azure",
    "CORS_ORIGINS": "*",
}


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def api_key() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("ASSEMBLYAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("ASSEMBLYAI_API_KEY not found in .env")


def retry(fn, label: str, attempts: int = 20, delay: int = 8):
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            log(f"[{label} {i}/{attempts}] {type(exc).__name__}: {str(exc)[:130]}")
            if i == attempts:
                raise
            time.sleep(delay)


def upload_zip() -> None:
    size = ZIPFILE.stat().st_size
    log(f"uploading {size/1e6:.1f} MB to s3://{BUCKET}/{S3_KEY}")
    s3 = boto3.client("s3", region_name=REGION)
    cfg = TransferConfig(
        multipart_threshold=4 * 1024 * 1024,
        multipart_chunksize=4 * 1024 * 1024,
        max_concurrency=4,
    )
    retry(
        lambda: s3.upload_file(str(ZIPFILE), BUCKET, S3_KEY, Config=cfg),
        "s3-upload",
    )
    log("upload complete")


def function_arn() -> str:
    lam = boto3.client("lambda", region_name=REGION)
    return lam.get_function_configuration(FunctionName=FUNCTION)["FunctionArn"]


def deploy_lambda() -> str:
    lam = boto3.client("lambda", region_name=REGION)
    exists = True
    try:
        lam.get_function(FunctionName=FUNCTION)
    except lam.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        retry(lambda: lam.update_function_code(
            FunctionName=FUNCTION, S3Bucket=BUCKET, S3Key=S3_KEY, Publish=True,
        ), "update-code")
        log("lambda code updated")
        waiter = lam.get_waiter("function_updated_v2")
        waiter.wait(FunctionName=FUNCTION)
    else:
        retry(lambda: lam.create_function(
            FunctionName=FUNCTION, Runtime="python3.11", Role=ROLE,
            Handler="app.lambda_handler.handler",
            Code={"S3Bucket": BUCKET, "S3Key": S3_KEY},
            Timeout=60, MemorySize=1024,
        ), "create-function")
        log("lambda created")

    env = {**ENV_VARS, "ASSEMBLYAI_API_KEY": api_key()}
    retry(lambda: lam.update_function_configuration(
        FunctionName=FUNCTION,
        Handler="app.lambda_handler.handler",
        Runtime="python3.11",
        Timeout=60,
        MemorySize=1024,
        Environment={"Variables": env},
    ), "update-config")
    log("lambda configuration applied")

    # remove the throwaway function URL from the earlier connectivity probe
    try:
        lam.delete_function_url_config(FunctionName=FUNCTION)
    except Exception:  # noqa: BLE001
        pass
    return function_arn()


def find_or_create_api(apigw) -> str:
    for item in apigw.get_rest_apis().get("items", []):
        if item["name"] == API_NAME:
            return item["id"]
    api = apigw.create_rest_api(name=API_NAME, description="Galen voice knowledge bank backend")
    return api["id"]


def wire_api_gateway(fn_arn: str) -> str:
    apigw = boto3.client("apigateway", region_name=REGION)
    api_id = find_or_create_api(apigw)
    resources = apigw.get_resources(restApiId=api_id)["items"]
    root_id = next(r["id"] for r in resources if r["path"] == "/")

    proxy_id = next((r["id"] for r in resources if r.get("pathPart") == "{proxy+}"), None)
    if not proxy_id:
        proxy_id = apigw.create_resource(
            restApiId=api_id, parentId=root_id, pathPart="{proxy+}"
        )["id"]

    try:
        apigw.put_method(
            restApiId=api_id, resourceId=proxy_id, httpMethod="ANY",
            authorizationType="NONE",
            requestParameters={"method.request.path.proxy": True},
        )
    except apigw.exceptions.ConflictException:
        pass

    uri = (
        f"arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/"
        f"{fn_arn}/invocations"
    )
    apigw.put_integration(
        restApiId=api_id, resourceId=proxy_id, httpMethod="ANY",
        type="AWS_PROXY", integrationHttpMethod="POST", uri=uri,
    )

    account = fn_arn.split(":")[4]
    lam = boto3.client("lambda", region_name=REGION)
    try:
        lam.add_permission(
            FunctionName=FUNCTION, StatementId="apigateway-proxy",
            Action="lambda:InvokeFunction", Principal="apigateway.amazonaws.com",
            SourceArn=f"arn:aws:execute-api:{REGION}:{account}:{api_id}/*/*/*",
        )
    except lam.exceptions.ResourceConflictException:
        pass

    apigw.create_deployment(restApiId=api_id, stageName="prod")
    log("api gateway deployed (stage: prod)")
    return f"https://{api_id}.execute-api.{REGION}.amazonaws.com/prod"


def main() -> int:
    if not ZIPFILE.exists():
        raise SystemExit("galen_lambda.zip missing — run scripts.build_lambda first")
    upload_zip()
    fn_arn = deploy_lambda()
    base = wire_api_gateway(fn_arn)
    log(f"Galen backend base URL: {base}")
    print(json.dumps({"base_url": base, "function_arn": fn_arn}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
