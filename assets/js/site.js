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

  /* ---------- Animated numbers ----------
     Counts headline stats up from zero the first time they scroll into view.
     Understands "$47,139", "267K+", "-87%", "1.55%", "+275". Anything that is
     not a single number (e.g. "FB + IG", "1 Year") is left untouched. The
     legacy homepage markup ("0+" with data-target="50") still works. */
  var counters = document.querySelectorAll('.stat-num, .metric-val, .case-metric-val, .case-card-stat-val, .cs-stat-val, [data-count]');
  if (counters.length) {
    var PREFIX_OK = /^[\s$+\-~−≈]*$/;
    var SUFFIX_OK = /^[\s+%KMBkmbx×]*$/;
    var parseStat = function (el) {
      var text = el.textContent.trim();
      var target = el.getAttribute('data-target');
      if (target !== null) {
        return { prefix: '', suffix: text.replace(/[\d,.]/g, ''), value: parseFloat(target), decimals: 0, comma: false };
      }
      var m = text.match(/^([^\d]*)(\d[\d,]*(?:\.\d+)?)([^\d]*)$/);
      if (!m || !PREFIX_OK.test(m[1]) || !SUFFIX_OK.test(m[3])) return null;
      var raw = m[2];
      var clean = raw.replace(/,/g, '');
      var value = parseFloat(clean);
      if (isNaN(value) || value < 5) return null;
      return {
        prefix: m[1], suffix: m[3], value: value,
        decimals: (clean.split('.')[1] || '').length,
        comma: raw.indexOf(',') !== -1
      };
    };
    var formatStat = function (p, v) {
      var s = v.toFixed(p.decimals);
      if (p.comma) {
        var parts = s.split('.');
        parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
        s = parts.join('.');
      }
      return p.prefix + s + p.suffix;
    };
    var finishStat = function (el) { el.textContent = formatStat(el._stat, el._stat.value); };
    var animateStat = function (el) {
      var p = el._stat, startTs = null, duration = 1400;
      var step = function (ts) {
        if (startTs === null) startTs = ts;
        var t = Math.min((ts - startTs) / duration, 1);
        var eased = 1 - Math.pow(1 - t, 4);
        el.textContent = formatStat(p, p.value * eased);
        if (t < 1) requestAnimationFrame(step); else finishStat(el);
      };
      requestAnimationFrame(step);
    };
    var statTargets = [];
    counters.forEach(function (el) {
      var p = parseStat(el);
      if (p) { el._stat = p; statTargets.push(el); }
    });
    if (reduceMotion.matches || !('IntersectionObserver' in window)) {
      statTargets.forEach(finishStat);
    } else {
      var statObserver = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          statObserver.unobserve(entry.target);
          animateStat(entry.target);
        });
      }, { threshold: 0.3 });
      statTargets.forEach(function (el) { statObserver.observe(el); });
    }
  }

  /* ---------- Video tiles ----------
     Case study videos show a poster frame with a play button; the Drive
     player is only loaded when someone asks for it. */
  document.querySelectorAll('.cs-video[data-src]').forEach(function (fig) {
    var btn = fig.querySelector('.cs-video-play');
    var frame = fig.querySelector('.cs-video-frame');
    if (!btn || !frame) return;
    btn.addEventListener('click', function () {
      var iframe = document.createElement('iframe');
      iframe.src = fig.getAttribute('data-src');
      iframe.setAttribute('allow', 'autoplay; fullscreen');
      iframe.setAttribute('allowfullscreen', '');
      iframe.title = btn.getAttribute('aria-label') || 'Video';
      frame.innerHTML = '';
      frame.appendChild(iframe);
    });
  });

  /* ---------- Lightbox for photo tiles ---------- */
  // Long photo/video grids start collapsed with a "Show all" button
  document.querySelectorAll('.cs-media, .cs-videos').forEach(function (grid) {
    var isVideo = grid.classList.contains('cs-videos');
    var items = grid.querySelectorAll(isVideo ? ':scope > figure' : ':scope > .cs-tile');
    var small = window.matchMedia('(max-width: 768px)').matches;
    var limit;
    if (isVideo) limit = grid.classList.contains('cs-videos--portrait') ? (small ? 4 : 5) : (small ? 2 : 3);
    else limit = grid.classList.contains('cs-media--wide') ? (small ? 3 : 6) : (small ? 6 : 10);
    if (items.length <= limit + 1) return; // collapse only when it hides at least two items
    grid.classList.add('is-collapsed');
    var btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'cs-more';
    btn.textContent = 'Show all ' + items.length + (isVideo ? ' videos' : ' photos');
    btn.addEventListener('click', function () { grid.classList.remove('is-collapsed'); btn.remove(); });
    grid.insertAdjacentElement('afterend', btn);
  });

  var tiles = document.querySelectorAll('a.cs-tile');
  if (tiles.length && typeof HTMLDialogElement === 'function') {
    var box = document.createElement('dialog');
    box.className = 'cs-lightbox';
    box.innerHTML = '<button class="cs-lightbox-close" type="button" aria-label="Close">×</button><img alt="">';
    document.body.appendChild(box);
    var boxImg = box.querySelector('img');
    box.querySelector('.cs-lightbox-close').addEventListener('click', function () { box.close(); });
    box.addEventListener('click', function (e) { if (e.target === box) box.close(); });
    box.addEventListener('close', function () { boxImg.removeAttribute('src'); });
    tiles.forEach(function (tile) {
      tile.addEventListener('click', function (e) {
        e.preventDefault();
        var img = tile.querySelector('img');
        boxImg.alt = img ? img.alt : '';
        boxImg.src = tile.getAttribute('href');
        box.showModal();
      });
    });
  }

  /* ---------- Cover image fallback ----------
     Cover photos are served from Google Drive. If one fails to load, drop it
     so the card or hero falls back to its designed logo-on-black state. */
  document.querySelectorAll('.case-card-media img, .case-hero-cover img, .cs-video-frame > img').forEach(function (img) {
    var drop = function () { if (img.parentNode) img.parentNode.removeChild(img); };
    if (img.complete && img.naturalWidth === 0 && img.getAttribute('src')) { drop(); return; }
    img.addEventListener('error', drop);
  });

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

  /* ---------- Homepage hero video ----------
     The poster <picture> paints first. After the page has loaded, the video
     gets a file sized for the screen (9:16 when the viewport is portrait) and
     fades in only once frames are playing, so a blocked autoplay (iOS Low
     Power Mode) just leaves the poster. Skipped for reduced motion and Data
     Saver. It pauses off screen and in background tabs, and the button stops
     it for the rest of the visit (WCAG 2.2.2). */
  var heroVideo = document.querySelector('.hero-video');
  var saveData = navigator.connection && navigator.connection.saveData;
  if (heroVideo && !saveData) {
    var videoToggle = document.querySelector('.hero-video-toggle');
    var portrait = window.matchMedia('(orientation: portrait)');
    var userPaused = false;
    var heroInView = true;
    var pickVideo = function () {
      if (portrait.matches) return heroVideo.getAttribute('data-src-portrait');
      var px = heroVideo.parentNode.clientWidth * (window.devicePixelRatio || 1);
      return heroVideo.getAttribute(px > 1400 ? 'data-src-1080' : 'data-src-720');
    };
    var syncVideo = function () {
      if (userPaused || !heroInView || document.hidden || reduceMotion.matches) {
        heroVideo.pause();
        return;
      }
      var playing = heroVideo.play();
      if (playing && playing.catch) playing.catch(function () {});
    };
    var loadVideo = function () {
      // Some Linux builds of Chromium and Firefox lack H.264: keep the poster, skip the download.
      if (reduceMotion.matches || !heroVideo.canPlayType('video/mp4; codecs="avc1.640028"')) return;
      var src = pickVideo();
      if (heroVideo.getAttribute('src') === src) return;
      heroVideo.classList.remove('is-playing');
      heroVideo.muted = true;
      heroVideo.src = src;
      syncVideo();
    };
    heroVideo.addEventListener('playing', function () {
      heroVideo.classList.add('is-playing');
      if (videoToggle) videoToggle.hidden = false;
    });
    if (videoToggle) {
      videoToggle.addEventListener('click', function () {
        userPaused = !userPaused;
        videoToggle.classList.toggle('is-paused', userPaused);
        videoToggle.setAttribute('aria-label', (userPaused ? 'Play' : 'Pause') + ' background video');
        syncVideo();
      });
    }
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (entries) {
        heroInView = entries[0].isIntersecting;
        syncVideo();
      }).observe(heroVideo.parentNode);
    }
    document.addEventListener('visibilitychange', syncVideo);
    if (portrait.addEventListener) {
      portrait.addEventListener('change', loadVideo);
      reduceMotion.addEventListener('change', function () { loadVideo(); syncVideo(); });
    }
    if (document.readyState === 'complete') loadVideo();
    else window.addEventListener('load', loadVideo);
  }
})();
