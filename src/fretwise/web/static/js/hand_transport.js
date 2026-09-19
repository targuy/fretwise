/** Versioned same-origin hand-view transport. No renderer or wall-clock state. */
export const HAND_PROTOCOL_VERSION = 1;

export class HandTransportReceiver {
  constructor(origin, source) {
    this.origin = origin;
    this.source = source;
    this.sessionId = null;
    this.planId = null;
    this.sequence = -1;
    this.snapshot = null;
  }

  /** Reject cross-window, obsolete, malformed and foreign-plan messages. */
  accept(event) {
    if (event.origin !== this.origin || event.source !== this.source) return null;
    const m = event.data;
    if (!m || m.protocolVersion !== HAND_PROTOCOL_VERSION
        || typeof m.sessionId !== 'string' || !m.sessionId
        || typeof m.planId !== 'string' || !m.planId
        || !Number.isSafeInteger(m.sequence) || m.sequence < 0) return null;
    if (m.type === 'fretwise:load') {
      if (!m.payload || !Array.isArray(m.payload.frames)) return null;
      if (this.sessionId === m.sessionId && m.sequence <= this.sequence) return null;
      this.sessionId = m.sessionId;
      this.planId = m.planId;
      this.sequence = m.sequence;
      this.snapshot = null;
      return m;
    }
    if (m.type !== 'fretwise:transport' || m.sessionId !== this.sessionId
        || m.planId !== this.planId || m.sequence <= this.sequence
        || !['playing', 'paused', 'seeking', 'stopped'].includes(m.status)
        || !Number.isFinite(m.nominalScoreSec) || m.nominalScoreSec < 0
        || !Number.isFinite(m.rate) || m.rate <= 0
        || !Number.isFinite(m.anchorEpochMs)
        || !Number.isSafeInteger(m.discontinuityId) || m.discontinuityId < 0) return null;
    if (this.snapshot && m.discontinuityId < this.snapshot.discontinuityId) return null;
    this.sequence = m.sequence;
    this.snapshot = m;
    return m;
  }

  /** Project at most 250 ms; an iframe never runs away after parent suspension. */
  timeAt(epochMs) {
    const m = this.snapshot;
    if (!m) return 0;
    const elapsed = m.status === 'playing'
      ? Math.max(0, Math.min(0.25, (epochMs - m.anchorEpochMs) / 1000)) : 0;
    return m.nominalScoreSec + elapsed * m.rate;
  }

  isDesynced(epochMs) {
    return this.snapshot?.status === 'playing'
      && epochMs - this.snapshot.anchorEpochMs > 250;
  }
}
