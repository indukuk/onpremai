#!/bin/bash
set -euo pipefail

# =============================================================================
# OnPremAI AWS Deployment Script
# =============================================================================
# Deploys the full infrastructure stack to AWS using Terraform, then builds
# and pushes Docker images to ECR.
#
# Usage:
#   ./deploy.sh [environment]
#   ./deploy.sh dev          # Deploy dev environment (default)
#   ./deploy.sh prod         # Deploy production environment
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="${SCRIPT_DIR}/infrastructure"
PROJECT="onpremai"
ENVIRONMENT="${1:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
STATE_BUCKET="${PROJECT}-terraform-state"
LOCK_TABLE="terraform-state-lock"

# Services to build and deploy
SERVICES=(
  "llm-gateway"
  "memory-service"
  "agent-eval"
  "compliance-assistant"
  "preprocessor"
  "observer"
  "sandbox-service"
)

# --- Color output helpers ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }

# =============================================================================
# Step 1: Check AWS Credentials
# =============================================================================
check_aws_credentials() {
  info "Checking AWS credentials..."

  if ! command -v aws &> /dev/null; then
    error "AWS CLI not found. Install it: https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html"
    exit 1
  fi

  if ! command -v terraform &> /dev/null; then
    error "Terraform not found. Install it: https://developer.hashicorp.com/terraform/downloads"
    exit 1
  fi

  if ! command -v docker &> /dev/null; then
    error "Docker not found. Install it: https://docs.docker.com/get-docker/"
    exit 1
  fi

  CALLER_IDENTITY=$(aws sts get-caller-identity --output json 2>&1) || {
    error "AWS credentials not configured or expired."
    error "Run: aws configure  OR  aws sso login"
    exit 1
  }

  ACCOUNT_ID=$(echo "$CALLER_IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Account'])")
  ARN=$(echo "$CALLER_IDENTITY" | python3 -c "import sys,json; print(json.load(sys.stdin)['Arn'])")

  ok "AWS credentials valid"
  info "  Account: ${ACCOUNT_ID}"
  info "  Identity: ${ARN}"
  info "  Region: ${AWS_REGION}"
  info "  Environment: ${ENVIRONMENT}"
  echo ""
}

# =============================================================================
# Step 2: Create S3 State Bucket + DynamoDB Lock Table (if not exist)
# =============================================================================
create_state_backend() {
  info "Checking Terraform state backend..."

  # Check if S3 bucket exists
  if aws s3api head-bucket --bucket "${STATE_BUCKET}" 2>/dev/null; then
    ok "State bucket '${STATE_BUCKET}' already exists"
  else
    info "Creating state bucket '${STATE_BUCKET}'..."
    aws s3api create-bucket \
      --bucket "${STATE_BUCKET}" \
      --region "${AWS_REGION}" \
      $([ "${AWS_REGION}" != "us-east-1" ] && echo "--create-bucket-configuration LocationConstraint=${AWS_REGION}")

    # Enable versioning
    aws s3api put-bucket-versioning \
      --bucket "${STATE_BUCKET}" \
      --versioning-configuration Status=Enabled

    # Enable encryption
    aws s3api put-bucket-encryption \
      --bucket "${STATE_BUCKET}" \
      --server-side-encryption-configuration '{
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"},"BucketKeyEnabled": true}]
      }'

    # Block public access
    aws s3api put-public-access-block \
      --bucket "${STATE_BUCKET}" \
      --public-access-block-configuration '{
        "BlockPublicAcls": true,
        "IgnorePublicAcls": true,
        "BlockPublicPolicy": true,
        "RestrictPublicBuckets": true
      }'

    ok "State bucket created and configured"
  fi

  # Check if DynamoDB lock table exists
  if aws dynamodb describe-table --table-name "${LOCK_TABLE}" --region "${AWS_REGION}" &>/dev/null; then
    ok "Lock table '${LOCK_TABLE}' already exists"
  else
    info "Creating DynamoDB lock table '${LOCK_TABLE}'..."
    aws dynamodb create-table \
      --table-name "${LOCK_TABLE}" \
      --attribute-definitions AttributeName=LockID,AttributeType=S \
      --key-schema AttributeName=LockID,KeyType=HASH \
      --billing-mode PAY_PER_REQUEST \
      --region "${AWS_REGION}" \
      --tags Key=Project,Value="${PROJECT}" Key=ManagedBy,Value=terraform

    # Wait for table to be active
    aws dynamodb wait table-exists --table-name "${LOCK_TABLE}" --region "${AWS_REGION}"
    ok "Lock table created"
  fi

  echo ""
}

# =============================================================================
# Step 3: Terraform Init
# =============================================================================
terraform_init() {
  info "Running terraform init..."
  cd "${INFRA_DIR}"

  terraform init \
    -backend-config="bucket=${STATE_BUCKET}" \
    -backend-config="key=infrastructure/terraform.tfstate" \
    -backend-config="region=${AWS_REGION}" \
    -backend-config="dynamodb_table=${LOCK_TABLE}" \
    -backend-config="encrypt=true"

  ok "Terraform initialized"
  echo ""
}

# =============================================================================
# Step 4: Terraform Plan
# =============================================================================
terraform_plan() {
  info "Running terraform plan..."
  cd "${INFRA_DIR}"

  terraform plan \
    -var-file="environments/${ENVIRONMENT}.tfvars" \
    -out=tfplan \
    -input=false

  ok "Terraform plan complete"
  echo ""
}

# =============================================================================
# Step 5: Terraform Apply
# =============================================================================
terraform_apply() {
  info "Applying Terraform changes (auto-approve for POC)..."
  cd "${INFRA_DIR}"

  terraform apply \
    -auto-approve \
    -input=false \
    tfplan

  ok "Terraform apply complete"
  echo ""
}

# =============================================================================
# Step 6: Build and Push Docker Images to ECR
# =============================================================================
build_and_push_images() {
  info "Building and pushing Docker images to ECR..."

  # Get ECR login
  ECR_REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
  aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

  IMAGE_TAG="${ENVIRONMENT}"

  for SERVICE in "${SERVICES[@]}"; do
    SERVICE_DIR="${SCRIPT_DIR}/${SERVICE}"
    ECR_REPO="${ECR_REGISTRY}/${PROJECT}/${SERVICE}"

    if [ ! -d "${SERVICE_DIR}" ]; then
      warn "Service directory '${SERVICE_DIR}' not found, skipping ${SERVICE}"
      continue
    fi

    if [ ! -f "${SERVICE_DIR}/Dockerfile" ]; then
      warn "No Dockerfile found for ${SERVICE}, skipping"
      continue
    fi

    info "Building ${SERVICE}..."
    docker build \
      --platform linux/amd64 \
      --provenance=false \
      -t "${ECR_REPO}:${IMAGE_TAG}" \
      -t "${ECR_REPO}:latest" \
      "${SERVICE_DIR}"

    info "Pushing ${SERVICE}..."
    docker push "${ECR_REPO}:${IMAGE_TAG}"
    docker push "${ECR_REPO}:latest"

    ok "Pushed ${SERVICE} -> ${ECR_REPO}:${IMAGE_TAG}"
  done

  echo ""
}

# =============================================================================
# Step 7: Output Results
# =============================================================================
output_results() {
  info "Deployment complete! Fetching outputs..."
  cd "${INFRA_DIR}"

  echo ""
  echo "============================================================================="
  echo "  DEPLOYMENT RESULTS - ${ENVIRONMENT}"
  echo "============================================================================="
  echo ""

  ALB_URL=$(terraform output -raw alb_url 2>/dev/null || echo "N/A")
  RDS_ENDPOINT=$(terraform output -raw rds_endpoint 2>/dev/null || echo "N/A")
  REDIS_ENDPOINT=$(terraform output -raw redis_endpoint 2>/dev/null || echo "N/A")
  COGNITO_POOL_ID=$(terraform output -raw cognito_user_pool_id 2>/dev/null || echo "N/A")
  COGNITO_CLIENT_ID=$(terraform output -raw cognito_client_id 2>/dev/null || echo "N/A")
  COGNITO_DOMAIN=$(terraform output -raw cognito_domain 2>/dev/null || echo "N/A")

  echo "  ALB URL:            ${ALB_URL}"
  echo "  RDS Endpoint:       ${RDS_ENDPOINT}"
  echo "  Redis Endpoint:     ${REDIS_ENDPOINT}"
  echo ""
  echo "  Cognito User Pool:  ${COGNITO_POOL_ID}"
  echo "  Cognito Client ID:  ${COGNITO_CLIENT_ID}"
  echo "  Cognito Domain:     ${COGNITO_DOMAIN}"
  echo ""
  echo "  ECR Registry:       ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${PROJECT}/"
  echo ""
  echo "============================================================================="
  echo ""
  echo "  Next steps:"
  echo "    1. Update secrets in AWS Secrets Manager (database password, API keys)"
  echo "    2. Run: CREATE EXTENSION IF NOT EXISTS vector; on the RDS instance"
  echo "    3. Create initial Cognito user:"
  echo "       aws cognito-idp admin-create-user \\"
  echo "         --user-pool-id ${COGNITO_POOL_ID} \\"
  echo "         --username admin@example.com \\"
  echo "         --user-attributes Name=email,Value=admin@example.com \\"
  echo "           Name=custom:tenant_id,Value=default \\"
  echo "           Name=custom:role,Value=admin"
  echo ""
  echo "============================================================================="
}

# =============================================================================
# Main Execution
# =============================================================================
main() {
  echo ""
  echo "============================================================================="
  echo "  OnPremAI AWS Deployment - ${ENVIRONMENT}"
  echo "============================================================================="
  echo ""

  # Validate environment
  if [[ "${ENVIRONMENT}" != "dev" && "${ENVIRONMENT}" != "staging" && "${ENVIRONMENT}" != "prod" ]]; then
    error "Invalid environment: ${ENVIRONMENT}. Must be one of: dev, staging, prod"
    exit 1
  fi

  # Warn on production deploy
  if [[ "${ENVIRONMENT}" == "prod" ]]; then
    warn "You are deploying to PRODUCTION!"
    warn "Press Ctrl+C within 5 seconds to abort..."
    sleep 5
  fi

  check_aws_credentials
  create_state_backend
  terraform_init
  terraform_plan
  terraform_apply
  build_and_push_images
  output_results

  ok "Deployment pipeline complete!"
}

main "$@"
