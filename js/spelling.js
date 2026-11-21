

/* =========================================================
   Translate App — spelling.js
   Диктовка, прочитане и управление на текст.
   Език: Български (bg-BG)
   ========================================================= */

(function () {
    'use strict';

    const textInput = document.getElementById('textInput');
    const dictationButton = document.getElementById('dictationButton');
    const speakButton = document.getElementById('speakButton');
    const clearButton = document.getElementById('clearTextButton');
    const statusElement = document.getElementById('textStatus');

    if (
        !textInput ||
        !dictationButton ||
        !speakButton ||
        !clearButton ||
        !statusElement
    ) {
        return;
    }

    const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

    let recognition = null;
    let isListening = false;
    let shouldRestart = false;

    function setStatus(message) {
        statusElement.textContent = message;
    }

    // -----------------------------------------------------
    // Dictation
    // -----------------------------------------------------

    if (SpeechRecognition) {
        recognition = new SpeechRecognition();

        recognition.lang = 'bg-BG';
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.maxAlternatives = 1;

        recognition.onstart = function () {
            isListening = true;
            dictationButton.textContent = '⏹ Спри диктовката';
            setStatus('Слушам... Говори на български.');
        };

        recognition.onresult = function (event) {
            let finalText = '';
            let interimText = '';

            for (
                let i = event.resultIndex;
                i < event.results.length;
                i++
            ) {
                const transcript = event.results[i][0].transcript;

                if (event.results[i].isFinal) {
                    finalText += transcript;
                } else {
                    interimText += transcript;
                }
            }

            if (finalText.trim()) {
                const existingText = textInput.value.trimEnd();
                const separator = existingText ? ' ' : '';

                textInput.value =
                    existingText + separator + finalText.trim();

                textInput.dispatchEvent(
                    new Event('input', { bubbles: true })
                );
            }

            if (interimText) {
                setStatus('Разпознавам: ' + interimText);
            } else if (finalText) {
                setStatus('Текстът е добавен успешно.');
            }
        };

        recognition.onerror = function (event) {
            if (event.error === 'not-allowed') {
                shouldRestart = false;
                setStatus(
                    'Няма разрешение за използване на микрофона.'
                );
            } else if (event.error === 'no-speech') {
                setStatus('Не беше разпозната реч. Опитай отново.');
            } else if (event.error !== 'aborted') {
                setStatus(
                    'Грешка при диктовката: ' + event.error
                );
            }
        };

        recognition.onend = function () {
            isListening = false;
            dictationButton.textContent = '🎙 Диктовка';

            if (shouldRestart) {
                try {
                    recognition.start();
                } catch (error) {
                    shouldRestart = false;
                    setStatus('Неуспешно повторно стартиране.');
                }
            } else if (textInput.value.trim()) {
                setStatus('Диктовката приключи.');
            }
        };

        dictationButton.addEventListener('click', function () {
            if (isListening) {
                shouldRestart = false;
                recognition.stop();
                return;
            }

            try {
                shouldRestart = true;
                recognition.start();
            } catch (error) {
                shouldRestart = false;
                setStatus(
                    'Не може да се стартира диктовката. Опитай отново.'
                );
            }
        });

    } else {
        dictationButton.addEventListener('click', function () {
            setStatus(
                'Този браузър не поддържа диктовка. ' +
                'Опитай с Google Chrome.'
            );
        });
    }

    // -----------------------------------------------------
    // Read text aloud
    // -----------------------------------------------------

    speakButton.addEventListener('click', function () {
        const text = textInput.value.trim();

        if (!text) {
            setStatus('Първо въведи текст за прочитане.');
            textInput.focus();
            return;
        }

        if (!('speechSynthesis' in window)) {
            setStatus(
                'Този браузър не поддържа прочитане на текст.'
            );
            return;
        }

        window.speechSynthesis.cancel();

        const utterance = new SpeechSynthesisUtterance(text);

        utterance.lang = 'bg-BG';
        utterance.rate = 0.9;
        utterance.pitch = 1;
        utterance.volume = 1;

        utterance.onstart = function () {
            setStatus('Прочитам текста...');
        };

        utterance.onend = function () {
            setStatus('Прочитането приключи.');
        };

        utterance.onerror = function () {
            setStatus('Възникна грешка при прочитането.');
        };

        window.speechSynthesis.speak(utterance);
    });

    // -----------------------------------------------------
    // Clear text
    // -----------------------------------------------------

    clearButton.addEventListener('click', function () {
        textInput.value = '';

        if (recognition && isListening) {
            shouldRestart = false;
            recognition.stop();
        }

        if ('speechSynthesis' in window) {
            window.speechSynthesis.cancel();
        }

        setStatus('Текстът е изчистен.');
        textInput.focus();
    });

    // -----------------------------------------------------
    // Manual typing
    // -----------------------------------------------------

    textInput.addEventListener('input', function () {
        if (textInput.value.trim()) {
            setStatus('Текстът е готов за прочитане.');
        } else {
            setStatus('Въведи текст, за да започнеш.');
        }
    });

})();
