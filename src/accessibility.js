// Keep keyboard focus inside whichever application modal is currently visible.
let previousFocus;
let activeModal;
let lastControl;
export function bindModalAccessibility() {
  document.addEventListener('click', event => {
    if (!activeModal) lastControl = event.target.closest('button, a, input');
  }, true);
  const observer = new MutationObserver(() => {
    const modal = [...document.querySelectorAll('.modal-backdrop:not(.hidden)')].find(node => node.getClientRects().length);
    if (modal === activeModal) return;
    if (modal) {
      previousFocus = lastControl || document.activeElement;
      activeModal = modal;
      const panel = modal.querySelector('section') || modal;
      panel.setAttribute('role','dialog'); panel.setAttribute('aria-modal','true');
      if (!panel.hasAttribute('aria-labelledby')) {
        const heading = panel.querySelector('h2, .eyebrow');
        if (heading) { heading.id ||= `${modal.id}-title`; panel.setAttribute('aria-labelledby',heading.id); }
      }
      const close = panel.querySelector('.modal-close');
      close?.setAttribute('aria-label','Close dialog');
      (panel.querySelector('button:not(:disabled), input:not([type=hidden]), select') || panel).focus();
    } else {
      activeModal = null;
      if (previousFocus?.isConnected) previousFocus.focus();
      else if (previousFocus?.id) document.getElementById(previousFocus.id)?.focus();
    }
  });
  observer.observe(document.querySelector('#app'), {childList:true, subtree:true, attributes:true, attributeFilter:['class']});
  document.addEventListener('keydown', event => {
    if (!activeModal || event.key !== 'Tab') return;
    const focusable = [...activeModal.querySelectorAll('button:not(:disabled), input:not(:disabled):not([type=hidden]), select:not(:disabled), textarea, a[href], [tabindex="0"]')].filter(node => node.getClientRects().length);
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && (document.activeElement === first || !activeModal.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || !activeModal.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
  });
}
