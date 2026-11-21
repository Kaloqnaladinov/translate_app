
/* =========================================================
   Translate App — recorder.js
   Използва съществуващите елементи от kamera.html.
   Не изисква промяна на CSS.
   Backend: FastAPI
   ========================================================= */

(function () {
    'use strict';

    /* ---------- Configuration ---------- */

    const API_BASE_URL = 'http://127.0.0.1:8000';

    /* ---------- Existing HTML elements ---------- */

    const personContainer = document.querySelector(
        '.person-container'
    );

    const headElement = personContainer?.querySelector('.head');
    const bodyElement = personContainer?.querySelector('.body');

    const playButton = document.querySelector('.play-btn');
    const stopButton = document.querySelector('.stop-btn');

    const statusElement = document.querySelector('.text-bold');

    /* ---------- Camera state ---------- */

    let cameraStream = null;
    let mediaRecorder = null;
    let recordedChunks = [];
    let selectedMimeType = '';
    let videoPreview = null;
    let shouldUpload = false;
    let pageIsClosing = false;

    const participantId = createParticipantId();

    /* ---------- Helpers ---------- */

    function createParticipantId() {
        if (crypto.randomUUID) {
            return `web-${crypto.randomUUID()}`;
        }

        return (
            'web-' +
            Date.now().toString(36) +
            '-' +
            Math.random().toString(36).slice(2, 10)
        );
    }

    function setStatus(message) {
        if (statusElement) {
            statusElement.textContent = message;
        }
    }

    function getSupportedMimeType() {
        if (!window.MediaRecorder) {
            throw new Error(
                'Браузърът не поддържа запис на видео.'
            );
        }

        const candidates = [
            'video/webm;codecs=vp9',
            'video/webm;codecs=vp8',
            'video/webm',
            'video/mp4'
        ];

        for (const type of candidates) {
            if (MediaRecorder.isTypeSupported(type)) {
                return type;
            }
        }

        return '';
    }

    function setButtonStates(isRecording) {
        if (playButton) {
            playButton.disabled = isRecording;
        }

        if (stopButton) {
            stopButton.disabled = !isRecording;
        }
    }

    /* ---------- Camera preview ---------- */

    function createVideoPreview() {
        if (videoPreview) return;

        videoPreview = document.createElement('video');

        videoPreview.autoplay = true;
        videoPreview.muted = true;
        videoPreview.playsInline = true;

        videoPreview.setAttribute(
            'aria-label',
            'Изображение от камерата'
        );

        /*
         * Видеото заема мястото на съществуващата
         * графика на човечето.
         */
        Object.assign(videoPreview.style, {
            display: 'block',
            width: '220px',
            height: '280px',
            maxWidth: '100%',
            objectFit: 'cover',
            borderRadius: '16px',
            backgroundColor: '#111'
        });

        if (headElement) {
            headElement.hidden = true;
        }

        if (bodyElement) {
            bodyElement.hidden = true;
        }

        personContainer.appendChild(videoPreview);
    }

    function removeVideoPreview() {
        if (videoPreview) {
            videoPreview.remove();
            videoPreview = null;
        }

        if (headElement) {
            headElement.hidden = false;
        }

        if (bodyElement) {
            bodyElement.hidden = false;
        }
    }

    async function startCamera() {
        if (cameraStream) return;

        if (
            !navigator.mediaDevices ||
            !navigator.mediaDevices.getUserMedia
        ) {
            throw new Error(
                'Няма достъп до камерата. ' +
                'Използвай localhost или HTTPS.'
            );
        }

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                facingMode: 'user',
                width: { ideal: 1280 },
                height: { ideal: 720 }
            },
            audio: false
        });

        createVideoPreview();

        videoPreview.srcObject = cameraStream;

        await videoPreview.play();
    }

    function stopCamera() {
        if (cameraStream) {
            cameraStream.getTracks().forEach(track => {
                track.stop();
            });

            cameraStream = null;
        }

        if (videoPreview) {
            videoPreview.srcObject = null;
        }

        removeVideoPreview();
    }

    /* ---------- Recording ---------- */

    async function startRecording() {
        try {
            if (!personContainer || !playButton || !stopButton) {
                throw new Error(
                    'Не са намерени необходимите HTML елементи.'
                );
            }

            if (mediaRecorder?.state === 'recording') {
                return;
            }

            /*
             * Изрично съгласие преди запис и съхранение
             * на видео в backend.
             */
            const consent = window.confirm(
                'Съгласен ли си видеозаписът да бъде ' +
                'съхранен в dataset на приложението?'
            );

            if (!consent) {
                setStatus('Записът е отказан.');
                return;
            }

            setStatus('Стартиране на камерата...');

            await startCamera();

            recordedChunks = [];
            shouldUpload = true;
            pageIsClosing = false;

            selectedMimeType = getSupportedMimeType();

            const options = selectedMimeType
                ? { mimeType: selectedMimeType }
                : undefined;

            mediaRecorder = new MediaRecorder(
                cameraStream,
                options
            );

            mediaRecorder.addEventListener(
                'dataavailable',
                event => {
                    if (event.data && event.data.size > 0) {
                        recordedChunks.push(event.data);
                    }
                }
            );

            mediaRecorder.addEventListener(
                'error',
                event => {
                    shouldUpload = false;

                    setStatus(
                        'Грешка при запис: ' +
                        (event.error?.message || 'неизвестна грешка')
                    );

                    setButtonStates(false);
                }
            );

            mediaRecorder.addEventListener(
                'stop',
                async () => {
                    if (shouldUpload && !pageIsClosing) {
                        await uploadRecording();
                    }

                    setButtonStates(false);
                }
            );

            mediaRecorder.start(1000);

            setButtonStates(true);

            setStatus('Камерата е активна. Записът започна.');

        } catch (error) {
            setStatus(error.message);
            setButtonStates(false);
        }
    }

    function stopRecording() {
        if (
            !mediaRecorder ||
            mediaRecorder.state !== 'recording'
        ) {
            return;
        }

        setStatus('Записът приключва...');

        stopButton.disabled = true;

        mediaRecorder.stop();
    }

    /* ---------- Upload to Python backend ---------- */

    async function uploadRecording() {
        try {
            if (!recordedChunks.length) {
                throw new Error('Няма записани видео данни.');
            }

            const mimeType =
                mediaRecorder.mimeType ||
                selectedMimeType ||
                'video/webm';

            const extension = mimeType.includes('mp4')
                ? 'mp4'
                : 'webm';

            const videoBlob = new Blob(recordedChunks, {
                type: mimeType
            });

            if (videoBlob.size === 0) {
                throw new Error('Видео файлът е празен.');
            }

            const formData = new FormData();

            formData.append(
                'file',
                videoBlob,
                `recording-${Date.now()}.${extension}`
            );

            formData.append(
                'participant_id',
                participantId
            );

            formData.append('consent', 'true');

            formData.append(
                'label',
                'Камерен запис'
            );

            setStatus('Изпращане на видеото към backend...');

            const response = await fetch(
                `${API_BASE_URL}/api/recordings`,
                {
                    method: 'POST',
                    body: formData
                }
            );

            const result = await response.json().catch(() => ({}));

            if (!response.ok) {
                throw new Error(
                    result.detail ||
                    `Backend грешка: ${response.status}`
                );
            }

            recordedChunks = [];

            setStatus(
                `Записът е запазен успешно! ID: ${result.id}`
            );

        } catch (error) {
            setStatus(
                `Грешка при качване: ${error.message}`
            );
        }
    }

    /* ---------- Events ---------- */

    if (playButton) {
        playButton.addEventListener(
            'click',
            startRecording
        );
    }

    if (stopButton) {
        stopButton.addEventListener(
            'click',
            stopRecording
        );
    }

    window.addEventListener('pagehide', () => {
        pageIsClosing = true;
        shouldUpload = false;

        if (mediaRecorder?.state === 'recording') {
            mediaRecorder.stop();
        }

        stopCamera();
    });

    /* ---------- Initial state ---------- */

    setButtonStates(false);

    setStatus('Натисни бутона за старт, за да включиш камерата.');

})();
