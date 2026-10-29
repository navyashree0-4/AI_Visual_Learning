document.addEventListener('DOMContentLoaded', () => {
  const nav = document.getElementById('nav'), menu = document.getElementById('menu'), burger = document.getElementById('burger');

  /* Sticky nav shadow */
  const onScroll = () => nav && nav.classList.toggle('scrolled', window.scrollY > 10);
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  /* Mobile menu */
  if (burger && menu) {
    const setOpen = open => {
      menu.classList.toggle('open', open);
      burger.setAttribute('aria-expanded', String(open));
      burger.textContent = open ? '✕' : '☰';
    };
    burger.addEventListener('click', () => setOpen(!menu.classList.contains('open')));
    menu.querySelectorAll('a').forEach(a => a.addEventListener('click', () => setOpen(false)));
    document.addEventListener('keydown', e => e.key === 'Escape' && setOpen(false));
  }

  /* Demo topic preview */
  const input = document.getElementById('demo-topic'), title = document.getElementById('demo-title');
  const show = v => { if (title) title.textContent = v.trim() || 'Your topic'; };
  if (input) input.addEventListener('input', () => show(input.value));
  document.querySelectorAll('.demo-suggestions button').forEach(b =>
    b.addEventListener('click', () => { input.value = b.dataset.topic; show(b.dataset.topic); })
  );
});