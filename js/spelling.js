
/* =========================================================
   Translate App — spelling.js
   Диктовка, прочитане, превод чрез 3D аватар.
   Език: Български (bg-BG)
   ========================================================= */

(function () {
    'use strict';

    const textInput = document.getElementById('textInput');
    const dictationButton = document.getElementById('dictationButton');
    const speakButton = document.getElementById('speakButton');
    const translateButton = document.getElementById('translateButton');
    const clearButton = document.getElementById('clearTextButton');
    const statusElement = document.getElementById('textStatus');

    if (
        !textInput ||
        !dictationButton ||
        !speakButton ||
        !translateButton ||
        !clearButton ||
        !statusElement
    ) {
        console.error('Липсва необходим HTML елемент.');
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
    // DICTATION
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
                setStatus('Няма разрешение за микрофона.');
            } else if (event.error === 'no-speech') {
                setStatus('Не беше разпозната реч.');
            } else if (event.error !== 'aborted') {
                setStatus('Грешка при диктовката: ' + event.error);
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
                setStatus('Не може да се стартира диктовката.');
            }
        });

    } else {
        dictationButton.addEventListener('click', function () {
            setStatus('Браузърът не поддържа диктовка. Използвай Chrome.');
        });
    }

    // -----------------------------------------------------
    // READ TEXT ALOUD
    // -----------------------------------------------------

    speakButton.addEventListener('click', function () {
        const text = textInput.value.trim();

        if (!text) {
            setStatus('Първо въведи текст за прочитане.');
            textInput.focus();
            return;
        }

        if (!('speechSynthesis' in window)) {
            setStatus('Браузърът не поддържа прочитане на текст.');
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
            setStatus('Грешка при прочитането.');
        };

        window.speechSynthesis.speak(utterance);
    });

    // -----------------------------------------------------
    // TRANSLATE WITH 3D AVATAR
    // -----------------------------------------------------

    translateButton.addEventListener('click', async function () {
        const text = textInput.value.trim();

        if (!text) {
            setStatus('Първо въведи текст за превод.');
            textInput.focus();
            return;
        }

        if (
            !window.TranslateAvatar ||
            typeof window.TranslateAvatar.play !== 'function'
        ) {
            setStatus('3D аватарът все още се зарежда. Опитай отново.');
            return;
        }

        translateButton.disabled = true;
        setStatus('Изпращане на текста към 3D аватара...');

        try {
            const result = await window.TranslateAvatar.play(text);

            if (result && result.success) {
                setStatus(
                    'Преводът приключи. Изпълнени жестове: ' +
                    result.played
                );
            } else {
                setStatus(
                    'Не бяха изпълнени жестове. Провери въведения текст и каталога.'
                );
            }

        } catch (error) {
            console.error('Грешка при превода:', error);
            setStatus('Грешка при превода: ' + error.message);

        } finally {
            translateButton.disabled = false;
        }
    });

    // -----------------------------------------------------
    // CLEAR TEXT
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

        if (
            window.TranslateAvatar &&
            typeof window.TranslateAvatar.stop === 'function'
        ) {
            window.TranslateAvatar.stop();
        }

        setStatus('Текстът е изчистен.');
        textInput.focus();
    });

    // -----------------------------------------------------
    // MANUAL TYPING
    // -----------------------------------------------------

    textInput.addEventListener('input', function () {
        if (textInput.value.trim()) {
            setStatus('Текстът е готов за превод.');
        } else {
            setStatus('Въведи текст, за да започнеш.');
        }
    });

})();
