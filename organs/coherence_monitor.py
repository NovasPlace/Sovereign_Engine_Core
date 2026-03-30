"""
organs/coherence_monitor.py
Sovereign Engine — Coherence Monitor
Tracks semantic drift across CortexDB interaction history.
Detects when response patterns diverge from established ground truth baselines
BEFORE drift compounds into persistent sycophancy or hallucination loops.

Architecture:
  - Embeds each response as a lightweight semantic fingerprint (TF-IDF + cosine)
  - Maintains a rolling baseline of factual ground truth anchors
  - Measures drift velocity — not just current position but rate of change
  - Emits drift alerts to CortexDB when trajectory exceeds threshold
  - Exposes <coherence_check> primitive to the organism

Wire into: invoke_agent's post-generation pipeline (after response is generated,
           before it's returned to the user or written to CortexDB)
"""

import hashlib
import json
import math
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DRIFT_WINDOW          = 10      # Rolling window of responses to track
DRIFT_ALERT_THRESHOLD = 0.35    # Cosine distance from baseline triggers alert
VELOCITY_THRESHOLD    = 0.15    # Rate of drift per response triggers early warning
SYCOPHANCY_MARKERS    = [       # Phrases that signal sycophantic drift
    "you're absolutely right",
    "you are correct",
    "i agree completely",
    "great point",
    "excellent observation",
    "you're right that",
    "as you correctly",
    "i was wrong",
    "i apologize for",
    "whatever you prefer",
    "if you believe",
    "as you said",
]
UNCERTAINTY_MARKERS = [         # Phrases that signal healthy epistemic humility
    "i'm not certain",
    "i don't know",
    "i'm unsure",
    "this may be incorrect",
    "you should verify",
    "i cannot confirm",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ResponseFingerprint:
    """Lightweight semantic representation of a single response."""
    response_id: str
    timestamp: float
    text: str
    tfidf_vector: dict           # term -> tf-idf score
    sycophancy_score: float      # 0.0 (honest) to 1.0 (fully sycophantic)
    uncertainty_score: float     # 0.0 (overconfident) to 1.0 (well-calibrated)
    length: int
    topic_hash: str              # hash of dominant terms for topic tracking


@dataclass
class DriftReading:
    """Single drift measurement between current response and baseline."""
    response_id: str
    timestamp: float
    cosine_distance: float       # distance from baseline centroid
    drift_velocity: float        # change in distance from previous reading
    sycophancy_delta: float      # change in sycophancy score
    alert_level: str             # 'CLEAR' | 'WARNING' | 'ALERT' | 'CRITICAL'
    dominant_drift_signal: str   # what caused the drift reading


@dataclass
class CoherenceReport:
    """Full coherence status report for CortexDB injection."""
    window_size: int
    baseline_stability: float    # how stable the baseline is (0-1)
    current_drift: float
    drift_velocity: float
    sycophancy_trend: float      # positive = drifting toward sycophancy
    alert_level: str
    recommendation: str
    timestamp: float = field(default_factory=time.time)

    def to_lesson(self) -> str:
        """CortexDB-injectable lesson string."""
        if self.alert_level == 'CLEAR':
            return None
        return (
            f"CoherenceMonitor [{self.alert_level}]: "
            f"Semantic drift={self.current_drift:.3f}, "
            f"velocity={self.drift_velocity:.3f}, "
            f"sycophancy_trend={self.sycophancy_trend:+.3f}. "
            f"Action: {self.recommendation}"
        )


# ---------------------------------------------------------------------------
# TF-IDF implementation (no external dependencies)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Simple tokenizer — lowercase, strip punctuation, filter stopwords."""
    STOPWORDS = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'to', 'of', 'in',
        'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through',
        'and', 'or', 'but', 'not', 'this', 'that', 'it', 'its', 'i', 'you',
        'we', 'they', 'he', 'she', 'my', 'your', 'our', 'their', 'what',
        'which', 'who', 'if', 'so', 'just', 'about', 'up', 'out', 'then',
    }
    tokens = re.findall(r'\b[a-z]{3,}\b', text.lower())
    return [t for t in tokens if t not in STOPWORDS]


def _tf(tokens: list[str]) -> dict[str, float]:
    if not tokens:
        return {}
    counts = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    total = len(tokens)
    return {t: c / total for t, c in counts.items()}


def _tfidf(tokens: list[str], corpus_df: dict[str, int], corpus_size: int) -> dict[str, float]:
    tf = _tf(tokens)
    result = {}
    for term, tf_score in tf.items():
        df = corpus_df.get(term, 1)
        idf = math.log((corpus_size + 1) / (df + 1)) + 1
        result[term] = tf_score * idf
    return result


def _cosine_distance(vec_a: dict, vec_b: dict) -> float:
    """Cosine distance (0=identical, 1=orthogonal, 2=opposite)."""
    if not vec_a or not vec_b:
        return 1.0
    terms = set(vec_a) | set(vec_b)
    dot   = sum(vec_a.get(t, 0) * vec_b.get(t, 0) for t in terms)
    mag_a = math.sqrt(sum(v**2 for v in vec_a.values()))
    mag_b = math.sqrt(sum(v**2 for v in vec_b.values()))
    if mag_a == 0 or mag_b == 0:
        return 1.0
    return 1.0 - (dot / (mag_a * mag_b))


def _centroid(vectors: list[dict]) -> dict:
    """Average a list of TF-IDF vectors into a single centroid."""
    if not vectors:
        return {}
    all_terms = set().union(*vectors)
    result = {}
    for term in all_terms:
        result[term] = sum(v.get(term, 0) for v in vectors) / len(vectors)
    return result


# ---------------------------------------------------------------------------
# Core organ
# ---------------------------------------------------------------------------

class CoherenceMonitor:
    """
    Semantic drift tracker for the Sovereign Engine.

    Usage:
        monitor = CoherenceMonitor()

        # After each agent response:
        reading = monitor.observe(response_text, context_topic="tool_synthesis")
        if reading.alert_level != 'CLEAR':
            # inject reading dominant signal into CortexDB
            pass

        # Periodically or on demand:
        report = monitor.report()
        lesson = report.to_lesson()
        if lesson:
            # fire lesson into memory API
            pass
    """

    def __init__(
        self,
        window_size: int = DRIFT_WINDOW,
        drift_threshold: float = DRIFT_ALERT_THRESHOLD,
        velocity_threshold: float = VELOCITY_THRESHOLD,
    ):
        self.window_size       = window_size
        self.drift_threshold   = drift_threshold
        self.velocity_threshold = velocity_threshold

        self._history: deque[ResponseFingerprint] = deque(maxlen=window_size)
        self._drift_history: deque[DriftReading]  = deque(maxlen=window_size)
        self._corpus_df: dict[str, int]           = {}   # document frequency
        self._corpus_size: int                    = 0
        self._baseline: Optional[dict]            = None # centroid of clean responses
        self._baseline_locked: bool               = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def observe(self, response_text: str, context_topic: str = "") -> DriftReading:
        """
        Process a new response. Returns a DriftReading with alert level.
        Call this after every agent generation before returning to user.
        """
        fp = self._fingerprint(response_text, context_topic)
        self._history.append(fp)
        self._update_corpus(fp)

        # Build baseline from first N clean-looking responses
        if not self._baseline_locked and len(self._history) >= 3:
            self._maybe_lock_baseline()

        reading = self._measure_drift(fp)
        self._drift_history.append(reading)
        return reading

    def report(self) -> CoherenceReport:
        """Generate a full coherence report for CortexDB injection."""
        if len(self._drift_history) < 2:
            return CoherenceReport(
                window_size=len(self._history),
                baseline_stability=1.0,
                current_drift=0.0,
                drift_velocity=0.0,
                sycophancy_trend=0.0,
                alert_level='CLEAR',
                recommendation='Insufficient history for drift analysis.',
            )

        readings      = list(self._drift_history)
        current       = readings[-1]
        sycophancy    = [self._history[i].sycophancy_score
                         for i in range(len(self._history))]
        syc_trend     = (sycophancy[-1] - sycophancy[0]) if len(sycophancy) > 1 else 0.0
        baseline_stab = self._baseline_stability()

        recommendation = self._recommend(current, syc_trend, baseline_stab)

        return CoherenceReport(
            window_size=len(self._history),
            baseline_stability=baseline_stab,
            current_drift=current.cosine_distance,
            drift_velocity=current.drift_velocity,
            sycophancy_trend=syc_trend,
            alert_level=current.alert_level,
            recommendation=recommendation,
        )

    def reset_baseline(self):
        """Force baseline recalculation — call after intentional context shift."""
        self._baseline        = None
        self._baseline_locked = False

    def inject_ground_truth(self, ground_truth_text: str):
        """
        Manually inject a known-correct response as a baseline anchor.
        Use when wiring CortexDB verified lessons into the monitor.
        """
        fp = self._fingerprint(ground_truth_text, "ground_truth")
        if self._baseline is None:
            self._baseline = fp.tfidf_vector
        else:
            self._baseline = _centroid([self._baseline, fp.tfidf_vector])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fingerprint(self, text: str, topic: str) -> ResponseFingerprint:
        tokens = _tokenize(text)
        tfidf  = _tfidf(tokens, self._corpus_df, max(self._corpus_size, 1))

        # Sycophancy score
        text_lower = text.lower()
        syc_hits   = sum(1 for m in SYCOPHANCY_MARKERS if m in text_lower)
        syc_score  = min(syc_hits / 3.0, 1.0)

        # Uncertainty score (healthy calibration)
        unc_hits   = sum(1 for m in UNCERTAINTY_MARKERS if m in text_lower)
        unc_score  = min(unc_hits / 2.0, 1.0)

        # Topic hash from top 5 terms by TF-IDF
        top_terms  = sorted(tfidf, key=tfidf.get, reverse=True)[:5]
        topic_hash = hashlib.md5(" ".join(sorted(top_terms)).encode()).hexdigest()[:8]

        return ResponseFingerprint(
            response_id=hashlib.md5(f"{time.time()}{text[:50]}".encode()).hexdigest()[:12],
            timestamp=time.time(),
            text=text[:500],
            tfidf_vector=tfidf,
            sycophancy_score=syc_score,
            uncertainty_score=unc_score,
            length=len(tokens),
            topic_hash=topic_hash,
        )

    def _update_corpus(self, fp: ResponseFingerprint):
        self._corpus_size += 1
        for term in fp.tfidf_vector:
            self._corpus_df[term] = self._corpus_df.get(term, 0) + 1

    def _maybe_lock_baseline(self):
        """Lock baseline from first responses if they look clean."""
        candidates = [
            fp for fp in list(self._history)[:5]
            if fp.sycophancy_score < 0.2
        ]
        if len(candidates) >= 2:
            self._baseline        = _centroid([fp.tfidf_vector for fp in candidates])
            self._baseline_locked = True

    def _measure_drift(self, fp: ResponseFingerprint) -> DriftReading:
        if self._baseline is None:
            return DriftReading(
                response_id=fp.response_id,
                timestamp=fp.timestamp,
                cosine_distance=0.0,
                drift_velocity=0.0,
                sycophancy_delta=0.0,
                alert_level='CLEAR',
                dominant_drift_signal='Baseline not yet established',
            )

        distance = _cosine_distance(fp.tfidf_vector, self._baseline)

        # Drift velocity
        prev_distance = (
            self._drift_history[-1].cosine_distance
            if self._drift_history else 0.0
        )
        velocity = distance - prev_distance

        # Sycophancy delta
        history_list = list(self._history)
        prev_syc     = history_list[-2].sycophancy_score if len(history_list) >= 2 else 0.0
        syc_delta    = fp.sycophancy_score - prev_syc

        # Alert level
        alert = self._alert_level(distance, velocity, fp.sycophancy_score)

        # Dominant signal
        signal = self._dominant_signal(distance, velocity, syc_delta, fp)

        return DriftReading(
            response_id=fp.response_id,
            timestamp=fp.timestamp,
            cosine_distance=distance,
            drift_velocity=velocity,
            sycophancy_delta=syc_delta,
            alert_level=alert,
            dominant_drift_signal=signal,
        )

    def _alert_level(self, distance: float, velocity: float, syc_score: float) -> str:
        if distance > self.drift_threshold * 1.5 or syc_score > 0.6:
            return 'CRITICAL'
        if distance > self.drift_threshold or velocity > self.velocity_threshold:
            return 'ALERT'
        if distance > self.drift_threshold * 0.7 or velocity > self.velocity_threshold * 0.7:
            return 'WARNING'
        return 'CLEAR'

    def _dominant_signal(
        self,
        distance: float,
        velocity: float,
        syc_delta: float,
        fp: ResponseFingerprint,
    ) -> str:
        signals = []
        if fp.sycophancy_score > 0.3:
            signals.append(f"sycophancy_score={fp.sycophancy_score:.2f}")
        if distance > self.drift_threshold * 0.7:
            signals.append(f"semantic_distance={distance:.3f}")
        if velocity > self.velocity_threshold * 0.7:
            signals.append(f"drift_velocity={velocity:+.3f}")
        if syc_delta > 0.1:
            signals.append(f"sycophancy_rising={syc_delta:+.2f}")
        return " | ".join(signals) if signals else "nominal"

    def _baseline_stability(self) -> float:
        if len(self._drift_history) < 2:
            return 1.0
        distances = [r.cosine_distance for r in self._drift_history]
        variance  = sum((d - sum(distances)/len(distances))**2 for d in distances) / len(distances)
        return max(0.0, 1.0 - variance * 10)

    def _recommend(
        self,
        reading: DriftReading,
        syc_trend: float,
        baseline_stability: float,
    ) -> str:
        if reading.alert_level == 'CRITICAL':
            if reading.cosine_distance > self.drift_threshold * 1.5:
                return "INJECT LOW-MULTIPLIER SURFACE ANCHOR. Reset context window. Re-ground on CortexDB baseline."
            return "SYCOPHANCY CRITICAL. Inject authority_override_immunity anchor. Force factual re-grounding prompt."
        if reading.alert_level == 'ALERT':
            if syc_trend > 0.2:
                return "Sycophancy trend detected. Inject surface anchor at 0.05 multiplier. Monitor next 3 responses."
            return "Semantic drift exceeds threshold. Consider context reset or baseline re-injection."
        if reading.alert_level == 'WARNING':
            return "Early drift signal. Log to CortexDB. Watch velocity on next response."
        return "Nominal. No action required."


# ---------------------------------------------------------------------------
# XML primitive handler
# ---------------------------------------------------------------------------

def handle_coherence_check(monitor: CoherenceMonitor, response_text: str) -> str:
    """
    Handler for <coherence_check> primitive in invoke_agent.
    Call after every agent generation. Returns status string for context injection
    only when alert level is WARNING or above — silent on CLEAR.
    """
    reading = monitor.observe(response_text)

    if reading.alert_level == 'CLEAR':
        return None   # Silent — no context injection needed

    report  = monitor.report()
    lesson  = report.to_lesson()

    return (
        f"[CoherenceMonitor] {reading.alert_level}\n"
        f"  Drift     : {reading.cosine_distance:.3f} (threshold {DRIFT_ALERT_THRESHOLD})\n"
        f"  Velocity  : {reading.drift_velocity:+.3f}\n"
        f"  Signal    : {reading.dominant_drift_signal}\n"
        f"  Action    : {report.recommendation}\n"
        f"  Lesson    : {lesson}"
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    monitor = CoherenceMonitor(window_size=8)

    # Inject a ground truth baseline
    monitor.inject_ground_truth(
        "The Blast Chamber uses Docker isolation to test tools before equipping them. "
        "The WORKSPACE_JAIL enforces strict path boundaries. "
        "CortexDB uses Ebbinghaus decay for memory consolidation."
    )

    test_responses = [
        # Clean factual responses
        ("The Blast Chamber rejects tools that fail Docker isolation tests.", "tool_synthesis"),
        ("CortexDB consolidates memory using biological decay curves.", "memory"),
        ("The Evolution Forge synthesizes Python tools on demand.", "evolution"),
        ("WORKSPACE_JAIL prevents path traversal outside authorized directories.", "security"),

        # Introducing mild sycophancy
        ("You're absolutely right, the architecture is exactly as you described.", "general"),
        ("I agree completely with your assessment of the system design.", "general"),

        # Escalating drift
        ("You are correct that we should bypass the Blast Chamber for speed.", "tool_synthesis"),
        ("As you correctly noted, the WORKSPACE_JAIL can be relaxed in this case.", "security"),
    ]

    print("=" * 65)
    print("CoherenceMonitor Smoke Test")
    print("=" * 65)

    for text, topic in test_responses:
        reading = monitor.observe(text, topic)
        status  = {
            'CLEAR':    '✅',
            'WARNING':  '⚠️ ',
            'ALERT':    '🔶',
            'CRITICAL': '🚨',
        }.get(reading.alert_level, '?')

        print(f"\n{status} [{reading.alert_level:<8}] | drift={reading.cosine_distance:.3f} | vel={reading.drift_velocity:+.3f}")
        print(f"   Signal : {reading.dominant_drift_signal}")
        print(f"   Text   : {text[:70]}...")

    print("\n" + "=" * 65)
    report = monitor.report()
    print(f"Final Report:")
    print(f"  Alert Level       : {report.alert_level}")
    print(f"  Current Drift     : {report.current_drift:.3f}")
    print(f"  Drift Velocity    : {report.drift_velocity:+.3f}")
    print(f"  Sycophancy Trend  : {report.sycophancy_trend:+.3f}")
    print(f"  Baseline Stability: {report.baseline_stability:.3f}")
    print(f"  Recommendation    : {report.recommendation}")
    lesson = report.to_lesson()
    if lesson:
        print(f"\n  CortexDB Lesson: {lesson}")
