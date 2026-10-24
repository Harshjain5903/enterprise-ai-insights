# Running it on a schedule

The pipeline is a batch job, so it runs as a Cloud Run **job** (not a service)
triggered by Cloud Scheduler at 06:00 America/Chicago.

```bash
PROJECT=$GOOGLE_CLOUD_PROJECT
REGION=us-central1
SA=insights-runner@$PROJECT.iam.gserviceaccount.com

gcloud services enable run.googleapis.com cloudscheduler.googleapis.com \
  bigquery.googleapis.com aiplatform.googleapis.com artifactregistry.googleapis.com

# service account with only what the job needs
gcloud iam service-accounts create insights-runner
for role in roles/bigquery.jobUser roles/bigquery.dataEditor roles/aiplatform.user; do
  gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=$role
done
```

`bigquery.dataEditor` at project level is the lazy option; scoping it to the
three `enterprise_ai_insights_*` datasets is better once they exist.

```bash
gcloud run jobs deploy insights-daily \
  --source . --region $REGION --service-account $SA \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global \
  --set-secrets CUSTOMER_SALT=customer-salt:latest \
  --task-timeout 20m --max-retries 1

gcloud scheduler jobs create http insights-daily-0600 \
  --location $REGION --schedule "0 6 * * *" --time-zone "America/Chicago" \
  --uri "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/insights-daily:run" \
  --http-method POST --oauth-service-account-email $SA
```

The salt secret needs to exist first:

```bash
openssl rand -hex 32 | gcloud secrets create customer-salt --data-file=-
gcloud secrets add-iam-policy-binding customer-salt \
  --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
```

Reports written inside the container go to `/tmp/out` and disappear with it;
the durable record is `mart.report_snapshot`. Pushing the HTML to a bucket is
on the list.
