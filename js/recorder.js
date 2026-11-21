
'use strict';

/* =========================================================
   Translate App — Camera Recorder
   Backend: FastAPI
   Endpoint: POST /api/recordings
   ========================================================= */

const API_BASE_URL = 'http://127.0.0.1:8000';

const preview = document.getElementById('cameraPreview');
const placeholder = document.getElementById('cameraPlaceholder');

const translatedText = document.getElementById('translatedText');
const translateButton = document.getElementById('translateButton');

const startButton = document.getElementById('startRecording');
const stopButton = document.getElementById('stopRecording');

const participantInput = document.getElementById('participantId');
const labelInput = document.getElementById('recordingLabel');
const consentInput = document.getElementById('recordingConsent');

const statusElement = document.getElementById('cameraStatus');

let cameraStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let selectedMimeType = '';

function setStatus(message) {
    statusElement.textContent = message;
}

function getSupportedMimeType() {
    const candidates = [
        'video/webm;codecs=vp9',
        'video/webm;codecs=vp8',
        'video/webm',
        'video/mp4'
    ];

    if (!window.MediaRecorder) {
        throw new Error(
            'Този браузър не поддържа MediaRecorder.'
        );
    }

    for (const type of candidates) {
        if (MediaRecorder.isTypeSupported(type)) {
            return type;
        }
    }

    return '';
}

async function startCamera() {
    if (cameraStream) {
        return;
    }

    if (!navigator.mediaDevices ||
        !navigator.mediaDevices.getUserMedia) {
        throw new Error(
            'Браузърът не поддържа достъп до камерата. ' +
            'Използвай HTTPS или localhost.'
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

    preview.srcObject = cameraStream;

    placeholder.hidden = true;

    await preview.play();
}

function validateForm() {
    const participantId = participantInput.value.trim();

    if (!/^[A-Za-z0-9_-]{3,40}$/.test(participantId)) {
        throw new Error(
            'ID на участник трябва да съдържа 3–40 ' +
            'букви, цифри, тирета или долни черти.'
        );
    }

    if (!consentInput.checked) {
        throw new Error(
            'Необходимо е съгласие за съхранение на видеото.'
        );
    }

   return {
    participantId,
    label: translatedText.value.trim()
};
}

async function startRecording() {
    try {
        validateForm();

        setStatus('Стартиране на камерата...');

        await startCamera();

        recordedChunks = [];

        selectedMimeType = getSupportedMimeType();

        const options = selectedMimeType
            ? { mimeType: selectedMimeType }
            : undefined;

        mediaRecorder = new MediaRecorder(
            cameraStream,
            options
        );

        mediaRecorder.ondataavailable = function (event) {
            if (event.data && event.data.size > 0) {
                recordedChunks.push(event.data);
            }
        };

        mediaRecorder.onerror = function (event) {
            setStatus(
                'Грешка при запис: ' +
                (event.error?.message || 'неизвестна грешка')
            );

            startButton.disabled = false;
            stopButton.disabled = true;
        };

        mediaRecorder.onstop = async function () {
            await uploadRecording();
        };

        mediaRecorder.start(1000);

        startButton.disabled = true;
        stopButton.disabled = false;

        setStatus('Записът е активен.');
    } catch (error) {
        setStatus(error.message);
    }
}

function stopRecording() {
    if (!mediaRecorder ||
        mediaRecorder.state !== 'recording') {
        return;
    }

    stopButton.disabled = true;

    setStatus('Записът приключва...');

    mediaRecorder.stop();
}

async function uploadRecording() {
    try {
        const { participantId, label } = validateForm();

        const mimeType =
            mediaRecorder.mimeType ||
            selectedMimeType ||
            'video/webm';

        const extension = mimeType.includes('mp4')
            ? 'mp4'
            : 'webm';

        const blob = new Blob(recordedChunks, {
            type: mimeType
        });

        if (blob.size === 0) {
            throw new Error('Полученият видео файл е празен.');
        }

        const formData = new FormData();

        formData.append(
            'file',
            blob,
            `recording-${Date.now()}.${extension}`
        );

        formData.append('participant_id', participantId);
        formData.append('consent', 'true');
        formData.append('label', label);

        setStatus('Качване на видеото към backend...');

        const response = await fetch(
            `${API_BASE_URL}/api/recordings`,
            {
                method: 'POST',
                body: formData
            }
        );

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.detail ||
                `Backend грешка: ${response.status}`
            );
        }

        setStatus(
            `Успешен запис! ID: ${result.id}`
        );

        recordedChunks = [];

        startButton.disabled = false;
        stopButton.disabled = true;

    } catch (error) {
        setStatus(
            `Неуспешно качване: ${error.message}`
        );

        startButton.disabled = false;
        stopButton.disabled = true;
    }
}

function stopCamera() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => {
            track.stop();
        });

        cameraStream = null;
        preview.srcObject = null;
        placeholder.hidden = false;
    }
}

startButton.addEventListener(
    'click',
    startRecording
);

stopButton.addEventListener(
    'click',
    stopRecording
);

window.addEventListener('pagehide', stopCamera);

setStatus('Готовност за стартиране на камерата.');

translateButton.addEventListener('click', function () {
    if (!translatedText.value.trim()) {
        setStatus('Няма текст за превод.');
        return;
    }

    setStatus(
        'Текстът е готов за превод. Модулът за разпознаване още се разработва.'
    );
});