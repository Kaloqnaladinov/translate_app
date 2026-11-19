/* ==================================================================
   Translate App — app.js
   Milestone: index.html popups (Идеи / Грешки / Речник)
   Vanilla JS, no dependencies, no network calls, no storage.
   ================================================================== */

(function () {
    'use strict';

    /* ---------- Configuration ---------- */
    // Опростена проверка за имейл – достатъчна за MVP.
    // Не претендира за пълно съответствие с RFC 5322.
    var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    var MSG_NOT_ACTIVE = 'Функцията за изпращане все още не е активна.';

    /* ---------- Modal open / close ---------- */
    var lastFocused = null;

    function openModal(overlay) {
        if (!overlay) return;
        lastFocused = document.activeElement;
        overlay.classList.add('is-open');
        overlay.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');

        // Фокус върху първото интерактивно поле (или close бутона).
        var firstField = overlay.querySelector(
            'input:not([type="hidden"]), textarea, button'
        );
        if (firstField) firstField.focus();
    }

    function closeModal(overlay) {
        if (!overlay) return;
        overlay.classList.remove('is-open');
        overlay.setAttribute('aria-hidden', 'true');

        // Отключваме scroll-а само ако няма друг отворен modal.
        if (!document.querySelector('.modal-overlay.is-open')) {
            document.body.classList.remove('modal-open');
        }

        // Връщаме фокуса там, където е бил преди отварянето.
        if (lastFocused && typeof lastFocused.focus === 'function') {
            lastFocused.focus();
        }
    }

    function initModalTriggers() {
        // Бутоните, които отварят modal по data-modal="<id>".
        var openButtons = document.querySelectorAll('[data-modal]');
        openButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var id = btn.getAttribute('data-modal');
                openModal(document.getElementById(id));
            });
        });

        // Затваряне: X бутон, клик върху backdrop, Escape.
        var overlays = document.querySelectorAll('.modal-overlay');
        overlays.forEach(function (overlay) {
            // Клик върху затъмнения фон (не върху .modal-content).
            overlay.addEventListener('click', function (e) {
                if (e.target === overlay) closeModal(overlay);
            });

            // X бутон.
            overlay.querySelectorAll('[data-close-modal]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    closeModal(overlay);
                });
            });
        });

        // Escape затваря първия отворен modal.
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            var open = document.querySelector('.modal-overlay.is-open');
            if (open) closeModal(open);
        });
    }

    /* ---------- Form validation & submit stub ---------- */
    function initPopupForms() {
        var forms = document.querySelectorAll('[data-popup-form]');
        forms.forEach(function (form) {
            form.addEventListener('submit', function (e) {
                e.preventDefault();

                var emailInput = form.querySelector('input[type="email"]');
                var textarea = form.querySelector('textarea');
                var errorEl = form.querySelector('[data-error]');
                var msgEl = form.querySelector('[data-message]');

                var email = (emailInput.value || '').trim();
                var description = (textarea.value || '').trim();

                // Скриваме предишни съобщения.
                errorEl.hidden = true;
                msgEl.hidden = true;

                // 1) Задължителен имейл.
                if (!email) {
                    errorEl.textContent = 'Моля, въведете имейл.';
                    errorEl.hidden = false;
                    emailInput.focus();
                    return;
                }

                // 2) Валиден формат на имейл.
                if (!EMAIL_RE.test(email)) {
                    errorEl.textContent = 'Моля, въведете валиден имейл.';
                    errorEl.hidden = false;
                    emailInput.focus();
                    return;
                }

                // 3) Задължително описание.
                if (!description) {
                    errorEl.textContent = 'Моля, попълнете описанието.';
                    errorEl.hidden = false;
                    textarea.focus();
                    return;
                }

                // Изпращането НЕ е реализирано в този milestone.
                // Никакви данни не се изпращат или записват.
                msgEl.textContent = MSG_NOT_ACTIVE;
                msgEl.hidden = false;
                form.reset();
            });
        });
    }

    /* ---------- Boot ---------- */
    document.addEventListener('DOMContentLoaded', function () {
        initModalTriggers();
        initPopupForms();
    });
})();
