const menuButton = document.querySelector('.menu-toggle');
const mobileNav = document.querySelector('.mobile-nav');

if (menuButton && mobileNav) {
  menuButton.addEventListener('click', () => {
    const open = menuButton.getAttribute('aria-expanded') !== 'true';
    menuButton.setAttribute('aria-expanded', String(open));
    menuButton.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    mobileNav.hidden = !open;
  });

  mobileNav.addEventListener('click', (event) => {
    if (event.target.closest('a')) {
      mobileNav.hidden = true;
      menuButton.setAttribute('aria-expanded', 'false');
      menuButton.setAttribute('aria-label', 'Open menu');
    }
  });
}

document.querySelectorAll('.copy-button').forEach((button) => {
  button.addEventListener('click', async () => {
    const code = button.closest('.code-window')?.querySelector('code');
    if (!code) return;

    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
      await navigator.clipboard.writeText(code.textContent);
      const previous = button.innerHTML;
      button.textContent = 'Copied ✓';
      button.classList.add('copied');
      window.setTimeout(() => {
        button.innerHTML = previous;
        button.classList.remove('copied');
      }, 1800);
    } catch {
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(code);
      selection.removeAllRanges();
      selection.addRange(range);
      button.textContent = 'Selected — press ⌘/Ctrl+C';
    }
  });
});

const sectionLinks = [...document.querySelectorAll(
  '.tutorial-sidebar a[href^="#"], .guide-sidebar a[href^="#"]'
)];
const sections = sectionLinks.map((link) => document.querySelector(link.getAttribute('href')));

if ('IntersectionObserver' in window && sections.length && sections.every(Boolean)) {
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting)
      .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (!visible) return;

    sectionLinks.forEach((link) => {
      const active = link.getAttribute('href') === `#${visible.target.id}`;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  }, { rootMargin: '-10% 0px -45% 0px', threshold: 0 });

  sections.forEach((section) => observer.observe(section));
}
