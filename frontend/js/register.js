/*
 * Self Mastery Programme — registration form logic.
 * Validates input client-side, POSTs to the Lambda registration endpoint and
 * renders the participant ID on success.
 *
 * programme_code (SP-MASTER) and cohort_code (2026-S1) are applied in the
 * background by the backend — the registrant only sees "Self Mastery Programme".
 */
(function () {
  "use strict";

  var cfg = window.SM_CONFIG || {};
  var PRICING = cfg.PRICING || {
    once_off: { amount: 500, instalments: 1 },
    monthly: { amount: 200, instalments: 3 },
  };

  var form = document.getElementById("reg-form");
  var alertBox = document.getElementById("form-alert");
  var submitBtn = document.getElementById("submit-btn");
  var successPanel = document.getElementById("success-panel");
  var demoBanner = document.getElementById("demo-banner");

  var isDemo = !cfg.REGISTER_ENDPOINT;
  if (isDemo) demoBanner.classList.add("visible");
  function $(sel) { return form.querySelector(sel); }

  function fieldWrap(name) {
    return document.getElementById("field-" + name) || null;
  }

  function setFieldError(name, message) {
    var wrap = fieldWrap(name);
    if (!wrap) return;
    wrap.classList.add("has-error");
    var msg = wrap.querySelector(".field-msg");
    if (msg && message) msg.textContent = message;
  }

  function clearFieldError(name) {
    var wrap = fieldWrap(name);
    if (!wrap) return;
    wrap.classList.remove("has-error");
    var msg = wrap.querySelector(".field-msg");
    if (msg) msg.textContent = "";
  }

  function showError(message) {
    alertBox.textContent = message;
    alertBox.classList.add("visible");
    alertBox.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function hideError() {
    alertBox.classList.remove("visible");
  }

  function validName(value) {
    return value.trim().length >= 2 && !/[\d!@#$%^&*()_+=\[\]{};:"\\|<>/?~`]/.test(value);
  }

  function validEmail(value) {
    return /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/.test(value.trim());
  }

  function validMobile(value) {
    var digits = value.replace(/[^\d+]/g, "");
    var rest = digits.charAt(0) === "+" ? digits.slice(1) : digits.replace(/^0/, "27").replace(/^\+/, "");
    return /^\d{7,15}$/.test(rest);
  }

  function money(n) {
    return "R" + Number(n).toLocaleString("en-ZA");
  }

  // Idempotency key: stable across retries of the same submission.
  var idemKey = null;
  function newIdemKey() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "idem-" + Date.now() + "-" + Math.random().toString(36).slice(2, 10);
  }
  idemKey = newIdemKey();

  // ---------- preselect plan from URL (?plan=monthly) ------------------
  var params = new URLSearchParams(window.location.search);
  var planParam = (params.get("plan") || "").replace(/[^a-z_]/gi, "");
  var planInput = form.querySelector('input[name="pricing_plan"][value="' + planParam + '"]');
  if (planInput) planInput.checked = true;

  // ---------- live validation ------------------------------------------
  ["first_name", "surname", "email", "mobile"].forEach(function (name) {
    var input = form.elements[name];
    input.addEventListener("blur", function () {
      if (!input.value.trim()) return;
      clearFieldError(name);
      var ok =
        (name === "email") ? validEmail(input.value) :
        (name === "mobile") ? validMobile(input.value) :
        validName(input.value);
      if (!ok) {
        var messages = {
          first_name: "Please enter your first name (letters only).",
          surname: "Please enter your surname (letters only).",
          email: "Enter a valid email address.",
          mobile: "Enter a valid mobile number, e.g. 072 123 4567.",
        };
        setFieldError(name, messages[name]);
      }
    });
    input.addEventListener("input", function () { clearFieldError(name); });
  });

  // ---------- client-side validation on submit --------------------------
  function validate() {
    var firstError = null;
    ["first_name", "surname", "email", "mobile", "consent", "pricing_plan"].forEach(clearFieldError);

    var plan = form.querySelector('input[name="pricing_plan"]:checked');
    if (!plan) {
      setFieldError("pricing_plan", "Please choose a payment plan.");
      firstError = firstError || "Please choose a payment plan.";
    }

    var firstName = form.elements.first_name.value.trim();
    if (!validName(firstName)) {
      setFieldError("first_name", firstName ? "Letters only, at least 2 characters." : "First name is required.");
      firstError = firstError || "Please enter your first name.";
    }

    var surname = form.elements.surname.value.trim();
    if (!validName(surname)) {
      setFieldError("surname", surname ? "Letters only, at least 2 characters." : "Surname is required.");
      firstError = firstError || "Please enter your surname.";
    }

    var email = form.elements.email.value.trim();
    if (!validEmail(email)) {
      setFieldError("email", "Enter a valid email address.");
      firstError = firstError || "Please enter a valid email address.";
    }

    var mobile = form.elements.mobile.value.trim();
    if (!validMobile(mobile)) {
      setFieldError("mobile", "Enter a valid mobile number, e.g. 072 123 4567.");
      firstError = firstError || "Please enter a valid mobile number.";
    }

    var consent = document.getElementById("consent");
    if (!consent.checked) {
      setFieldError("consent", "POPIA consent is required to register.");
      firstError = firstError || "Please accept the POPIA consent to continue.";
    }

    if (firstError) {
      showError(firstError);
      return null;
    }
    hideError();
    return {
      first_name: firstName,
      surname: surname,
      email: email,
      mobile: mobile,
      pricing_plan: plan.value,
    };
  }

  // ---------- success rendering -----------------------------------------
  function showSuccess(data, alreadyRegistered) {
    form.style.display = "none";
    successPanel.classList.add("visible");

    document.getElementById("already-banner").style.display = alreadyRegistered ? "inline-block" : "none";
    document.getElementById("success-title").textContent = alreadyRegistered
      ? "You're already registered!"
      : "Welcome, " + (data.first_name || "champ") + "!";
    document.getElementById("success-sub").textContent = alreadyRegistered
      ? "This email address is already on the " + (cfg.PROGRAMME_NAME || "Self Mastery Programme") + " register. Your details are below."
      : "Your registration for the " + (cfg.PROGRAMME_NAME || "Self Mastery Programme") + " has been received.";

    var pid = data.participant_id || "PENDING";
    document.getElementById("participant-id").textContent = pid;

    var plan = data.pricing_plan || null;
    var planInfo = plan ? PRICING[plan] : null;
    var amountText = plan === "monthly"
      ? money(planInfo.amount) + "/month × " + (planInfo.instalments || 3)
      : plan === "once_off"
        ? money(planInfo.amount) + " once-off"
        : "";

    var meta = document.getElementById("success-meta");
    meta.innerHTML =
      "<strong>" + (cfg.PROGRAMME_NAME || "Self Mastery Programme") + "</strong>" +
      (amountText ? " · Amount due: <strong>" + amountText + "</strong>" : "") +
      " · Registered: " + (data.email || form.elements.email.value.trim() || "");

    document.getElementById("copy-btn").textContent = "Copy ID";
    successPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------- copy button ------------------------------------------------
  document.getElementById("copy-btn").addEventListener("click", function () {
    var pid = document.getElementById("participant-id").textContent;
    var btn = this;
    function done() { btn.textContent = "Copied ✓"; setTimeout(function () { btn.textContent = "Copy ID"; }, 2200); }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(pid).then(done, done);
    } else {
      var ta = document.createElement("textarea");
      ta.value = pid;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (e) { /* noop */ }
      document.body.removeChild(ta);
      done();
    }
  });

  // ---------- register another person -------------------------------------
  document.getElementById("again-btn").addEventListener("click", function () {
    form.reset();
    idemKey = newIdemKey();
    successPanel.classList.remove("visible");
    form.style.display = "";
    hideError();
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  // ---------- submit -------------------------------------------------------
  function setBusy(busy) {
    submitBtn.disabled = busy;
    submitBtn.textContent = busy ? "Submitting…" : "Complete Registration →";
  }

  function handleResult(payload, status) {
    if (status === 201 || status === 200) {
      showSuccess(payload, false);
      return;
    }
    if (status === 409) {
      showSuccess(
        { participant_id: payload.participant_id, first_name: payload.first_name },
        true
      );
      return;
    }
    if (status === 400 && payload && payload.details) {
      payload.details.forEach(function (d) { setFieldError(d.field, d.message); });
      showError("Please fix the highlighted fields and try again.");
      return;
    }
    var msg = (payload && payload.message) ? payload.message :
      "Something went wrong while saving your registration. Please try again in a moment.";
    showError(msg);
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var payload = validate();
    if (!payload) return;

    setBusy(true);

    if (isDemo) {
      // Demo mode — simulate a successful registration.
      setTimeout(function () {
        setBusy(false);
        var num = String(Math.floor(100000 + Math.random() * 899999));
        showSuccess({ participant_id: (cfg.PROGRAMME_CODE === "SP-MASTER" ? "MSRI" : "SM") + "-" + num, first_name: payload.first_name, pricing_plan: payload.pricing_plan }, false);
      }, 900);
      return;
    }

    fetch(cfg.REGISTER_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idemKey,
      },
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          handleResult(body, res.status);
        });
      })
      .catch(function () {
        showError(
          "We couldn't reach the registration server. Please check your connection " +
          "and try again — if it keeps failing, contact the institute."
        );
      })
      .then(function () { setBusy(false); });
  });
})();
