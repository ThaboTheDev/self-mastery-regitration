# Self Mastery Programme — Registration Site

A public registration site for the **Self Mastery Programme** (MSR Learning Institute /
MSRI), styled after the [MSRI website](https://msri-website.vercel.app/) and designed to
feed registrants into the [PoP payments system](https://pop-system-lake.vercel.app/).

- **Programme code (`SP-MASTER`) and cohort code (`2026-S1`)** are applied in the
  background — registrants only see *“Self Mastery Programme”*.
- **Participant IDs** (e.g. `MSRI-004121`) are auto-generated on submission.
- **Pricing**: R500 once-off **or** R200/month × 3 (`amount_due` records what is due now).
- Mobile numbers are normalised to E.164 (`072 123 4567` → `+27721234567`).
- Duplicate emails are rejected (HTTP 409) so each person exists only once.
- Submissions are idempotent via an `Idempotency-Key` header (safe retries).

## Structure

```
frontend/            # Static site (HTML/CSS/JS) — host on S3+CloudFront, Netlify, Vercel…
  index.html         # Programme landing page
  register.html      # Registration form
  css/styles.css     # MSRI brand styles (navy #0b004b · gold #c89a30)
  js/config.js       # ← paste your deployed endpoint here
  js/register.js     # Form validation + submission
  assets/img/        # Logo, hero, programme imagery
backend/             # Python AWS Lambda + DynamoDB (AWS SAM)
  handler.py         # Registration API (validation, IDs, duplicates, storage)
  template.yaml      # SAM template — Lambda + Function URL + DynamoDB
  export_csv.py      # Export registrations to the PoP system CSV format
  tests/             # Unit tests (no AWS account needed)
```

## Data contract (PoP system import)

`export_csv.py` (and the stored DynamoDB records) match exactly:

```
participant_id,first_name,surname,email,mobile,programme_code,cohort_code,amount_due
MSRI-004120,Sipho,Dlamini,sipho@example.co.za,+27731234567,SP-MASTER,,200
```

- `amount_due` = **500** (once-off plan) or **200** (first monthly instalment).
- `cohort_code` = `2026-S1` for everyone (change via the SAM parameter).
- `mobile` is stored in international format for the PoP system.

## Run tests

```bash
cd backend
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## Deploy the backend (AWS SAM)

```bash
aws configure                      # once — needs an AWS account with admin access
cd backend
sam build
sam deploy --guided                # accept defaults; note the RegisterEndpoint output
```

Parameters you can set during `--guided` (defaults shown):

| Parameter | Default | Meaning |
|---|---|---|
| `ProgrammeCode` | `SP-MASTER` | Applied in the background |
| `CohortCode` | `2026-S1` | Applied in the background |
| `ParticipantIdPrefix` | `MSRI` | Prefix of generated IDs |
| `PriceOnceOff` / `PriceMonthly` | `500` / `200` | ZAR pricing |
| `MonthlyInstalments` | `3` | Instalment count |

## Connect the frontend

1. Copy the `RegisterEndpoint` output URL from the deploy.
2. Paste it into `frontend/js/config.js`:

```js
REGISTER_ENDPOINT: "https://xxxxxxxx.lambda-url.af-south-1.on.aws/",
```

While `REGISTER_ENDPOINT` is empty the site runs in **demo mode** — it validates and
shows a sample participant ID without saving anything.

3. Host `frontend/` anywhere static (Vercel / Netlify / S3 + CloudFront) and point the
   “MSRI Home” links wherever you like.

For a quick local preview of the site (demo mode):

```bash
cd frontend && python3 -m http.server 8080
# open http://localhost:8080
```

## Export registrations for the PoP system

```bash
cd backend
python export_csv.py --table sm-registrations-prod --region af-south-1 --output registrations.csv
# incremental:
python export_csv.py --start-after MSRI-004120 --output registrations-new.csv
```

## API reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/registrations` (or `/` on the Function URL) | Create a registration |
| `GET` | `/health` | Liveness + current programme config |
| `OPTIONS` | any | CORS preflight (handled automatically) |

Request body:

```json
{
  "first_name": "Thandi",
  "surname": "Nkosi",
  "email": "thandi@example.co.za",
  "mobile": "072 123 4567",
  "pricing_plan": "once_off"          // "once_off" | "monthly"
}
```

Responses: `201` created · `200` idempotent retry · `400` validation error ·
`409` duplicate email · `503` storage unavailable.

## Security notes

- The endpoint is public by design (registrations come from the open site). The Lambda
  validates and sanitises every field, caps sizes and never echoes internal errors.
- DynamoDB is encrypted at rest; access is limited to the registration function.
- To lock CORS down to your site, replace `AllowOrigins: ["*"]` in `template.yaml`
  with your domain and redeploy.
