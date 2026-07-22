/* THE STOOP — shared site behavior (deferred on every page)
   The <html> element gets a .js class from an inline snippet in <head>;
   reveal-hiding CSS is scoped to html.js so content is never stuck hidden. */
(function () {
  'use strict';

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  var desktop = window.matchMedia('(min-width: 769px)');

  /* ---------- Reveal on scroll ---------- */
  var reveals = document.querySelectorAll('.reveal');
  if (reveals.length) {
    if ('IntersectionObserver' in window) {
      var revealObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry, i) {
          if (entry.isIntersecting) {
            setTimeout(function () { entry.target.classList.add('visible'); }, i * 100);
            revealObserver.unobserve(entry.target);
          }
        });
      }, { threshold: 0.1 });
      reveals.forEach(function (el) { revealObserver.observe(el); });
    } else {
      reveals.forEach(function (el) { el.classList.add('visible'); });
    }
  }

  /* ---------- Stat counters ---------- */
  var statNums = document.querySelectorAll('.stat-num[data-target]');
  if (statNums.length) {
    var finishStat = function (num) {
      var target = parseInt(num.dataset.target, 10);
      var suffix = num.textContent.replace(/[0-9]/g, '');
      num.textContent = target + suffix;
    };
    if (reduceMotion.matches || !('IntersectionObserver' in window)) {
      statNums.forEach(finishStat);
    } else {
      var statObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var num = entry.target;
          var target = parseInt(num.dataset.target, 10);
          var suffix = num.textContent.replace(/[0-9]/g, '');
          var current = 0;
          var step = Math.ceil(target / 40);
          var timer = setInterval(function () {
            current += step;
            if (current >= target) { current = target; clearInterval(timer); }
            num.textContent = current + suffix;
          }, 30);
          statObserver.unobserve(num);
        });
      }, { threshold: 0.3 });
      statNums.forEach(function (el) { statObserver.observe(el); });
    }
  }

  /* ---------- Parallax (JS fallback) ----------
     Browsers with CSS scroll-driven animation support run parallax on the
     compositor via site.css; the scroll handler is only wired up elsewhere. */
  var supportsScrollTimeline =
    typeof CSS !== 'undefined' && CSS.supports && CSS.supports('animation-timeline: view()');

  if (!supportsScrollTimeline) {
    var heroBgText = document.querySelector('.hero-bg-text');
    var caseHeroBg = document.querySelector('.case-hero-bg');
    var ctaBg = document.querySelector('.cta-bg');
    var trackNumbers = document.querySelectorAll('.track-number');
    var serviceNums = document.querySelectorAll('.service-num');
    var hasTargets = heroBgText || caseHeroBg || ctaBg || trackNumbers.length || serviceNums.length;

    if (hasTargets) {
      var parallaxOn = function () { return desktop.matches && !reduceMotion.matches; };
      var clearParallax = function () {
        [heroBgText, caseHeroBg, ctaBg].forEach(function (el) {
          if (el) el.style.transform = '';
        });
        trackNumbers.forEach(function (el) { el.style.transform = ''; });
        serviceNums.forEach(function (el) { el.style.transform = ''; });
      };
      var ticking = false;
      var onScroll = function () {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(function () {
          if (!parallaxOn()) { ticking = false; return; }
          var scrollY = window.scrollY;
          var vh = window.innerHeight;

          if (heroBgText) {
            heroBgText.style.transform = 'translate(-50%, calc(-50% + ' + (scrollY * 0.3) + 'px))';
          }
          if (caseHeroBg) {
            caseHeroBg.style.transform = 'translate(-50%, calc(-50% + ' + (scrollY * 0.4) + 'px))';
          }
          if (ctaBg) {
            var ctaRect = ctaBg.parentElement.getBoundingClientRect();
            if (ctaRect.top < vh && ctaRect.bottom > 0) {
              ctaBg.style.transform = 'translateX(-50%) translateY(' + ((ctaRect.top - vh) * 0.15) + 'px)';
            }
          }
          trackNumbers.forEach(function (num) {
            var rect = num.parentElement.getBoundingClientRect();
            if (rect.top < vh && rect.bottom > 0) {
              num.style.transform = 'translateY(' + ((rect.top - vh * 0.5) * 0.1) + 'px)';
            }
          });
          serviceNums.forEach(function (num) {
            var rect = num.parentElement.getBoundingClientRect();
            if (rect.top < vh && rect.bottom > 0) {
              num.style.transform = 'translateY(' + ((rect.top - vh * 0.5) * 0.08) + 'px)';
            }
          });
          ticking = false;
        });
      };
      window.addEventListener('scroll', onScroll, { passive: true });
      var onGateChange = function () {
        if (!parallaxOn()) clearParallax(); else onScroll();
      };
      if (desktop.addEventListener) {
        desktop.addEventListener('change', onGateChange);
        reduceMotion.addEventListener('change', onGateChange);
      }
      if (parallaxOn()) onScroll();
    }
  }

  /* ---------- Mobile menu ---------- */
  var menuToggle = document.querySelector('.menu-toggle');
  var navLinks = document.querySelector('.nav-links');
  if (menuToggle && navLinks) {
    if (!navLinks.id) navLinks.id = 'site-nav-links';
    menuToggle.setAttribute('aria-controls', navLinks.id);
    menuToggle.setAttribute('aria-expanded', 'false');
    var setMenu = function (open) {
      navLinks.classList.toggle('open', open);
      menuToggle.classList.toggle('active', open);
      menuToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      document.body.classList.toggle('nav-open', open);
    };
    menuToggle.addEventListener('click', function () {
      setMenu(!navLinks.classList.contains('open'));
    });
    navLinks.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () { setMenu(false); });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && navLinks.classList.contains('open')) {
        setMenu(false);
        menuToggle.focus();
      }
    });
  }
})();
