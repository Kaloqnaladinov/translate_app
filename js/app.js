
/* =========================================================
   Translate App — app.js
   Главно меню и popup прозорци
   ========================================================= */

(function () {
    'use strict';

    const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    const MSG_NOT_ACTIVE =
        'Функцията за изпращане все още не е активна.';

    let lastFocused = null;

    function openModal(overlay) {
        if (!overlay) return;

        lastFocused = document.activeElement;

        overlay.classList.add('is-open');
        overlay.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');

        const firstField = overlay.querySelector(
            'input:not([type="hidden"]), textarea, button'
        );

        if (firstField) firstField.focus();
    }

    function closeModal(overlay) {
        if (!overlay) return;

        overlay.classList.remove('is-open');
        overlay.setAttribute('aria-hidden', 'true');

        const anotherModalIsOpen =
            document.querySelector('.modal-overlay.is-open');

        if (!anotherModalIsOpen) {
            document.body.classList.remove('modal-open');
        }

        if (
            lastFocused &&
            typeof lastFocused.focus === 'function'
        ) {
            lastFocused.focus();
        }
    }

    function initModalTriggers() {
        document.querySelectorAll('[data-modal]').forEach(btn => {
            btn.addEventListener('click', () => {
                const modalId = btn.getAttribute('data-modal');
                const overlay = document.getElementById(modalId);

                openModal(overlay);
            });
        });

        document.querySelectorAll('.modal-overlay').forEach(overlay => {
            overlay.addEventListener('click', event => {
                if (event.target === overlay) {
                    closeModal(overlay);
                }
            });

            overlay
                .querySelectorAll('[data-close-modal]')
                .forEach(btn => {
                    btn.addEventListener('click', () => {
                        closeModal(overlay);
                    });
                });
        });

        document.addEventListener('keydown', event => {
            if (event.key !== 'Escape') return;

            const openOverlay = document.querySelector(
                '.modal-overlay.is-open'
            );

            if (openOverlay) {
                closeModal(openOverlay);
            }
        });
    }

    function initPopupForms() {
        document.querySelectorAll('[data-popup-form]').forEach(form => {
            form.addEventListener('submit', event => {
                event.preventDefault();

                const emailInput = form.querySelector(
                    'input[type="email"]'
                );

                const textarea = form.querySelector('textarea');
                const errorElement = form.querySelector('[data-error]');
                const messageElement = form.querySelector('[data-message]');

                if (
                    !emailInput ||
                    !textarea ||
                    !errorElement ||
                    !messageElement
                ) {
                    return;
                }

                const email = emailInput.value.trim();
                const description = textarea.value.trim();

                errorElement.hidden = true;
                messageElement.hidden = true;

                if (!email) {
                    showError('Моля, въведете имейл.', emailInput);
                    return;
                }

                if (!EMAIL_RE.test(email)) {
                    showError(
                        'Моля, въведете валиден имейл.',
                        emailInput
                    );
                    return;
                }

                if (!description) {
                    showError(
                        'Моля, попълнете описанието.',
                        textarea
                    );
                    return;
                }

                messageElement.textContent = MSG_NOT_ACTIVE;
                messageElement.hidden = false;

                form.reset();

                function showError(message, field) {
                    errorElement.textContent = message;
                    errorElement.hidden = false;
                    field.focus();
                }
            });
        });
    }

    function initApp() {
        initModalTriggers();
        initPopupForms();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initApp);
    } else {
        initApp();
    }
})();
