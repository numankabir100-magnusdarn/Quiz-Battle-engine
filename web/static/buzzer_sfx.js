/**
 * buzzer_sfx.js — EEECi FA'26 EEE Brain Battle
 * Authentic 60Hz electromagnetic coil game-show buzzer ("BZZZZT!")
 * 100% offline — pure Web Audio API synthesis, zero external files.
 * Exposed as window.QuizBuzzerSFX
 */
(function (global) {
  'use strict';

  var MUTE_KEY = 'eeeci_sfx_muted';
  var _ctx = null;
  var _shaperCurve = null;

  function _getCtx() {
    if (!_ctx) {
      var AC = global.AudioContext || global.webkitAudioContext;
      if (!AC) return null;
      _ctx = new AC();
    }
    return _ctx;
  }

  function _resumeCtx() {
    var ctx = _getCtx();
    if (!ctx) return Promise.resolve(null);
    if (ctx.state === 'suspended') {
      return ctx.resume().then(function () { return ctx; }).catch(function () { return ctx; });
    }
    return Promise.resolve(ctx);
  }

  /* ── Bulletproof Desktop & Mobile AudioContext Unlock ─────── */
  function _attachUnlockListeners() {
    var events = ['pointerdown', 'mousedown', 'touchstart', 'click', 'keydown'];
    function handleGesture() {
      _resumeCtx();
    }
    for (var i = 0; i < events.length; i++) {
      document.addEventListener(events[i], handleGesture, { capture: true, passive: true });
    }
  }

  /* ── Mute state (localStorage: eeeci_sfx_muted) ──────────── */
  function _loadMuted() {
    try {
      return localStorage.getItem(MUTE_KEY) === 'true';
    } catch (e) {
      return false;
    }
  }

  function _saveMuted(val) {
    try {
      localStorage.setItem(MUTE_KEY, val ? 'true' : 'false');
    } catch (e) { /* storage unavailable */ }
  }

  var _muted = _loadMuted();

  /* ── Soft-clipping WaveShaper curve ──────────────────────── */
  function _getSoftClipCurve() {
    if (_shaperCurve) return _shaperCurve;
    var n = 1024;
    var curve = new Float32Array(n);
    var drive = 3.2;
    for (var i = 0; i < n; i++) {
      var x = (i * 2) / n - 1;
      curve[i] = Math.tanh(drive * x);
    }
    _shaperCurve = curve;
    return curve;
  }

  /* ── Solenoid click transient ────────────────────────────── */
  function _noiseClick(ctx, dest, durationSec, freqHz, gain) {
    var bufSize = Math.max(1, Math.ceil(ctx.sampleRate * durationSec));
    var buf = ctx.createBuffer(1, bufSize, ctx.sampleRate);
    var data = buf.getChannelData(0);
    for (var i = 0; i < bufSize; i++) {
      data[i] = Math.random() * 2 - 1;
    }
    var src = ctx.createBufferSource();
    src.buffer = buf;

    var bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = freqHz;
    bp.Q.value = 2.0;

    var gNode = ctx.createGain();
    var now = ctx.currentTime;
    gNode.gain.setValueAtTime(0.0001, now);
    gNode.gain.exponentialRampToValueAtTime(gain, now + 0.002);
    gNode.gain.exponentialRampToValueAtTime(0.0001, now + durationSec);

    src.connect(bp);
    bp.connect(gNode);
    gNode.connect(dest);
    src.start(now);
    src.stop(now + durationSec + 0.005);
  }

  /* ── Simple helper oscillator for cues ───────────────────── */
  function _cueTone(ctx, freq, type, gain, attack, sustain, release, delay) {
    var osc = ctx.createOscillator();
    osc.type = type;
    osc.frequency.value = freq;

    var gNode = ctx.createGain();
    var now = ctx.currentTime + (delay || 0);
    gNode.gain.setValueAtTime(0.0001, now);
    gNode.gain.exponentialRampToValueAtTime(gain, now + attack);
    gNode.gain.setValueAtTime(gain, now + attack + sustain);
    gNode.gain.exponentialRampToValueAtTime(0.0001, now + attack + sustain + release);

    osc.connect(gNode);
    gNode.connect(ctx.destination);
    var total = (delay || 0) + attack + sustain + release + 0.02;
    osc.start(now);
    osc.stop(ctx.currentTime + total);
  }

  /* ── Main 60Hz Electromagnetic Coil Game-Show Buzzer ─────── */
  /**
   * Play authentic 420ms mechanical solenoid buzzer ("BZZZZT!").
   * @param {'A'|'B'|'STAGE'} variant
   */
  async function playRealBuzzer(variant) {
    if (_muted) return;
    var ctx = await _resumeCtx();
    if (!ctx) return;

    var lfoFreq;
    var harmonics;
    if (variant === 'B') {
      lfoFreq = 64;
      harmonics = [128, 192, 256];
    } else if (variant === 'STAGE') {
      lfoFreq = 60;
      harmonics = [120, 180, 240, 300];
    } else {
      lfoFreq = 58;
      harmonics = [116, 174, 232];
    }

    var now = ctx.currentTime;
    var totalDur = 0.420; // 420ms
    var attack = 0.005;
    var release = 0.065;
    var sustainEnd = totalDur - release;

    // Master ADSR envelope
    var masterEnv = ctx.createGain();
    masterEnv.gain.setValueAtTime(0.0001, now);
    masterEnv.gain.exponentialRampToValueAtTime(0.55, now + attack);
    masterEnv.gain.setValueAtTime(0.55, now + sustainEnd);
    masterEnv.gain.exponentialRampToValueAtTime(0.0001, now + totalDur);
    masterEnv.connect(ctx.destination);

    // 1. Mechanical solenoid snap at t=0
    _noiseClick(ctx, masterEnv, 0.014, 900, 0.45);

    // 2. 60Hz Armature Chatter (AM Modulator: 0.35 .. 1.0)
    var amGain = ctx.createGain();
    amGain.gain.value = 0.675; // midpoint of [0.35, 1.0]

    var lfo = ctx.createOscillator();
    lfo.type = 'square';
    lfo.frequency.value = lfoFreq;

    var lfoDepth = ctx.createGain();
    lfoDepth.gain.value = 0.325; // +/- 0.325 => [0.35, 1.0]
    lfo.connect(lfoDepth);
    lfoDepth.connect(amGain.gain);

    // 3. Resonant brass coil filter chain: WaveShaper -> Peaking(420Hz, +6dB) -> Lowpass(2400Hz) -> amGain -> masterEnv
    var shaper = ctx.createWaveShaper();
    shaper.curve = _getSoftClipCurve();
    shaper.oversample = '2x';

    var peaking = ctx.createBiquadFilter();
    peaking.type = 'peaking';
    peaking.frequency.value = 420;
    peaking.Q.value = 1.8;
    peaking.gain.value = 6.0;

    var lowpass = ctx.createBiquadFilter();
    lowpass.type = 'lowpass';
    lowpass.frequency.value = 2400;
    lowpass.Q.value = 1.4;

    shaper.connect(peaking);
    peaking.connect(lowpass);
    lowpass.connect(amGain);
    amGain.connect(masterEnv);

    // 4. Layered sawtooth + square brass coil harmonics
    var oscGainPerVoice = 0.45 / harmonics.length;
    var oscs = [];
    for (var i = 0; i < harmonics.length; i++) {
      var freq = harmonics[i];

      var saw = ctx.createOscillator();
      saw.type = 'sawtooth';
      saw.frequency.value = freq;
      var sawG = ctx.createGain();
      sawG.gain.value = oscGainPerVoice;
      saw.connect(sawG);
      sawG.connect(shaper);
      oscs.push(saw);

      var sq = ctx.createOscillator();
      sq.type = 'square';
      sq.frequency.value = freq;
      var sqG = ctx.createGain();
      sqG.gain.value = oscGainPerVoice * 0.55;
      sq.connect(sqG);
      sqG.connect(shaper);
      oscs.push(sq);
    }

    lfo.start(now);
    lfo.stop(now + totalDur + 0.02);
    for (var j = 0; j < oscs.length; j++) {
      oscs[j].start(now);
      oscs[j].stop(now + totalDur + 0.02);
    }
  }

  /* ── Additional Stage Cues ───────────────────────────────── */
  async function playPassOver() {
    if (_muted) return;
    var ctx = await _resumeCtx();
    if (!ctx) return;
    _cueTone(ctx, 320, 'triangle', 0.14, 0.010, 0.080, 0.050, 0.000);
    _cueTone(ctx, 260, 'triangle', 0.12, 0.010, 0.080, 0.050, 0.160);
  }

  async function playArmReset() {
    if (_muted) return;
    var ctx = await _resumeCtx();
    if (!ctx) return;
    _cueTone(ctx, 880, 'sine', 0.08, 0.008, 0.060, 0.080, 0.000);
    _cueTone(ctx, 1320, 'sine', 0.06, 0.008, 0.050, 0.070, 0.055);
  }

  /* ── Public API ──────────────────────────────────────────── */
  global.QuizBuzzerSFX = {
    playRealBuzzer: playRealBuzzer,
    playPassOver: playPassOver,
    playArmReset: playArmReset,
    setMuted: function (val) {
      _muted = !!val;
      _saveMuted(_muted);
    },
    isMuted: function () {
      return _muted;
    },
    unlock: function () {
      _resumeCtx();
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _attachUnlockListeners);
  } else {
    _attachUnlockListeners();
  }
}(typeof window !== 'undefined' ? window : this));
