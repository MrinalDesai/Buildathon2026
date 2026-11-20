#!/usr/bin/env bash
# Put FaultLens on Google Cloud Run. Run from the project folder.
#
#   PROJECT_ID=my-project ./deploy_gcp.sh            sign in to Gemini with an API key (default)
#   PROJECT_ID=my-project AUTH=vertex ./deploy_gcp.sh   sign in through Vertex AI, no key
#
# With AUTH=key the script reads GEMINI_API_KEY from the environment or from .env and stores it
# in Secret Manager. The key is never put in the image.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project id}"
REGION="${REGION:-asia-south1}"          # Mumbai
SERVICE="${SERVICE:-faultlens}"
AUTH="${AUTH:-key}"
AGENT_MODEL="${AGENT_MODEL:-gemini-3.8-flash}"
SECRET="faultlens-gemini-key"

echo "== Project $PROJECT_ID, region $REGION, service $SERVICE, sign-in: $AUTH, model: $AGENT_MODEL"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "== Turning on the Google Cloud services this needs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com aiplatform.googleapis.com

NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUN_ACCOUNT="${NUMBER}-compute@developer.gserviceaccount.com"

# One instance only: jobs in progress and the visitor limits are kept in memory.
COMMON=(--source . --region "$REGION" --allow-unauthenticated
        --min-instances 1 --max-instances 1 --concurrency 40
        --memory 2Gi --cpu 2 --timeout 600)

if [ "$AUTH" = "vertex" ]; then
  echo "== Letting the service call Gemini on Vertex AI"
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUN_ACCOUNT}" \
    --role roles/aiplatform.user --condition=None >/dev/null
  echo "== Building and deploying (first build takes several minutes)"
  gcloud run deploy "$SERVICE" "${COMMON[@]}" \
    --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION:-global},AGENT_MODEL=${AGENT_MODEL}"
else
  if [ -z "${GEMINI_API_KEY:-}" ] && [ -f .env ]; then
    GEMINI_API_KEY="$(grep -E '^GEMINI_API_KEY=' .env | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r')"
  fi
  : "${GEMINI_API_KEY:?Set GEMINI_API_KEY (or put it in .env)}"
  echo "== Storing the Gemini key in Secret Manager"
  if gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
    printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add "$SECRET" --data-file=- >/dev/null
  else
    printf '%s' "$GEMINI_API_KEY" | gcloud secrets create "$SECRET" --data-file=- >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "$SECRET" --member "serviceAccount:${RUN_ACCOUNT}" \
    --role roles/secretmanager.secretAccessor >/dev/null
  echo "== Building and deploying (first build takes several minutes)"
  gcloud run deploy "$SERVICE" "${COMMON[@]}" \
    --set-secrets "GEMINI_API_KEY=${SECRET}:latest" \
    --set-env-vars "AGENT_MODEL=${AGENT_MODEL}"
fi

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo
echo "== Live at: $URL"
