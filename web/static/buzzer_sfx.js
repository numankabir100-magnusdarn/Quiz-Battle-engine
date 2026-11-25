/**
 * buzzer_sfx.js — EEECi FA'26 EEE Brain Battle
 * Realistic game-show electromechanical relay buzzer synthesis.
 * 100% offline — pure Web Audio API, zero external files.
 * Exposed as window.QuizBuzzerSFX
 */
(function (global) {
  'use strict';

  /* ── Storage key ─────────────────────────────────────────── */
  var MUTE_KEY = 'eeeci_sfx_muted';

  /* ── AudioContext singleton ──────────────────────────────── */
  var _ctx = null;

  function _ensureCtx() {
    if (_ctx) {
      if (_ctx.state === 'suspended') _ctx.resume();
      return _ctx;
    }
    var AC = global.AudioContext || global.webkitAudioContext;
    if (!AC) return null;
    _ctx = new AC();
    return _ctx;
  }

  /* ── Browser audio-unlock (mobile Chrome/Safari) ─────────── */
  function _unlockOnGesture() {
    var events = ['pointerdown', 'touchstart', 'keydown'];
    function unlock() {
      _ensureCtx();
      events.forEach(function (ev) {
        document.removeEventListener(ev, unlock, true);
      });
    }
    events.forEach(function (ev) {
      document.addEventListener(ev, unlock, { capture: true, passive: true });
    });
  }

  /* ── Mute state ───────────────────────────────────────────── */
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

  /* ── Low-level helpers ───────────────────────────────────── */

  /**
   * Filtered white-noise burst — simulates relay/solenoid click transient.
   * @param {AudioContext} ctx
   * @param {number} durationSec
   * @param {number} freqHz   bandpass centre
   * @param {number} gain     peak gain
   */
  function _noiseClick(ctx, durationSec, freqHz, gain) {
    var bufSize = Math.ceil(ctx.sampleRate * durationSec);
    var buf = ctx.createBuffer(1, bufSize, ctx.sampleRate);
    var data = buf.getChannelData(0);
    for (var i = 0; i < bufSize; i++) {
      data[i] = (Math.random() * 2 - 1);
    }
    var src = ctx.createBufferSource();
    src.buffer = buf;

    // Bandpass around the mechanical click frequency
    var bp = ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = freqHz;
    bp.Q.value = 2.5;

    var gNode = ctx.createGain();
    var now = ctx.currentTime;
    gNode.gain.setValueAtTime(0.0001, now);
    gNode.gain.exponentialRampToValueAtTime(gain, now + 0.002);
    gNode.gain.exponentialRampToValueAtTime(0.0001, now + durationSec);

    src.connect(bp);
    bp.connect(gNode);
    gNode.connect(ctx.destination);
    src.start(now);
    src.stop(now + durationSec + 0.005);
  }

  /**
   * Oscillator with ADSR into a lowpass resonant filter.
   * @param {AudioContext} ctx
   * @param {number} freq       fundamental Hz
   * @param {string} type       OscillatorType
   * @param {number} detune     cents
   * @param {number} gain       peak gain
   * @param {number} attack     sec
   * @param {number} sustain    sec
   * @param {number} release    sec
   * @param {number} lpFreq     lowpass cutoff Hz
   * @param {number} lpQ        lowpass Q
   * @param {number} delay      start delay sec
   */
  function _oscLayer(ctx, freq, type, detune, gain, attack, sustain, release, lpFreq, lpQ, delay) {
    var osc = ctx.createOscillator();
    osc.type = type;
    osc.frequency.value = freq;
    osc.detune.value = detune || 0;

    var lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = lpFreq || 950;
    lp.Q.value = lpQ || 3.5;

    var gNode = ctx.createGain();
    var now = ctx.currentTime + (delay || 0);
    gNode.gain.setValueAtTime(0.0001, now);
    gNode.gain.exponentialRampToValueAtTime(gain, now + attack);
    gNode.gain.setValueAtTime(gain, now + attack + sustain);
    gNode.gain.exponentialRampToValueAtTime(0.0001, now + attack + sustain + release);

    osc.connect(lp);
    lp.connect(gNode);
    gNode.connect(ctx.destination);

    var total = (delay || 0) + attack + sustain + release + 0.02;
    osc.start(now);
    osc.stop(ctx.currentTime + total);
  }

  /* ── Main buzzer synthesis ───────────────────────────────── */

  /**
   * Play a realistic game-show electromechanical relay buzzer.
   * @param {'A'|'B'|'STAGE'} variant
   */
  function playRealBuzzer(variant) {
    if (_muted) return;
    var ctx = _ensureCtx();
    if (!ctx) return;

    // Frequencies per variant
    //   A: 142 Hz (fundamental)  + 284 Hz (octave)
    //   B: 168 Hz (fundamental)  + 336 Hz (octave)
    //   STAGE: 148 + 222 Hz chord
    var f1, f2;
    if (variant === 'B') {
      f1 = 168; f2 = 336;
    } else if (variant === 'STAGE') {
      f1 = 148; f2 = 222;
    } else {
      f1 = 142; f2 = 284; // A (default)
    }

    // 1. Relay click transient (12 ms noise burst at 800 Hz bandpass)
    _noiseClick(ctx, 0.012, 800, 0.35);

    // 2. Rich harmonic buzz — sawtooth fundamental
    _oscLayer(ctx, f1, 'sawtooth', 0,   0.22, 0.005, 0.360, 0.065, 950, 3.5, 0.002);
    // 3. Square octave (adds clang)
    _oscLayer(ctx, f2, 'square',   0,   0.10, 0.005, 0.330, 0.055, 950, 3.5, 0.003);
    // 4. Slight detuned sawtooth for width
    _oscLayer(ctx, f1, 'sawtooth', 12,  0.08, 0.008, 0.310, 0.060, 950, 3.5, 0.004);
  }

  /* ── Helper cues ─────────────────────────────────────────── */

  /**
   * Low double-pulse warning: used when -5 steal passes to opposing team.
   */
  function playPassOver() {
    if (_muted) return;
    var ctx = _ensureCtx();
    if (!ctx) return;
    // Two descending pulses
    _oscLayer(ctx, 320, 'triangle', 0, 0.12, 0.010, 0.080, 0.050, 600, 2, 0.000);
    _oscLayer(ctx, 260, 'triangle', 0, 0.10, 0.010, 0.080, 0.050, 600, 2, 0.160);
  }

  /**
   * Subtle crisp chime when buzzers re-arm.
   */
  function playArmReset() {
    if (_muted) return;
    var ctx = _ensureCtx();
    if (!ctx) return;
    _oscLayer(ctx, 880,  'sine', 0, 0.07, 0.008, 0.060, 0.080, 2000, 1, 0.000);
    _oscLayer(ctx, 1320, 'sine', 0, 0.05, 0.008, 0.050, 0.070, 2000, 1, 0.055);
  }

  /* ── Public API ──────────────────────────────────────────── */
  var QuizBuzzerSFX = {
    playRealBuzzer: playRealBuzzer,
    playPassOver:   playPassOver,
    playArmReset:   playArmReset,

    setMuted: function (val) {
      _muted = !!val;
      _saveMuted(_muted);
    },
    isMuted: function () {
      return _muted;
    },
    /** Force AudioContext init (call from a user gesture handler). */
    unlock: function () {
      _ensureCtx();
    }
  };

  global.QuizBuzzerSFX = QuizBuzzerSFX;

  // Auto-attach gesture unlock
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _unlockOnGesture);
  } else {
    _unlockOnGesture();
  }

}(typeof window !== 'undefined' ? window : this));
