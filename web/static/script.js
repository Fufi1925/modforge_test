/**
 * ModForge — script.js v3.0
 * Ultra Modern · Three.js 3D World · Glassmorphism · Cyber Security Aesthetic
 */

/* ═══════════════════════════════════════════════════════════
   BOOTSTRAP — Load Three.js then init everything
   ═══════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── Inject Three.js mit Offline-Fallback ──────────────────
  function loadScript(src, cb) {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      cb();
    };
    const s = document.createElement('script');
    s.src = src;
    s.async = true;
    s.onload = finish;
    s.onerror = finish;
    document.head.appendChild(s);
    // Wenn CDN/Netz blockiert ist, darf die Seite trotzdem starten.
    window.setTimeout(finish, 1800);
  }

  let booted = false;
  function init() {
    if (booted) return;
    booted = true;
    const start = () => {
      setupAmbientFallback();
      setupCustomCursor();
      setup3DScene();
      setupNavbar();
      setupScrollReveal();
      setupFeatureCards();
      setupCounters();
      setupDashboardPreview();
      setupLogChannelHovers();
      setupCommandCards();
      setupMicroInteractions();
      setupSmartClipboard();
    };
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', start, { once: true });
    } else {
      start();
    }
  }

  if (window.THREE) init();
  else loadScript('https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js', init);

  function setupAmbientFallback() {
    if (document.querySelector('.mf-ambient')) return;
    const ambient = document.createElement('div');
    ambient.className = 'mf-ambient';
    ambient.setAttribute('aria-hidden', 'true');
    ambient.innerHTML = '<span></span><span></span><span></span><i></i>';
    document.body.prepend(ambient);
  }

  /* ═══════════════════════════════════════════════════════
     CUSTOM CURSOR – Großer Farbfleck, 100% zentriert
     ═══════════════════════════════════════════════════════ */
  function setupCustomCursor() {
    // Nur auf Geräten mit Maus aktivieren (kein Touch)
    if (!window.matchMedia('(pointer: fine)').matches) return;

    const blob = document.createElement('div');
    blob.className = 'cursor-blob';
    document.body.appendChild(blob);

    let mx = 0, my = 0;          // Zielposition
    let cx = window.innerWidth / 2, cy = window.innerHeight / 2;  // aktuelle Position des Flecks
    let velX = 0, velY = 0;      // Geschwindigkeit für Stauch‑Effekt

    document.addEventListener('mousemove', e => {
      mx = e.clientX;
      my = e.clientY;

      // Geschwindigkeit berechnen (für dynamische Verzerrung)
      velX = mx - cx;
      velY = my - cy;
    });

    // Hover‑State für interaktive Elemente
    const hoverTargets = 'a, button, .feature-card, .command-card, .log-tag, .stat-item, .btn, input, select, textarea';
    document.addEventListener('mouseover', e => {
      if (e.target.closest(hoverTargets)) {
        blob.classList.add('hovering');
      } else {
        blob.classList.remove('hovering');
      }
    });

    // Fleck verschwindet, wenn Maus das Fenster verlässt
    document.addEventListener('mouseleave', () => {
      blob.style.opacity = '0';
    });
    document.addEventListener('mouseenter', () => {
      blob.style.opacity = '1';
    });

    function animate() {
      // Weiche Verfolgung der Maus (100% zentriert)
      cx += (mx - cx) * 0.3;
      cy += (my - cy) * 0.3;

      // Dynamische Verzerrung basierend auf Geschwindigkeit
      const speed = Math.sqrt(velX * velX + velY * velY);
      const stretch = Math.min(speed / 4, 1.8);  // max. Stauchung
      const angle = Math.atan2(velY, velX);

      blob.style.transform = `translate(${cx}px, ${cy}px) scaleX(${1 + stretch * 0.15}) scaleY(${1 - stretch * 0.1}) rotate(${angle}rad)`;

      // Geschwindigkeit langsam abbauen
      velX *= 0.85;
      velY *= 0.85;

      requestAnimationFrame(animate);
    }
    animate();
  }

  /* ═══════════════════════════════════════════════════════
     THREE.JS 3D SCENE
     ═══════════════════════════════════════════════════════ */
  function setup3DScene() {
    if (typeof THREE === 'undefined') return;

    const canvas = document.createElement('canvas');
    canvas.id = 'three-canvas';
    document.body.insertBefore(canvas, document.body.firstChild);

    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);

    const scene  = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 200);
    camera.position.set(0, 0, 22);

    // ── Materials ─────────────────────────────────────────
    const wireMat = new THREE.MeshBasicMaterial({
      color: 0x1d6aff,
      wireframe: true,
      transparent: true,
      opacity: 0.12,
    });

    const glowMat = new THREE.MeshBasicMaterial({
      color: 0x0ea5e9,
      wireframe: true,
      transparent: true,
      opacity: 0.07,
    });

    const edgeMat = new THREE.LineBasicMaterial({
      color: 0x2563eb,
      transparent: true,
      opacity: 0.25,
    });

    // ── 3D Objects Group ──────────────────────────────────
    const group = new THREE.Group();
    scene.add(group);

    const objects = [];

    // Helper: edge lines from geometry
    function makeEdges(geo, mat, pos, scale) {
      const edges = new THREE.EdgesGeometry(geo);
      const mesh  = new THREE.LineSegments(edges, mat.clone());
      mesh.position.set(...pos);
      mesh.scale.setScalar(scale);
      return mesh;
    }

    // 1. Large shield-like octahedron (hero centerpiece)
    const shieldGeo = new THREE.OctahedronGeometry(3, 0);
    const shield = makeEdges(shieldGeo, edgeMat, [0, 0, -4], 1);
    shield.material.opacity = 0.18;
    group.add(shield);
    objects.push({ mesh: shield, rx: 0.003, ry: 0.005, phase: 0 });

    // 2. Icosahedron — right
    const icoGeo1 = new THREE.IcosahedronGeometry(2, 0);
    const ico1 = makeEdges(icoGeo1, edgeMat, [12, 3, -6], 1);
    group.add(ico1);
    objects.push({ mesh: ico1, rx: 0.004, ry: 0.003, phase: 1.5 });

    // 3. Icosahedron — left
    const icoGeo2 = new THREE.IcosahedronGeometry(1.5, 0);
    const ico2 = makeEdges(icoGeo2, edgeMat, [-13, -2, -5], 1);
    ico2.material.opacity = 0.12;
    group.add(ico2);
    objects.push({ mesh: ico2, rx: -0.005, ry: 0.004, phase: 3.0 });

    // 4. Tetrahedron — top right
    const tetraGeo = new THREE.TetrahedronGeometry(1.2, 0);
    const tetra = makeEdges(tetraGeo, edgeMat, [8, 7, -3], 1);
    tetra.material.opacity = 0.2;
    group.add(tetra);
    objects.push({ mesh: tetra, rx: 0.006, ry: -0.003, phase: 0.8 });

    // 5. Large dodecahedron-like shape — bottom left
    const dodGeo = new THREE.DodecahedronGeometry(2.5, 0);
    const dod = makeEdges(dodGeo, edgeMat, [-9, -7, -8], 1);
    dod.material.opacity = 0.08;
    group.add(dod);
    objects.push({ mesh: dod, rx: 0.002, ry: 0.006, phase: 2.2 });

    // 6. Small decorative octahedron — top left
    const oct2Geo = new THREE.OctahedronGeometry(0.8, 0);
    const oct2 = makeEdges(oct2Geo, edgeMat, [-6, 6, -2], 1);
    oct2.material.opacity = 0.28;
    group.add(oct2);
    objects.push({ mesh: oct2, rx: 0.008, ry: 0.006, phase: 1.1 });

    // 7. Wireframe sphere — far back
    const sphGeo = new THREE.SphereGeometry(4, 12, 8);
    const sph = new THREE.Mesh(sphGeo, wireMat.clone());
    sph.material.opacity = 0.04;
    sph.position.set(4, -2, -14);
    group.add(sph);
    objects.push({ mesh: sph, rx: 0.001, ry: 0.003, phase: 4 });

    // ── Particle Field ────────────────────────────────────
    const particleCount = 280;
    const positions = new Float32Array(particleCount * 3);

    for (let i = 0; i < particleCount; i++) {
      positions[i * 3]     = (Math.random() - 0.5) * 80;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 50;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 40 - 5;
    }

    const pGeo = new THREE.BufferGeometry();
    pGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    const pMat = new THREE.PointsMaterial({
      color: 0x3b82f6,
      size: 0.06,
      transparent: true,
      opacity: 0.55,
    });

    const particles = new THREE.Points(pGeo, pMat);
    scene.add(particles);

    // ── Grid Plane ────────────────────────────────────────
    const gridHelper = new THREE.GridHelper(80, 40, 0x1d3a6a, 0x0a1628);
    gridHelper.position.y = -12;
    gridHelper.material.transparent = true;
    gridHelper.material.opacity = 0.35;
    scene.add(gridHelper);

    // ── Ambient fog ───────────────────────────────────────
    scene.fog = new THREE.FogExp2(0x030712, 0.025);

    // ── 3D Mouse Tracker Ring (dezent) ────────────────────
    const hasFinePointer = window.matchMedia('(pointer: fine)').matches;
    let mouseTracker = null;
    let targetWorldX = 0, targetWorldY = 0;

    if (hasFinePointer) {
      const ringGeo = new THREE.TorusGeometry(0.6, 0.02, 16, 32);
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0x5b7fff,
        transparent: true,
        opacity: 0.6,
      });
      mouseTracker = new THREE.Mesh(ringGeo, ringMat);
      mouseTracker.position.z = 8;
      mouseTracker.renderOrder = 999;
      mouseTracker.material.depthTest = false;
      scene.add(mouseTracker);
    }

    // ── Mouse parallax ────────────────────────────────────
    let mouseX = 0, mouseY = 0;
    let targetX = 0, targetY = 0;

    document.addEventListener('mousemove', e => {
      mouseX = (e.clientX / window.innerWidth  - 0.5) * 2;
      mouseY = (e.clientY / window.innerHeight - 0.5) * 2;

      if (mouseTracker) {
        targetWorldX = (e.clientX / window.innerWidth) * 20 - 10;
        targetWorldY = -(e.clientY / window.innerHeight) * 12 + 6;
      }
    });

    // ── Scroll effect ─────────────────────────────────────
    let scrollY = 0;
    window.addEventListener('scroll', () => {
      scrollY = window.scrollY;
    });

    // ── Resize ────────────────────────────────────────────
    window.addEventListener('resize', () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });

    // ── Animate ───────────────────────────────────────────
    const clock = new THREE.Clock();

    function animate() {
      requestAnimationFrame(animate);

      const t = clock.getElapsedTime();

      // Smooth mouse follow
      targetX += (mouseX - targetX) * 0.05;
      targetY += (mouseY - targetY) * 0.05;

      group.rotation.y = targetX * 0.12;
      group.rotation.x = targetY * 0.08;

      // Scroll camera drift
      camera.position.y = -scrollY * 0.003;
      group.position.y  = -scrollY * 0.005;

      // Rotate each object
      objects.forEach(({ mesh, rx, ry, phase }) => {
        mesh.rotation.x += rx;
        mesh.rotation.y += ry;
        // Gentle float
        mesh.position.y += Math.sin(t * 0.6 + phase) * 0.003;
      });

      // Particles drift
      particles.rotation.y = t * 0.02;
      particles.rotation.x = t * 0.008;

      // Grid pulse
      gridHelper.material.opacity = 0.2 + Math.sin(t * 0.5) * 0.08;

      // Mouse-Tracker folgen lassen
      if (mouseTracker) {
        const lerpFactor = 0.08;
        mouseTracker.position.x += (targetWorldX - mouseTracker.position.x) * lerpFactor;
        mouseTracker.position.y += (targetWorldY - mouseTracker.position.y) * lerpFactor;
        mouseTracker.rotation.z += 0.01;
        mouseTracker.rotation.x = Math.sin(t * 2) * 0.1;
      }

      renderer.render(scene, camera);
    }

    animate();
  }

  /* ═══════════════════════════════════════════════════════
     NAVBAR — scroll state
     ═══════════════════════════════════════════════════════ */
  function setupNavbar() {
    const nav = document.querySelector('nav, .navbar');
    if (!nav) return;

    function update() {
      nav.classList.toggle('scrolled', window.scrollY > 20);
    }

    window.addEventListener('scroll', update, { passive: true });
    update();
  }

  /* ═══════════════════════════════════════════════════════
     SCROLL REVEAL — IntersectionObserver
     ═══════════════════════════════════════════════════════ */
  function setupScrollReveal() {
    // Auto-assign .reveal to key elements
    const targets = [
      'h2', '.section-desc', '.section-label',
      '.feature-card', '.command-card', '.log-tag',
      '.stat-item', '.dashboard-preview', '.cta-shield',
    ];

    targets.forEach(sel => {
      document.querySelectorAll(sel).forEach((el, i) => {
        el.classList.add('reveal');
        // Stagger siblings
        if (['feature-card', 'command-card', 'log-tag', 'stat-item'].some(c => el.classList.contains(c))) {
          const delay = (i % 6) * 0.07;
          el.style.transitionDelay = delay + 's';
        }
      });
    });

    const io = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
        }
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

    document.querySelectorAll('.reveal').forEach(el => io.observe(el));
  }

  /* ═══════════════════════════════════════════════════════
     FEATURE CARDS — mouse spotlight
     ═══════════════════════════════════════════════════════ */
  function setupFeatureCards() {
    document.querySelectorAll('.feature-card').forEach(card => {
      card.addEventListener('mousemove', e => {
        const r  = card.getBoundingClientRect();
        const mx = ((e.clientX - r.left) / r.width)  * 100;
        const my = ((e.clientY - r.top)  / r.height) * 100;
        card.style.setProperty('--mx', mx + '%');
        card.style.setProperty('--my', my + '%');
      });
    });
  }

  /* ═══════════════════════════════════════════════════════
     COUNTER ANIMATION
     ═══════════════════════════════════════════════════════ */
  function setupCounters() {
    const counters = document.querySelectorAll('.stat-value[data-target], [data-count]');
    if (!counters.length) return;

    const io = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        io.unobserve(entry.target);

        const el     = entry.target;
        const target = parseInt(el.dataset.target || el.dataset.count, 10);
        const suffix = el.dataset.suffix || '';
        const dur    = 1600;
        const start  = performance.now();

        function tick(now) {
          const pct = Math.min((now - start) / dur, 1);
          const ease = 1 - Math.pow(1 - pct, 3);
          el.textContent = Math.round(ease * target) + suffix;
          if (pct < 1) requestAnimationFrame(tick);
        }

        requestAnimationFrame(tick);
      });
    }, { threshold: 0.5 });

    counters.forEach(el => io.observe(el));
  }

  /* ═══════════════════════════════════════════════════════
     DASHBOARD PREVIEW — animated log stream
     ═══════════════════════════════════════════════════════ */
  function setupDashboardPreview() {
    const preview = document.querySelector('.dash-log, .dashboard-log');
    if (!preview) return;

    const events = [
      { type: 'ban',  user: 'SpamBot#0001',  action: 'Anti-Spam getriggert' },
      { type: 'warn', user: 'Troll#4421',     action: 'Regelverstoß erkannt' },
      { type: 'ok',   user: 'User#8832',      action: 'Verifizierung bestanden' },
      { type: 'mute', user: 'Raider#9912',    action: 'Anti-Raid aktiviert' },
      { type: 'ban',  user: 'Scammer#0420',   action: 'Phishing-Link blockiert' },
      { type: 'ok',   user: 'Mod#0001',       action: 'Case #1337 erstellt' },
    ];

    let idx = 0;

    function addEntry() {
      const ev   = events[idx % events.length];
      const entry = document.createElement('div');
      entry.className = 'log-entry';
      entry.innerHTML = `
        <span class="log-badge ${ev.type}">${ev.type.toUpperCase()}</span>
        <span style="color:var(--text-secondary)">${ev.user}</span>
        <span>${ev.action}</span>
      `;

      preview.appendChild(entry);
      idx++;

      // Keep max 5 entries
      while (preview.children.length > 5) {
        preview.removeChild(preview.firstChild);
      }

      // Scroll to bottom
      preview.scrollTop = preview.scrollHeight;
    }

    // Initial entries
    for (let i = 0; i < 3; i++) addEntry();

    setInterval(addEntry, 2400);
  }

  /* ═══════════════════════════════════════════════════════
     LOG CHANNEL HOVER TOOLTIPS
     ═══════════════════════════════════════════════════════ */
  function setupLogChannelHovers() {
    const descriptions = {
      moderation:     'Ban, Kick, Mute, Warn logs',
      'anti-spam':    'Nachrichten-Spam Erkennung',
      'anti-nuke':    'Massen-Aktionen Schutz',
      'anti-raid':    'Koordinierte Angriffe stoppen',
      automod:        'Regex, BadWords, Invite-Filter',
      tickets:        'Support-Ticket Ereignisse',
      cases:          'Case-ID Protokoll',
      audit:          'Discord Audit-Log Mirror',
    };

    document.querySelectorAll('.log-tag').forEach(tag => {
      const key = tag.textContent.replace('#', '').trim().toLowerCase();
      if (descriptions[key]) {
        tag.title = descriptions[key];
      }
    });
  }

  /* ═══════════════════════════════════════════════════════
     COMMAND CARDS — shimmer on hover
     ═══════════════════════════════════════════════════════ */
  function setupCommandCards() {
    // Wrap backtick-style command text if plain
    document.querySelectorAll('.commands-grid > *, .command-item, li').forEach(el => {
      const code = el.querySelector('code');
      if (code && !el.classList.contains('command-card')) {
        const wrapper = document.createElement('div');
        wrapper.className = 'command-card';

        const nameEl = document.createElement('span');
        nameEl.className = 'command-name';
        nameEl.textContent = code.textContent;

        const descEl = document.createElement('span');
        descEl.className = 'command-desc';
        descEl.textContent = el.lastChild?.textContent?.trim() || '';

        wrapper.appendChild(nameEl);
        wrapper.appendChild(descEl);
        el.replaceWith(wrapper);
      }
    });
  }

  /* ═══════════════════════════════════════════════════════
     MICRO INTERACTIONS — schlicht, aber lebendig
     ═══════════════════════════════════════════════════════ */
  function setupMicroInteractions() {
    const finePointer = window.matchMedia('(pointer: fine)').matches;
    if (!finePointer) return;

    document.querySelectorAll('.btn, .btn-glass, .feature-card, .stat-card, .pricing-card').forEach(el => {
      if (el.dataset.mfTilt) return;
      el.dataset.mfTilt = '1';
      el.addEventListener('mousemove', e => {
        const r = el.getBoundingClientRect();
        const x = (e.clientX - r.left) / Math.max(r.width, 1) - 0.5;
        const y = (e.clientY - r.top) / Math.max(r.height, 1) - 0.5;
        el.style.setProperty('--mx', `${(x + 0.5) * 100}%`);
        el.style.setProperty('--my', `${(y + 0.5) * 100}%`);
        el.style.transform = `perspective(900px) rotateX(${(-y * 4).toFixed(2)}deg) rotateY(${(x * 5).toFixed(2)}deg) translateY(-2px)`;
      });
      el.addEventListener('mouseleave', () => {
        el.style.transform = '';
      });
    });
  }

  function setupSmartClipboard() {
    document.querySelectorAll('[data-copy], code').forEach(el => {
      if (el.dataset.copyReady) return;
      el.dataset.copyReady = '1';
      el.addEventListener('click', async () => {
        const text = el.dataset.copy || el.textContent.trim();
        if (!text || text.length > 250) return;
        try {
          await navigator.clipboard.writeText(text);
          el.classList.add('copied');
          window.setTimeout(() => el.classList.remove('copied'), 900);
        } catch (_) { /* ignore */ }
      });
    });
  }

  /* ═══════════════════════════════════════════════════════
     DOM ENHANCEMENT — Add classes & wrappers
     ═══════════════════════════════════════════════════════ */
  document.addEventListener('DOMContentLoaded', function () {
    // Wrap page content
    const body = document.body;
    if (!body.querySelector('.page-wrapper')) {
      const nav    = body.querySelector('nav, header nav');
      const footer = body.querySelector('footer');
      const wrapper = document.createElement('div');
      wrapper.className = 'page-wrapper';

      // Move everything except canvas and cursor blob into wrapper
      Array.from(body.children).forEach(child => {
        if (child.id !== 'three-canvas' &&
            !child.classList.contains('cursor-blob') &&
            !child.classList.contains('mf-ambient')) {
          wrapper.appendChild(child);
        }
      });
      body.appendChild(wrapper);
    }

    // ── Stats enhancement ──────────────────────────────
    document.querySelectorAll('.stat-value, .hero-stat-num').forEach(el => {
      const num = parseInt(el.textContent.replace(/\D/g, ''), 10);
      if (!isNaN(num) && num > 0) {
        el.dataset.target = num;
        el.dataset.suffix = el.textContent.replace(/\d/g, '').trim();
        el.textContent = '0';
      }
    });

    // Re-run counters after DOM is ready
    setupCounters();

    // ── Section labels ─────────────────────────────────
    const sectionMap = {
      'Features': '🚀 Features',
      'Dashboard': '📊 Web Dashboard',
      'Logging':   '📝 Logging',
      'Commands':  '⌨️ Commands',
    };

    document.querySelectorAll('h2').forEach(h2 => {
      const parent = h2.parentElement;
      if (parent && !parent.querySelector('.section-label')) {
        Object.keys(sectionMap).forEach(key => {
          if (h2.textContent.includes(key)) {
            const label = document.createElement('div');
            label.className = 'section-label';
            label.textContent = sectionMap[key];
            parent.insertBefore(label, h2);
          }
        });
      }
    });

    // ── Add dividers between sections ──────────────────
    document.querySelectorAll('section + section').forEach(sec => {
      const div = document.createElement('div');
      div.className = 'divider';
      sec.parentNode.insertBefore(div, sec);
    });

    // ── Feature grid: wrap plain icons/h3 cards ────────
    const featureGrid = document.querySelector('.feature-grid, .features-grid');
    if (featureGrid) {
      featureGrid.querySelectorAll(':scope > *:not(.feature-card)').forEach(el => {
        el.classList.add('feature-card');
        const icon = el.querySelector('span, .icon, h3 + span');
        if (icon && !el.querySelector('.feature-icon')) {
          const iconWrap = document.createElement('div');
          iconWrap.className = 'feature-icon';
          iconWrap.textContent = icon.textContent;
          el.prepend(iconWrap);
          icon.remove();
        }
      });
    }

    // ── CTA section enhancement ────────────────────────
    document.querySelectorAll('section').forEach(sec => {
      if (sec.querySelector('h2')?.textContent?.includes('Bereit') ||
          sec.querySelector('h2')?.textContent?.includes('Ready')) {
        sec.classList.add('cta-section');
        if (!sec.querySelector('.cta-shield')) {
          const shield = document.createElement('div');
          shield.className = 'cta-shield';
          shield.textContent = '🛡️';
          sec.insertBefore(shield, sec.firstChild);
        }
      }
    });

    // ── Add scanline to glassmorphism elements ─────────
    document.querySelectorAll('.dashboard-preview, .feature-card').forEach(el => {
      if (!el.querySelector('.scanline-wrapper')) {
        const sw = document.createElement('div');
        sw.className = 'scanline-wrapper';
        el.style.position = 'relative';
        el.appendChild(sw);
      }
    });

    console.log('%c⬡ ModForge %cv3.0.0 ', 
      'background:#1d6aff;color:#fff;padding:3px 6px;border-radius:4px 0 0 4px;font-weight:bold',
      'background:#0f1f35;color:#7fa4c9;padding:3px 6px;border-radius:0 4px 4px 0');
  });

})();
