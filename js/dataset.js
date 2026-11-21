
/* =========================================================
   Translate App — dataset.js
   Управление на записите в тренировъчния dataset.
   Backend: FastAPI
   ========================================================= */

(function () {
    'use strict';

    const API_BASE_URL =
        window.TRANSLATE_API_BASE_URL || 'http://127.0.0.1:8000';

    const statusElement = document.getElementById('datasetStatus');
    const recordingsList = document.getElementById('recordingsList');

    if (!statusElement || !recordingsList) {
        console.error(
            'Dataset: липсват datasetStatus или recordingsList в HTML.'
        );
        return;
    }

    let recordings = [];
    let isLoading = false;

    // ---------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------

    function setStatus(message) {
        statusElement.textContent = message;
    }

    function formatDate(value) {
        if (!value) return 'Неизвестна дата';

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return value;
        }

        return new Intl.DateTimeFormat('bg-BG', {
            dateStyle: 'medium',
            timeStyle: 'short'
        }).format(date);
    }

    function formatFileSize(bytes) {
        if (!Number.isFinite(Number(bytes))) {
            return 'Неизвестен размер';
        }

        const size = Number(bytes);

        if (size < 1024) {
            return `${size} B`;
        }

        if (size < 1024 * 1024) {
            return `${(size / 1024).toFixed(1)} KB`;
        }

        return `${(size / (1024 * 1024)).toFixed(2)} MB`;
    }

    function createElement(tag, text, className) {
        const element = document.createElement(tag);

        if (text !== undefined && text !== null) {
            element.textContent = text;
        }

        if (className) {
            element.className = className;
        }

        return element;
    }

    async function request(endpoint, options = {}) {
        let response;

        try {
            response = await fetch(
                `${API_BASE_URL}${endpoint}`,
                {
                    ...options,
                    headers: {
                        ...(options.headers || {})
                    }
                }
            );
        } catch (error) {
            throw new Error(
                'Не може да се достигне Python backend. ' +
                'Провери дали сървърът работи на порт 8000.'
            );
        }

        const contentType =
            response.headers.get('content-type') || '';

        let result = null;

        if (contentType.includes('application/json')) {
            result = await response.json().catch(() => null);
        }

        if (!response.ok) {
            const message =
                result?.detail ||
                `Backend грешка: HTTP ${response.status}`;

            throw new Error(message);
        }

        return result;
    }

    // ---------------------------------------------------------
    // Recording actions
    // ---------------------------------------------------------

    async function editLabel(recording) {
        const currentLabel = recording.label || '';

        const newLabel = window.prompt(
            'Въведи правилния етикет за този жест:',
            currentLabel
        );

        if (newLabel === null) return;

        const normalizedLabel = newLabel.trim();

        if (normalizedLabel.length > 80) {
            window.alert(
                'Етикетът не може да бъде по-дълъг от 80 символа.'
            );
            return;
        }

        try {
            setStatus('Запазване на етикета...');

            await request(
                `/api/recordings/${encodeURIComponent(recording.id)}`,
                {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        label: normalizedLabel || null
                    })
                }
            );

            await loadRecordings();

            setStatus('Етикетът е обновен успешно.');
        } catch (error) {
            setStatus(`Грешка: ${error.message}`);
        }
    }

    async function deleteRecording(recording) {
        const confirmed = window.confirm(
            'Сигурен ли си, че искаш да премахнеш този запис от списъка?\n\n' +
            'ВАЖНО: Ще бъдат изтрити само метаданните в базата данни. ' +
            'Оригиналното видео ще остане в dataset/raw/.'
        );

        if (!confirmed) return;

        try {
            setStatus('Премахване на записа...');

            await request(
                `/api/recordings/${encodeURIComponent(recording.id)}`,
                {
                    method: 'DELETE'
                }
            );

            await loadRecordings();

            setStatus(
                'Метаданните са премахнати. Оригиналното видео е запазено.'
            );
        } catch (error) {
            setStatus(`Грешка: ${error.message}`);
        }
    }

    // ---------------------------------------------------------
    // Render
    // ---------------------------------------------------------

    function renderRecording(recording) {
        const card = createElement('article', undefined, 'recording-item');

        const title = createElement(
            'h3',
            recording.label || 'Без етикет',
            'recording-title'
        );

        const filename = createElement(
            'p',
            `Файл: ${recording.original_filename || 'Неизвестен файл'}`
        );

        const date = createElement(
            'p',
            `Дата: ${formatDate(recording.created_at)}`
        );

        const participant = createElement(
            'p',
            `Участник: ${recording.participant_id || 'Неизвестен'}`
        );

        const size = createElement(
            'p',
            `Размер: ${formatFileSize(recording.file_size)}`
        );

        const id = createElement(
            'p',
            `ID: ${recording.id}`
        );

        const actions = createElement(
            'div',
            undefined,
            'recording-actions'
        );

        const fileLink = createElement('a', 'Отвори видеото');

        const fileUrl = recording.file_url
            ? new URL(recording.file_url, API_BASE_URL).href
            : `${API_BASE_URL}/api/recordings/${encodeURIComponent(recording.id)}/file`;

        fileLink.href = fileUrl;
        fileLink.target = '_blank';
        fileLink.rel = 'noopener noreferrer';

        const editButton = createElement('button', 'Промени етикета');
        editButton.type = 'button';

        editButton.addEventListener('click', () => {
            editLabel(recording);
        });

        const deleteButton = createElement('button', 'Премахни от списъка');
        deleteButton.type = 'button';

        deleteButton.addEventListener('click', () => {
            deleteRecording(recording);
        });

        actions.append(
            fileLink,
            editButton,
            deleteButton
        );

        card.append(
            title,
            filename,
            date,
            participant,
            size,
            id,
            actions
        );

        return card;
    }

    function renderRecordings() {
        recordingsList.replaceChildren();

        if (recordings.length === 0) {
            const emptyMessage = createElement(
                'p',
                'Все още няма записани видеа.'
            );

            recordingsList.appendChild(emptyMessage);
            return;
        }

        const fragment = document.createDocumentFragment();

        recordings.forEach(recording => {
            fragment.appendChild(
                renderRecording(recording)
            );
        });

        recordingsList.appendChild(fragment);
    }

    // ---------------------------------------------------------
    // Load recordings
    // ---------------------------------------------------------

    async function loadRecordings() {
        if (isLoading) return;

        isLoading = true;
        setStatus('Зареждане на записите...');

        try {
            const result = await request('/api/recordings');

            if (!result || !Array.isArray(result.items)) {
                throw new Error(
                    'Backend върна невалиден формат на записите.'
                );
            }

            recordings = result.items;

            renderRecordings();

            setStatus(
                `Заредени записи: ${recordings.length}`
            );

        } catch (error) {
            recordings = [];
            renderRecordings();

            setStatus(`Грешка при зареждане: ${error.message}`);

        } finally {
            isLoading = false;
        }
    }

    // ---------------------------------------------------------
    // Public interface
    // ---------------------------------------------------------

    window.TranslateDataset = {
        reload: loadRecordings,

        getRecordings: function () {
            return [...recordings];
        }
    };

    // Initial load
    loadRecordings();

})();
