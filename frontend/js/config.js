/*
 * Self Mastery Programme — shared configuration.
 *
 * Set REGISTER_ENDPOINT to your deployed Lambda Function URL after running
 * `sam deploy` (see README.md). While it is empty the site runs in demo mode:
 * submissions are validated and a sample participant ID is shown without
 * contacting any server.
 */
window.SM_CONFIG = {
  // e.g. "https://abc123.lambda-url.af-south-1.on.aws/"
  REGISTER_ENDPOINT: "",

  // Shown on the site; the codes below are applied in the background.
  PROGRAMME_NAME: "Self Mastery Programme",
  PROGRAMME_CODE: "SP-MASTER",
  COHORT_CODE: "2026-S1",

  PRICING: {
    once_off: {
      label: "Once-off payment",
      amount: 500,
      instalments: 1,
      summary: "R500 once-off",
      note: "Pay once and be done — R100 less than the monthly plan.",
      badge: "Save R100",
    },
    monthly: {
      label: "Monthly plan",
      amount: 200,
      instalments: 3,
      summary: "R200 × 3 months",
      note: "Spread the cost — R200 per month for 3 months.",
      badge: "Most flexible",
    },
  },
};
