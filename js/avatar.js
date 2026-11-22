
/*
 * TRANSLATE APP — UNIVERSAL 3D AVATAR
 *
 * Поддържа:
 * 1. Вградените GLB анимации.
 * 2. Външни GLB анимации.
 * 3. Речник с думи и цели фрази.
 * 4. Най-дълго съвпадение (Longest Match).
 * 5. Последователно изпълнение на жестовете.
 * 6. Публичен API: window.TranslateAvatar.play(text).
 */

import * as THREE from
    "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js";

import { GLTFLoader } from
    "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/loaders/GLTFLoader.js";

import { OrbitControls } from
    "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/controls/OrbitControls.js";


// ---------------------------------------------------------
// CONFIGURATION
// ---------------------------------------------------------

const CONFIG = {
    modelPath: "assets/models/Athletic_man.glb",
    signsPath: "data/signs.json",

    backgroundColor: 0xd0d6dc,

    cameraFov: 35,
    cameraNear: 0.1,
    cameraFar: 100,

    modelHeight: 4.5,

    animationFade: 0.2,

    enableControls: true,

    maxAnimationQueue: 100
};


// ---------------------------------------------------------
// DOM
// ---------------------------------------------------------

const container = document.getElementById("avatarContainer");
const statusElement = document.getElementById("avatarStatus");


// ---------------------------------------------------------
// RUNTIME STATE
// ---------------------------------------------------------

let scene = null;
let camera = null;
let renderer = null;
let controls = null;

let avatar = null;
let mixer = null;

let animationFrameId = null;
let resizeObserver = null;

let manifest = {
    letters: {},
    words: {}
};

let currentAction = null;
let animationQueue = Promise.resolve();

let isInitialized = false;
let isModelLoaded = false;


// ---------------------------------------------------------
// STATUS
// ---------------------------------------------------------

function setStatus(message) {
    if (statusElement) {
        statusElement.textContent = message;
    }

    console.info("[TranslateAvatar]", message);
}


// ---------------------------------------------------------
// ERROR HANDLING
// ---------------------------------------------------------

function showError(message, error = null) {
    console.error("[TranslateAvatar]", message, error || "");
    setStatus(message);
}


// ---------------------------------------------------------
// VALIDATION
// ---------------------------------------------------------

if (!container) {
    console.error(
        "[TranslateAvatar] Липсва елементът #avatarContainer."
    );
}

if (!statusElement) {
    console.warn(
        "[TranslateAvatar] Липсва елементът #avatarStatus."
    );
}


// ---------------------------------------------------------
// THREE.JS INITIALIZATION
// ---------------------------------------------------------

function initializeScene() {
    if (!container) {
        throw new Error("Не е намерен #avatarContainer.");
    }

    scene = new THREE.Scene();

    scene.background = new THREE.Color(
        CONFIG.backgroundColor
    );

    camera = new THREE.PerspectiveCamera(
        CONFIG.cameraFov,
        1,
        CONFIG.cameraNear,
        CONFIG.cameraFar
    );

    camera.position.set(0, 2.85, 7.2);
    camera.lookAt(0, 2.85, 0);

    renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: false
    });

    renderer.setPixelRatio(
        Math.min(window.devicePixelRatio || 1, 2)
    );

    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    renderer.domElement.style.position = "absolute";
    renderer.domElement.style.inset = "0";
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";
    renderer.domElement.style.zIndex = "0";

    container.style.position = "relative";
    container.style.overflow = "hidden";

    if (statusElement) {
        statusElement.style.position = "relative";
        statusElement.style.zIndex = "1";
        statusElement.style.pointerEvents = "none";
    }

    container.appendChild(renderer.domElement);

    const ambientLight = new THREE.HemisphereLight(
        0xffffff,
        0x777777,
        2
    );

    scene.add(ambientLight);

    const mainLight = new THREE.DirectionalLight(
        0xffffff,
        2.5
    );

    mainLight.position.set(4, 7, 6);
    mainLight.castShadow = true;

    scene.add(mainLight);

    const fillLight = new THREE.DirectionalLight(
        0xffffff,
        1
    );

    fillLight.position.set(-4, 3, -4);

    scene.add(fillLight);

    if (CONFIG.enableControls) {
        controls = new OrbitControls(
            camera,
            renderer.domElement
        );

        controls.enableDamping = true;
        controls.dampingFactor = 0.06;

        controls.minDistance = 2;
        controls.maxDistance = 12;

        controls.target.set(0, 2.85, 0);
        controls.maxPolarAngle = Math.PI * 0.85;

        controls.update();
    }

    updateRendererSize();

    resizeObserver = new ResizeObserver(() => {
        updateRendererSize();
    });

    resizeObserver.observe(container);

    animate();

    isInitialized = true;
}


// ---------------------------------------------------------
// RESPONSIVE RESIZE
// ---------------------------------------------------------

function updateRendererSize() {
    if (!container || !renderer || !camera) {
        return;
    }

    const width = Math.max(
        container.clientWidth,
        1
    );

    const height = Math.max(
        container.clientHeight,
        230
    );

    renderer.setSize(width, height, false);

    camera.aspect = width / height;

    camera.updateProjectionMatrix();
}


// ---------------------------------------------------------
// RENDER LOOP
// ---------------------------------------------------------

const clock = new THREE.Clock();

function animate() {
    animationFrameId = requestAnimationFrame(animate);

    const delta = Math.min(
        clock.getDelta(),
        0.05
    );

    if (mixer) {
        mixer.update(delta);
    }

    if (controls) {
        controls.update();
    }

    if (renderer && scene && camera) {
        renderer.render(scene, camera);
    }
}


// ---------------------------------------------------------
// LOAD BASE MODEL
// ---------------------------------------------------------

async function loadAvatarModel() {
    setStatus("Зареждане на 3D аватара...");

    const loader = new GLTFLoader();

    const gltf = await loader.loadAsync(
        CONFIG.modelPath
    );

    avatar = gltf.scene;

    if (!avatar) {
        throw new Error(
            "GLB файлът не съдържа валидна 3D сцена."
        );
    }

    avatar.traverse((object) => {
        if (object.isMesh) {
            object.castShadow = true;
            object.receiveShadow = true;

            if (object.material) {
                object.material.needsUpdate = true;
            }
        }
    });

    const initialBox = new THREE.Box3().setFromObject(
        avatar
    );

    const initialSize = new THREE.Vector3();
    const initialCenter = new THREE.Vector3();

    initialBox.getSize(initialSize);
    initialBox.getCenter(initialCenter);

    if (initialSize.y <= 0) {
        throw new Error(
            "Не може да бъде определена височината на модела."
        );
    }

    avatar.position.sub(initialCenter);

    const scale = CONFIG.modelHeight / initialSize.y;

    avatar.scale.setScalar(scale);

    const scaledBox = new THREE.Box3().setFromObject(
        avatar
    );

    avatar.position.y -= scaledBox.min.y;

    scene.add(avatar);

    mixer = new THREE.AnimationMixer(avatar);

    const embeddedAnimations = gltf.animations || [];

    console.info(
        "[TranslateAvatar] Вградени анимации:",
        embeddedAnimations.map(animation => animation.name)
    );

    isModelLoaded = true;

    setStatus(
        embeddedAnimations.length > 0
            ? `Аватарът е зареден. Открити анимации: ${embeddedAnimations.length}.`
            : "Аватарът е зареден. Все още няма открити анимации."
    );

    return embeddedAnimations;
}


// ---------------------------------------------------------
// LOAD SIGNS MANIFEST
// ---------------------------------------------------------

async function loadManifest() {
    setStatus("Зареждане на каталога с жестове...");

    const response = await fetch(CONFIG.signsPath, {
        cache: "no-cache"
    });

    if (!response.ok) {
        throw new Error(
            `Неуспешно зареждане на signs.json: HTTP ${response.status}`
        );
    }

    const data = await response.json();

    if (
        !data ||
        typeof data !== "object" ||
        Array.isArray(data)
    ) {
        throw new Error(
            "Невалидна структура на signs.json."
        );
    }

    manifest = {
        ...data,
        letters: data.letters || {},
        words: data.words || {}
    };

    console.info(
        "[TranslateAvatar] Каталогът е зареден.",
        manifest
    );

    return manifest;
}


// ---------------------------------------------------------
// TEXT NORMALIZATION
// ---------------------------------------------------------

function normalizeText(value) {
    return String(value)
        .normalize("NFC")
        .trim()
        .toLocaleLowerCase("bg-BG")
        .replace(/\s+/g, " ");
}


// ---------------------------------------------------------
// FIND SIGN IN MANIFEST
// ---------------------------------------------------------

function findSign(token) {
    const normalized = normalizeText(token);

    const words = manifest.words || {};
    const letters = manifest.letters || {};

    for (const [key, value] of Object.entries(words)) {
        if (normalizeText(key) === normalized) {
            return {
                type: "word",
                key,
                definition: value
            };
        }
    }

    for (const [key, value] of Object.entries(letters)) {
        if (normalizeText(key) === normalized) {
            return {
                type: "letter",
                key,
                definition: value
            };
        }
    }

    return null;
}


// ---------------------------------------------------------
// LONGEST MATCH TOKENIZER
// ---------------------------------------------------------

function tokenizeText(text) {
    const normalized = normalizeText(text);

    if (!normalized) {
        return [];
    }

    const words = manifest.words || {};
    const letters = manifest.letters || {};

    // Събираме всички ключове от речника.
    const dictionaryKeys = [
        ...Object.keys(words),
        ...Object.keys(letters)
    ]
        .map(key => normalizeText(key))
        .filter(Boolean);

    // Премахваме дублираните ключове.
    const uniqueKeys = [...new Set(dictionaryKeys)];

    // Сортираме от най-дългата фраза към най-късата.
    uniqueKeys.sort((a, b) => {
        const wordDifference =
            b.split(" ").length - a.split(" ").length;

        return wordDifference || b.length - a.length;
    });

    const tokens = normalized.split(/\s+/);

    const result = [];

    let index = 0;

    while (index < tokens.length) {
        let matchedKey = null;

        // Търсим най-дългото съвпадение от текущата позиция.
        for (const key of uniqueKeys) {
            const keyTokens = key.split(/\s+/);

            const candidate = tokens
                .slice(index, index + keyTokens.length)
                .join(" ");

            if (
                candidate === key &&
                keyTokens.length <= tokens.length - index
            ) {
                matchedKey = key;
                break;
            }
        }

        if (matchedKey) {
            result.push(matchedKey);

            index += matchedKey.split(/\s+/).length;
        } else {
            // Ако няма дума или фраза, оставяме
            // отделния токен за търсене на буква.
            result.push(tokens[index]);

            index++;
        }
    }

    return result;
}


// ---------------------------------------------------------
// GET ANIMATION CONFIGURATION
// ---------------------------------------------------------

function getAnimationConfig(sign) {
    const definition = sign.definition;

    if (typeof definition === "string") {
        return {
            animation: definition
        };
    }

    if (!definition || typeof definition !== "object") {
        return null;
    }

    return definition;
}


// ---------------------------------------------------------
// CHECK ANIMATION TRACK COMPATIBILITY
// ---------------------------------------------------------

function getAvatarNodeNames() {
    const names = new Set();

    if (!avatar) {
        return names;
    }

    avatar.traverse((object) => {
        if (object.name) {
            names.add(object.name);
        }
    });

    return names;
}


function isClipCompatible(clip) {
    if (!clip || !clip.tracks || clip.tracks.length === 0) {
        return false;
    }

    const avatarNames = getAvatarNodeNames();

    let matchingTracks = 0;

    for (const track of clip.tracks) {
        const nodeName = track.name.split(".")[0];

        if (avatarNames.has(nodeName)) {
            matchingTracks++;
        }
    }

    return matchingTracks > 0;
}


// ---------------------------------------------------------
// GET CLIP FROM BASE MODEL
// ---------------------------------------------------------

function findEmbeddedClip(clipName) {
    if (!avatar || !mixer) {
        return null;
    }

    const clips = avatar.userData.embeddedAnimations || [];

    if (!clipName) {
        return clips.length === 1 ? clips[0] : null;
    }

    return clips.find(
        clip => clip.name === clipName
    ) || null;
}


// ---------------------------------------------------------
// LOAD EXTERNAL ANIMATION GLB
// ---------------------------------------------------------

async function loadExternalAnimation(path) {
    if (!path || typeof path !== "string") {
        throw new Error(
            "Не е зададен валиден път към анимационния файл."
        );
    }

    const loader = new GLTFLoader();

    const gltf = await loader.loadAsync(path);

    if (!gltf.animations || gltf.animations.length === 0) {
        throw new Error(
            `Във файла ${path} няма открити анимации.`
        );
    }

    return gltf.animations;
}


// ---------------------------------------------------------
// PLAY ANIMATION CLIP
// ---------------------------------------------------------

function playClip(clip, validateCompatibility = true) {
    if (!mixer || !avatar) {
        throw new Error("3D аватарът не е готов.");
    }

    if (validateCompatibility && !isClipCompatible(clip)) {
        throw new Error(
            `Анимацията "${clip.name || "без име"}" няма съвместими tracks с рига на аватара.`
        );
    }

    const nextAction = mixer.clipAction(clip);

    nextAction.reset();
    nextAction.setLoop(THREE.LoopOnce, 1);
    nextAction.clampWhenFinished = true;
    nextAction.fadeIn(CONFIG.animationFade);

    if (currentAction && currentAction !== nextAction) {
        currentAction.fadeOut(CONFIG.animationFade);
    }

    nextAction.play();

    currentAction = nextAction;

    return nextAction;
}


// ---------------------------------------------------------
// PLAY ONE SIGN
// ---------------------------------------------------------

async function playSign(sign) {
    const animationConfig = getAnimationConfig(sign);

    if (!animationConfig) {
        throw new Error(
            `Няма конфигурация за жеста "${sign.key}".`
        );
    }

    if (animationConfig.clip && !animationConfig.animation) {
        const clip = findEmbeddedClip(
            animationConfig.clip
        );

        if (!clip) {
            throw new Error(
                `Не е намерен вграден clip "${animationConfig.clip}".`
            );
        }

        return playClip(clip, false);
    }

    if (animationConfig.animation) {
        const clips = await loadExternalAnimation(
            animationConfig.animation
        );

        let clip = null;

        if (animationConfig.clip) {
            clip = clips.find(
                item => item.name === animationConfig.clip
            );
        } else {
            clip = clips[0];
        }

        if (!clip) {
            throw new Error(
                `В ${animationConfig.animation} не е намерена зададената анимация.`
            );
        }

        return playClip(clip, true);
    }

    throw new Error(
        `За "${sign.key}" няма зададен animation или clip.`
    );
}


// ---------------------------------------------------------
// PLAY TEXT
// ---------------------------------------------------------

async function playText(text) {
    if (!isModelLoaded) {
        setStatus("Аватарът все още се зарежда.");

        return {
            success: false,
            reason: "model-not-ready"
        };
    }

    const input = normalizeText(text);

    if (!input) {
        setStatus("Въведи текст за изпълнение.");

        return {
            success: false,
            reason: "empty-text"
        };
    }

    // Ново: разделяме текста чрез Longest Match.
    const tokens = tokenizeText(input);

    if (tokens.length > CONFIG.maxAnimationQueue) {
        setStatus("Текстът е прекалено дълъг.");

        return {
            success: false,
            reason: "text-too-long"
        };
    }

    console.info(
        "[TranslateAvatar] Разпозната последователност:",
        tokens
    );

    const task = async () => {
        let played = 0;

        for (const token of tokens) {
            const sign = findSign(token);

            if (!sign) {
                setStatus(
                    `Няма добавен жест за "${token}".`
                );

                continue;
            }

            try {
                setStatus(
                    `Подготовка на жеста: ${sign.key}`
                );

                const action = await playSign(sign);

                played++;

                const duration =
                    action.getClip().duration * 1000;

                await new Promise(resolve => {
                    setTimeout(
                        resolve,
                        Math.max(duration, 100)
                    );
                });

            } catch (error) {
                console.error(
                    `[TranslateAvatar] Грешка при жест "${token}":`,
                    error
                );

                setStatus(
                    `Жестът "${token}" не може да бъде изпълнен: ${error.message}`
                );
            }
        }

        if (played > 0) {
            setStatus(
                `Изпълнени са ${played} жеста.`
            );
        } else {
            setStatus(
                "Не бяха намерени изпълними жестове за този текст."
            );
        }

        return {
            success: played > 0,
            played,
            tokens
        };
    };

    animationQueue = animationQueue.then(
        task,
        task
    );

    return animationQueue;
}


// ---------------------------------------------------------
// STOP ANIMATION
// ---------------------------------------------------------

function stop() {
    if (mixer) {
        mixer.stopAllAction();
    }

    currentAction = null;

    setStatus("Анимацията е спряна.");
}


// ---------------------------------------------------------
// PUBLIC API
// ---------------------------------------------------------

window.TranslateAvatar = {
    play: playText,
    stop,

    getStatus() {
        return {
            initialized: isInitialized,
            modelLoaded: isModelLoaded,
            manifestLoaded: Boolean(manifest),
            animationPlaying: Boolean(
                currentAction && currentAction.isRunning()
            )
        };
    },

    // Позволява проверка на разделянето на фразите.
    tokenize: tokenizeText
};


// ---------------------------------------------------------
// STARTUP
// ---------------------------------------------------------

async function startAvatar() {
    try {
        if (!container) {
            return;
        }

        initializeScene();

        const embeddedAnimations = await loadAvatarModel();

        avatar.userData.embeddedAnimations = embeddedAnimations;

        await loadManifest();

        setStatus(
            embeddedAnimations.length > 0
                ? "3D аватарът е готов. Каталогът с жестове е зареден."
                : "3D аватарът е зареден, но няма открити вградени анимации. Добави съвместими жестове."
        );

    } catch (error) {
        showError(
            `Неуспешно стартиране на 3D аватара: ${error.message}`,
            error
        );
    }
}


// ---------------------------------------------------------
// CLEANUP
// ---------------------------------------------------------

window.addEventListener("beforeunload", () => {
    if (animationFrameId !== null) {
        cancelAnimationFrame(animationFrameId);
    }

    if (resizeObserver) {
        resizeObserver.disconnect();
    }

    if (controls) {
        controls.dispose();
    }

    if (renderer) {
        renderer.dispose();
    }
});


// ---------------------------------------------------------
// RUN
// ---------------------------------------------------------

startAvatar();
