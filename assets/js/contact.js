/* THE STOOP — contact page inquiry form
   GoHighLevel's External Tracking script (loaded on every page) captures this
   form's native submit event and creates the contact in GHL. This script only:
   - validates with the browser's own constraint validation, so an invalid form
     never fires a submit event (and never reaches GHL), and shows inline messages;
   - pre-selects the service from ?service=<slug> and reveals the "Other" boxes;
   - refuses to submit if GHL's script didn't load (e.g. an ad blocker), showing
     the email/phone fallback instead of silently losing the lead;
   - after a submit, waits for GHL's request, then redirects to the thank-you
     page for the chosen service (each fires the GA4 generate_lead event).
   The GHL <script> tag sets window.stoopTracker to 'loaded' or 'failed'. */
(function () {
  'use strict';

  var form = document.getElementById('inquiry-form');
  if (!form) return;

  var THANK_YOU = {
    'influencer-marketing': 1, 'digital-advertising': 1, 'organic-social': 1,
    'content-development': 1, 'design-branding': 1, 'website-design': 1,
    'automation-ops': 1, 'influencer-coaching': 1
  };
  var MISSING = {
    first_name: 'Please enter your first name.',
    last_name: 'Please enter your last name.',
    email: 'Please enter your email.',
    phone: 'Please enter your phone number.',
    service: 'Please choose a service.'
  };
  var FALLBACK = 'We couldn\'t connect to our form system (an ad or tracking blocker ' +
    'can cause this). Please email <a href="mailto:mike@thestooppgh.com">mike@thestooppgh.com</a> ' +
    'or call <a href="tel:+14126160542">(412) 616-0542</a> and we\'ll get right back to you.';

  var status = document.getElementById('form-status');
  var submit = form.querySelector('[type="submit"]');
  var service = form.elements.service;
  var howFound = form.elements.how_found;
  var attempted = false;
  var clickedAt = 0;

  function slugOf(select) {
    var option = select.options[select.selectedIndex];
    return option ? option.getAttribute('data-slug') || '' : '';
  }

  /* ---------- Pre-select the service from ?service= ---------- */
  var wanted = new URLSearchParams(window.location.search).get('service');
  if (wanted && /^[a-z-]+$/.test(wanted)) {
    var match = service.querySelector('option[data-slug="' + wanted + '"]');
    if (match) match.selected = true;
  }

  /* ---------- "Other" boxes ---------- */
  function syncOther(select) {
    var wrap = form.querySelector('[data-other-for="' + select.name + '"]');
    if (!wrap) return;
    var show = slugOf(select) === 'other';
    wrap.classList.toggle('is-shown', show);
    if (!show) wrap.querySelector('input').value = '';
  }
  [service, howFound].forEach(function (select) {
    syncOther(select);
    select.addEventListener('change', function () { syncOther(select); });
  });

  /* ---------- Validation (native, with our own messages) ---------- */
  function extraChecks() {
    var email = form.elements.email, phone = form.elements.phone;
    var e = email.value.trim(), digits = phone.value.replace(/\D/g, '').length;
    email.setCustomValidity(e && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(e) ? 'Please enter a valid email address.' : '');
    phone.setCustomValidity(phone.value.trim() && (digits < 10 || digits > 15) ? 'Please enter a valid phone number.' : '');
  }

  function render(field) {
    var error = document.getElementById(field.name + '-error');
    if (!error) return;
    var message = '';
    if (!field.validity.valid) {
      message = field.validity.valueMissing ? MISSING[field.name] : field.validationMessage;
      if (field.validity.typeMismatch) message = 'Please enter a valid email address.';
    }
    field.setAttribute('aria-invalid', message ? 'true' : 'false');
    error.textContent = message;
  }

  Object.keys(MISSING).forEach(function (name) {
    var field = form.elements[name];
    field.addEventListener(field.tagName === 'SELECT' ? 'change' : 'input', function () {
      extraChecks();
      if (attempted) render(field);
    });
  });

  // Fired by the browser for each invalid field when a submit is attempted.
  // Cancelling it hides the browser's bubble; we show our message instead.
  var focusQueued = false;
  form.addEventListener('invalid', function (e) {
    e.preventDefault();
    attempted = true;
    render(e.target);
    if (!focusQueued) {
      focusQueued = true;
      var target = e.target;
      setTimeout(function () { target.focus(); focusQueued = false; }, 0);
    }
  }, true);

  function fail() {
    submit.disabled = false;
    submit.textContent = 'Send Inquiry';
    status.innerHTML = FALLBACK;
    status.hidden = false;
  }

  function trackerReady(done) {
    if (window.stoopTracker === 'loaded') return done(true);
    if (window.stoopTracker === 'failed') return done(false);
    var waited = 0;
    var poll = setInterval(function () {
      waited += 200;
      if (window.stoopTracker === 'loaded' || window.stoopTracker === 'failed' || waited >= 4000) {
        clearInterval(poll);
        done(window.stoopTracker === 'loaded');
      }
    }, 200);
  }

  /* ---------- Before the submit event: spam trap + tracker check ---------- */
  // Runs on the button click (Enter in a field also "clicks" it). Invalid forms
  // are left alone: the browser fires 'invalid' events and no submit happens.
  submit.addEventListener('click', function (e) {
    extraChecks();
    status.hidden = true;
    if (form.elements.stoop_hp.value) { e.preventDefault(); return; }
    var valid = Array.prototype.every.call(form.elements, function (el) {
      return !el.willValidate || el.validity.valid;
    });
    if (!valid) return;
    clickedAt = performance.now();
    if (window.stoopTracker === 'loaded') return; // let the native submit happen
    e.preventDefault();
    submit.disabled = true;
    submit.textContent = 'Sending…';
    trackerReady(function (ok) {
      if (!ok) { fail(); return; }
      submit.disabled = false;
      clickedAt = performance.now();
      form.requestSubmit ? form.requestSubmit(submit) : submit.click();
    });
  });

  /* ---------- After the submit event: wait for GHL, then thank-you ---------- */
  // Listening on window (bubble phase) so GHL's own submit listeners run first.
  window.addEventListener('submit', function (e) {
    if (e.target !== form) return;
    e.preventDefault(); // stay on the page; GitHub Pages can't accept a form POST
    var slug = slugOf(service);
    var next = '/services/thank-you/' + (THANK_YOU[slug] ? slug : 'contact') + '.html';
    var since = (clickedAt || performance.now()) - 50;
    submit.disabled = true;
    submit.textContent = 'Sending…';

    var finished = false, observer = null;
    var go = function () {
      if (finished) return;
      finished = true;
      if (observer) observer.disconnect();
      window.location.assign(next);
    };
    setTimeout(go, 2500); // upper bound if GHL's request can't be observed
    if ('PerformanceObserver' in window) {
      observer = new PerformanceObserver(function (list) {
        list.getEntries().forEach(function (entry) {
          if (entry.startTime >= since && entry.initiatorType !== 'script' &&
              /external-tracking/.test(entry.name)) {
            setTimeout(go, 150);
          }
        });
      });
      try { observer.observe({ type: 'resource', buffered: true }); } catch (err) { observer = null; }
    }
  });
})();
