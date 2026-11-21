
/* =========================================================
   Translate App — landmarks.js
   Извличане на landmarks от записано видео.
   Backend: FastAPI
   ========================================================= */

(function () {
    'use strict';

    const API_BASE_URL =
        window.TRANSLATE_API_BASE_URL || 'http://127.0.0.1:8000';

    async function extract(recording) {
        if (!recording || !recording.id) {
            throw new Error('Липсва ID на записа.');
        }

        let response;

        try {
            response = await fetch(
                `${API_BASE_URL}/api/recordings/${encodeURIComponent(recording.id)}/extract`,
                {
                    method: 'POST',
                    headers: {
                        'Accept': 'application/json'
                    }
                }
            );
        } catch (error) {
            throw new Error(
                'Не може да се достигне Python backend.'
            );
        }

        const contentType =
            response.headers.get('content-type') || '';

        const result = contentType.includes('application/json')
            ? await response.json().catch(() => null)
            : null;

        if (!response.ok) {
            const detail = result?.detail;

            throw new Error(
                typeof detail === 'string'
                    ? detail
                    : `Грешка при извличане: HTTP ${response.status}`
            );
        }

        if (!result || result.status !== 'completed') {
            throw new Error(
                'Backend не потвърди успешно извличане.'
            );
        }

        return result;
    }

    window.TranslateLandmarks = {
        extract
    };

})();
