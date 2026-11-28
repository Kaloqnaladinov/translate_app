
/* =========================================================
   TRANSLATE APP — RECORDER.JS
   Камера, видеозапис, смяна на камерата,
   плаващи контроли и известия.
   Backend: FastAPI
   ========================================================= */

(function () {
    'use strict';

    /* =====================================================
       1. CONFIGURATION
       ===================================================== */

    const API_BASE_URL =
        window.TRANSLATE_API_BASE_URL ||
        'http://127.0.0.1:8000';

    /* =====================================================
       2. HTML ELEMENTS
       ===================================================== */

    const phoneScreen = document.querySelector('.phone-screen');
    const cameraStage = document.querySelector('#camera-stage');
    const personContainer = document.querySelector('.person-container');

    const headElement = personContainer?.querySelector('.head');
    const bodyElement = personContainer?.querySelector('.body');

    const playButton = document.querySelector('.play-btn');
    const stopButton = document.querySelector('.stop-btn');

    const switchCameraButton =
        document.querySelector('#switch-camera');

    const controlsPanel =
        document.querySelector('#camera-controls');

    const statusElement =
        document.querySelector('.text-bold');

    /* =====================================================
       3. APPLICATION STATE
       ===================================================== */

    let cameraStream = null;
    let videoPreview = null;

    let currentFacingMode = 'user';
    let isSwitchingCamera = false;

    let mediaRecorder = null;
    let recordedChunks = [];
    let selectedMimeType = '';

    let shouldUpload = false;
    let pageIsClosing = false;

    let toastElement = null;
    let toastTimeout = null;

    const participantId = createParticipantId();

    /* =====================================================
       4. PARTICIPANT ID
       ===================================================== */

    function createParticipantId() {
        if (window.crypto?.randomUUID) {
            return `web-${window.crypto.randomUUID()}`;
        }

        return (
            'web-' +
            Date.now().toString(36) +
            '-' +
            Math.random().toString(36).slice(2, 10)
        );
    }

    /* =====================================================
       5. POPUP NOTIFICATIONS
       ===================================================== */

    function createToast() {
        if (toastElement || !phoneScreen) return;

        toastElement = document.createElement('div');

        toastElement.className = 'camera-toast';
        toastElement.setAttribute('role', 'status');
        toastElement.setAttribute('aria-live', 'polite');

        Object.assign(toastElement.style, {
            position: 'absolute',
            left: '50%',
            top: '50%',
            transform: 'translate(-50%, -50%)',
            width: 'max-content',
            maxWidth: 'calc(100% - 40px)',
            padding: '11px 15px',
            backgroundColor: '#111',
            color: '#fff',
            border: '1px solid #555',
            borderRadius: '12px',
            fontSize: '13px',
            fontWeight: '700',
            lineHeight: '1.4',
            textAlign: 'center',
            boxShadow: '0 4px 15px rgba(0,0,0,0.35)',
            zIndex: '50',
            pointerEvents: 'none',
            opacity: '0',
            transition: 'opacity 0.2s ease'
        });

        phoneScreen.appendChild(toastElement);
    }

    function setStatus(message, duration = 2800, isError = false) {
        // Запазваме досегашното поведение:
        // обичайните статуси не се показват на тестерите.
        if (!isError) return;

        createToast();

        if (statusElement) {
            statusElement.textContent = 'Не можа да се запише.';
            statusElement.hidden = true;
        }

        if (!toastElement) return;

        toastElement.textContent = 'Не можа да се запише.';
        toastElement.style.opacity = '1';

        if (toastTimeout) {
            clearTimeout(toastTimeout);
        }

        toastTimeout = setTimeout(() => {
            if (toastElement) {
                toastElement.style.opacity = '0';
            }
        }, duration);
    }

    /* =====================================================
       6. SUPPORTED VIDEO FORMAT
       ===================================================== */

    function getSupportedMimeType() {
        if (!window.MediaRecorder) {
            throw new Error(
                'Браузърът не поддържа видеозапис.'
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

    /* =====================================================
       7. RECORDING BUTTON STATES
       ===================================================== */

    function setButtonStates(isRecording) {
        if (playButton) {
            playButton.disabled = isRecording;
        }

        if (stopButton) {
            stopButton.disabled = !isRecording;
        }
    }

    /* =====================================================
       8. VIDEO PREVIEW
       ===================================================== */

    function updateVideoMirror() {
        if (!videoPreview) return;

        videoPreview.style.transform =
            currentFacingMode === 'user'
                ? 'scaleX(-1)'
                : 'none';
    }

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

        Object.assign(videoPreview.style, {
            display: 'block',
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            backgroundColor: '#111'
        });

        updateVideoMirror();

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
            videoPreview.srcObject = null;
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

    /* =====================================================
       9. START CAMERA
       ===================================================== */

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

        const newStream =
            await navigator.mediaDevices.getUserMedia({
                video: {
                    facingMode: currentFacingMode,
                    width: { ideal: 1280 },
                    height: { ideal: 720 }
                },
                audio: false
            });

        cameraStream = newStream;

        createVideoPreview();

        videoPreview.srcObject = cameraStream;

        updateVideoMirror();

        await videoPreview.play();
    }

    /* =====================================================
       10. SWITCH FRONT / BACK CAMERA
       ===================================================== */

    async function switchCamera() {
        if (isSwitchingCamera) return;

        if (!cameraStream || !videoPreview) {
            setStatus('Първо стартирай камерата.');
            return;
        }

        if (mediaRecorder?.state === 'recording') {
            setStatus(
                'Спри записа, преди да смениш камерата.'
            );
            return;
        }

        isSwitchingCamera = true;

        const nextFacingMode =
            currentFacingMode === 'user'
                ? 'environment'
                : 'user';

        let newStream = null;

        try {
            setStatus('Търсене на камера...');

            newStream =
                await navigator.mediaDevices.getUserMedia({
                    video: {
                        facingMode: {
                            exact: nextFacingMode
                        },
                        width: { ideal: 1280 },
                        height: { ideal: 720 }
                    },
                    audio: false
                });

            const oldStream = cameraStream;

            cameraStream = newStream;
            currentFacingMode = nextFacingMode;

            videoPreview.srcObject = newStream;

            updateVideoMirror();

            await videoPreview.play();

            oldStream.getTracks().forEach(track => {
                track.stop();
            });

            setStatus(
                currentFacingMode === 'environment'
                    ? 'Задната камера е активна.'
                    : 'Предната камера е активна.'
            );

        } catch (error) {
            if (newStream) {
                newStream.getTracks().forEach(track => {
                    track.stop();
                });
            }

            console.error(
                '[Recorder] Camera switch failed:',
                error
            );

            setStatus(
                'Не можа да се запише.',
                4500,
                true
            );

        } finally {
            isSwitchingCamera = false;
        }
    }

    /* =====================================================
       11. STOP CAMERA
       ===================================================== */

    function stopCamera() {
        if (cameraStream) {
            cameraStream.getTracks().forEach(track => {
                track.stop();
            });

            cameraStream = null;
        }

        removeVideoPreview();
    }

    /* =====================================================
       12. START RECORDING
       ===================================================== */

    async function startRecording() {
        try {
            if (
                !personContainer ||
                !playButton ||
                !stopButton
            ) {
                throw new Error(
                    'Не са намерени необходимите HTML елементи.'
                );
            }

            if (mediaRecorder?.state === 'recording') {
                return;
            }

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
                    if (
                        event.data &&
                        event.data.size > 0
                    ) {
                        recordedChunks.push(event.data);
                    }
                }
            );

            mediaRecorder.addEventListener(
                'error',
                event => {
                    shouldUpload = false;

                    console.error(
                        '[Recorder] MediaRecorder error:',
                        event
                    );

                    setStatus(
                        'Не можа да се запише.',
                        4500,
                        true
                    );

                    setButtonStates(false);
                }
            );

            mediaRecorder.addEventListener(
                'stop',
                async () => {
                    try {
                        if (shouldUpload && !pageIsClosing) {
                            await uploadRecording();
                        }
                    } finally {
                        setButtonStates(false);
                    }
                }
            );

            mediaRecorder.start(1000);

            setButtonStates(true);

            setStatus(
                'Камерата е активна. Записът започна.'
            );

        } catch (error) {
            console.error(
                '[Recorder] Could not start recording:',
                error
            );

            setStatus(
                'Не можа да се запише.',
                4500,
                true
            );

            setButtonStates(false);
        }
    }

    /* =====================================================
       13. STOP RECORDING
       ===================================================== */

    function stopRecording() {
        if (
            !mediaRecorder ||
            mediaRecorder.state !== 'recording'
        ) {
            return;
        }

        setStatus('Записът приключва...');

        if (stopButton) {
            stopButton.disabled = true;
        }

        mediaRecorder.stop();
    }

    /* =====================================================
       14. UPLOAD TO FASTAPI
       ===================================================== */

    async function uploadRecording() {
        try {
            if (!recordedChunks.length) {
                throw new Error(
                    'Няма записани видео данни.'
                );
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
                throw new Error(
                    'Видео файлът е празен.'
                );
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

            setStatus(
                'Изпращане на видеото към backend...'
            );

            // 1. Upload video.
            const response = await fetch(
                `${API_BASE_URL}/api/recordings`,
                {
                    method: 'POST',
                    body: formData
                }
            );

            const result = await response
                .json()
                .catch(() => ({}));

            if (!response.ok) {
                throw new Error(
                    result.detail ||
                    `Backend грешка: ${response.status}`
                );
            }

            if (!result.id) {
                throw new Error(
                    'Backend не върна ID на записа.'
                );
            }

            recordedChunks = [];

            console.info(
                '[Recorder] Video uploaded successfully.',
                {
                    recordingId: result.id,
                    fileSize: videoBlob.size,
                    mimeType
                }
            );

            setStatus(
                `Записът е запазен успешно! ID: ${result.id}`
            );

            // 2. Run AI gesture prediction.
            // Upload stays successful even if prediction fails.
            await runPrediction(result.id);

        } catch (error) {
            console.error(
                '[Recorder] Грешка при запис или изпращане:',
                error
            );

            setStatus(
                'Не можа да се запише.',
                4500,
                true
            );
        }
    }

    /* =====================================================
       15. AI GESTURE PREDICTION
       ===================================================== */

    async function runPrediction(recordingId) {
        try {
            console.info(
                '[Translate AI] Стартиране на разпознаването...',
                recordingId
            );

            const predictionResponse = await fetch(
                `${API_BASE_URL}/api/recordings/${encodeURIComponent(recordingId)}/predict`,
                {
                    method: 'POST',
                    headers: {
                        'Accept': 'application/json'
                    }
                }
            );

            const predictionResult = await predictionResponse
                .json()
                .catch(() => ({}));

            if (!predictionResponse.ok) {
                throw new Error(
                    predictionResult.detail ||
                    `Prediction failed: HTTP ${predictionResponse.status}`
                );
            }

            if (
                predictionResult.status !== 'success' ||
                !predictionResult.prediction
            ) {
                throw new Error(
                    'Невалиден отговор от AI системата.'
                );
            }

            const prediction =
                predictionResult.prediction;

            console.info(
                '[Translate AI] РАЗПОЗНАТ ЖЕСТ:',
                prediction.predicted_label
            );

            console.info(
                '[Translate AI] ВЕРОЯТНОСТ:',
                `${(
                    prediction.confidence * 100
                ).toFixed(2)}%`
            );

            console.table(
                prediction.top_predictions
            );

            console.info(
                '[Translate AI] ПЪЛЕН РЕЗУЛТАТ:',
                prediction
            );

            return prediction;

        } catch (error) {
            // Видеото вече е качено.
            // Грешка в AI не изтрива и не отменя записа.
            console.error(
                '[Translate AI] Грешка при разпознаването:',
                error
            );

            return null;
        }
    }

    /* =====================================================
       16. FLOATING PANEL — DRAG AND SNAP
       ===================================================== */

    let dragState = null;
    let suppressNextClick = false;

    function clamp(value, min, max) {
        return Math.min(
            Math.max(value, min),
            Math.max(min, max)
        );
    }

    function movePanelTo(left, top) {
        if (!controlsPanel || !phoneScreen) return;

        const maxLeft =
            phoneScreen.clientWidth -
            controlsPanel.offsetWidth;

        const maxTop =
            phoneScreen.clientHeight -
            controlsPanel.offsetHeight;

        const safeLeft = clamp(left, 0, maxLeft);
        const safeTop = clamp(top, 0, maxTop);

        controlsPanel.style.left = `${safeLeft}px`;
        controlsPanel.style.top = `${safeTop}px`;

        controlsPanel.style.right = 'auto';
        controlsPanel.style.bottom = 'auto';
    }

    function snapPanelToNearestEdge() {
        if (!controlsPanel || !phoneScreen) return;

        const panelRect =
            controlsPanel.getBoundingClientRect();

        const phoneRect =
            phoneScreen.getBoundingClientRect();

        const panelWidth = controlsPanel.offsetWidth;
        const panelHeight = controlsPanel.offsetHeight;

        const phoneWidth = phoneScreen.clientWidth;
        const phoneHeight = phoneScreen.clientHeight;

        const currentLeft =
            panelRect.left -
            phoneRect.left -
            phoneScreen.clientLeft;

        const currentTop =
            panelRect.top -
            phoneRect.top -
            phoneScreen.clientTop;

        const distances = {
            top: currentTop,
            right: phoneWidth - currentLeft - panelWidth,
            bottom: phoneHeight - currentTop - panelHeight,
            left: currentLeft
        };

        const nearestEdge = Object.keys(distances).reduce(
            (nearest, edge) =>
                distances[edge] < distances[nearest]
                    ? edge
                    : nearest,
            'top'
        );

        let finalLeft = currentLeft;
        let finalTop = currentTop;

        switch (nearestEdge) {
            case 'top':
                finalTop = 0;
                break;

            case 'bottom':
                finalTop = phoneHeight - panelHeight;
                break;

            case 'left':
                finalLeft = 0;
                break;

            case 'right':
                finalLeft = phoneWidth - panelWidth;
                break;
        }

        movePanelTo(finalLeft, finalTop);
    }

    function startPanelDrag(event) {
        if (!controlsPanel || !phoneScreen) return;

        if (
            event.button !== undefined &&
            event.button !== 0
        ) {
            return;
        }

        if (event.target.closest('button')) {
            return;
        }

        const panelRect =
            controlsPanel.getBoundingClientRect();

        const phoneRect =
            phoneScreen.getBoundingClientRect();

        dragState = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,

            startLeft:
                panelRect.left -
                phoneRect.left -
                phoneScreen.clientLeft,

            startTop:
                panelRect.top -
                phoneRect.top -
                phoneScreen.clientTop,

            moved: false
        };

        controlsPanel.setPointerCapture(
            event.pointerId
        );

        event.preventDefault();
    }

    function movePanelDrag(event) {
        if (
            !dragState ||
            event.pointerId !== dragState.pointerId
        ) {
            return;
        }

        const deltaX =
            event.clientX - dragState.startX;

        const deltaY =
            event.clientY - dragState.startY;

        if (
            Math.abs(deltaX) > 5 ||
            Math.abs(deltaY) > 5
        ) {
            dragState.moved = true;
        }

        movePanelTo(
            dragState.startLeft + deltaX,
            dragState.startTop + deltaY
        );
    }

    function finishPanelDrag(event) {
        if (
            !dragState ||
            event.pointerId !== dragState.pointerId
        ) {
            return;
        }

        const wasMoved = dragState.moved;

        dragState = null;

        if (wasMoved) {
            suppressNextClick = true;

            setTimeout(() => {
                suppressNextClick = false;
            }, 250);

            snapPanelToNearestEdge();
        }
    }

    function preventClickAfterDrag(event) {
        if (!suppressNextClick) return;

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();

        suppressNextClick = false;
    }

    function initializeFloatingPanel() {
        if (!controlsPanel) return;

        controlsPanel.addEventListener(
            'pointerdown',
            startPanelDrag
        );

        controlsPanel.addEventListener(
            'pointermove',
            movePanelDrag
        );

        controlsPanel.addEventListener(
            'pointerup',
            finishPanelDrag
        );

        controlsPanel.addEventListener(
            'pointercancel',
            finishPanelDrag
        );

        controlsPanel.addEventListener(
            'click',
            preventClickAfterDrag,
            true
        );

        window.addEventListener('resize', () => {
            if (!controlsPanel.style.left) return;

            const currentLeft =
                parseFloat(controlsPanel.style.left) || 0;

            const currentTop =
                parseFloat(controlsPanel.style.top) || 0;

            movePanelTo(currentLeft, currentTop);
            snapPanelToNearestEdge();
        });
    }

    /* =====================================================
       17. EVENT LISTENERS
       ===================================================== */

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

    if (switchCameraButton) {
        switchCameraButton.addEventListener(
            'click',
            switchCamera
        );

        switchCameraButton.addEventListener(
            'keydown',
            event => {
                if (
                    event.key === 'Enter' ||
                    event.key === ' '
                ) {
                    event.preventDefault();
                    switchCamera();
                }
            }
        );
    }

    /* =====================================================
       18. PAGE CLEANUP
       ===================================================== */

    window.addEventListener('pagehide', () => {
        pageIsClosing = true;
        shouldUpload = false;

        if (mediaRecorder?.state === 'recording') {
            mediaRecorder.stop();
        }

        stopCamera();
    });

    /* =====================================================
       19. INITIALIZATION
       ===================================================== */

    setButtonStates(false);

    if (statusElement) {
        statusElement.hidden = true;
    }

    initializeFloatingPanel();

    setStatus(
        'Натисни бутона за старт, за да включиш камерата.'
    );

})();
