/* HandPerformance 1.0/1.1 -> deterministic contact trajectories.
 * Public positions: metres. Musical time: nominal seconds, never wall time.
 * See docs/specifications/notion_hand_replacement_2026-09-14.md §§7, 8, 19.
 * This plans geometric contact, not force or clinically validated biomechanics.
 */
export const FINGERS = Object.freeze(["index", "middle", "ring", "pinky"]);
export const MOTION_CAPABILITIES = Object.freeze([
  "transport.tempoMap", "performance.noteExecution", "motion.contact", "motion.anticipation", "motion.hold",
  "motion.hammerOn", "motion.pullOff", "motion.slide", "motion.bendCurve",
  "motion.vibratoCurve", "motion.seek", "motion.playbackRate",
]);
const finite = Number.isFinite;
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
export const minimumJerk = t => {
  t = clamp(t, 0, 1);
  return t * t * t * (10 + t * (-15 + 6 * t));
};
const distance = (a, b) => Math.hypot(...a.map((v, i) => v - b[i]));
const lerp3 = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
const sameContact = (a, b) => a.stringNo === b.stringNo && a.fretAbs === b.fretAbs;
const diagnostic = (code, message, noteIds = [], interval = null, severity = "warning") =>
  ({code, message, noteIds, ...(interval ? {interval} : {}), severity});

function rootAt(frames, sec, fallback) {
  let x = frames[0]?.x ?? fallback;
  for (let i = 1; i < frames.length; i++) {
    const frame = frames[i], previous = frames[i - 1];
    if (sec < frame.start) break;
    if (sec >= frame.on) x = frame.x;
    else { x = previous.x + (frame.x - previous.x)
      * minimumJerk((sec - frame.start) / Math.max(1e-9, frame.on - frame.start)); break; }
  }
  return x;
}

// Rest targets belonging to the delivered adult-reference-left/1 profile.
// These MCP offsets are measured from the source rig; no dynamic bone scaling.
function restTarget(finger, rootX) {
  const i = FINGERS.indexOf(finger);
  const mcpX = [-.0235506924548, -.0017259102062, .0174652305685, .0350540583275];
  return [rootX - mcpX[0] + .018 + mcpX[i] + .003, .016 + i * .0015, .012];
}

/** Integrate a piecewise constant tempo map in quarter-note units. */
export function makeTempoClock(ppq, tempoMap) {
  if (!Number.isInteger(ppq) || ppq <= 0 || !Array.isArray(tempoMap) || !tempoMap.length) {
    throw new Error("INVALID_TEMPO_MAP: PPQ and tempo points required");
  }
  let seconds = 0;
  const segments = tempoMap.map((point, i) => {
    if (!Number.isInteger(point.tick) || point.tick < 0 || !finite(point.usPerQuarter)
        || point.usPerQuarter <= 0 || (i === 0 && point.tick !== 0)
        || (i && point.tick <= tempoMap[i - 1].tick)) {
      throw new Error("INVALID_TEMPO_MAP: ordered constant tempos starting at tick 0 required");
    }
    if (point.interpolation && point.interpolation !== "constant") {
      throw new Error("TEMPO_RAMP_UNSUPPORTED");
    }
    if (i) seconds += (point.tick - tempoMap[i - 1].tick)
      * tempoMap[i - 1].usPerQuarter / (ppq * 1e6);
    return {tick: point.tick, sec: seconds, secPerTick: point.usPerQuarter / (ppq * 1e6)};
  });
  function find(value, field) {
    let lo = 0, hi = segments.length;
    while (lo + 1 < hi) {
      const mid = (lo + hi) >> 1;
      if (segments[mid][field] <= value) lo = mid; else hi = mid;
    }
    return segments[lo];
  }
  return {
    tickToSeconds(tick) {
      if (!finite(tick)) throw new Error("INVALID_TICK");
      const s = find(tick, "tick");
      return s.sec + (tick - s.tick) * s.secPerTick;
    },
    secondsToTick(sec) {
      if (!finite(sec)) throw new Error("INVALID_SECONDS");
      const s = find(sec, "sec");
      return s.tick + (sec - s.sec) / s.secPerTick;
    },
  };
}

/** Canonical right-handed coordinates: X toward bridge, Y toward treble, Z up. */
export function makeInstrumentGeometry(instrument) {
  const scale = instrument.scaleLengthM;
  const count = instrument.strings?.length;
  if (!finite(scale) || scale <= 0 || !count || count > 12) {
    throw new Error("INVALID_INSTRUMENT");
  }
  // Versioned reference electric-guitar dimensions, explicit in plan metadata.
  const nutSpacing = instrument.nutStringSpacingM ?? 0.042;
  const bridgeSpacing = instrument.bridgeStringSpacingM ?? 0.052;
  const radius = instrument.fingerboardRadiusM ?? 0.3048;
  const fretHeight = instrument.fretHeightM ?? 0.0013;
  const capo = instrument.capoFret || 0;
  const fretX = fret => scale * (1 - 2 ** (-fret / 12));
  const stringY = (stringNo, x) => count === 1 ? 0 :
    ((count + 1) / 2 - stringNo) / (count - 1)
    * (nutSpacing + (bridgeSpacing - nutSpacing) * x / scale);
  const surfaceZ = (x, y) => radius > 0 ? Math.sqrt(Math.max(0, radius ** 2 - y ** 2)) - radius : 0;
  const stringRadius = stringNo => instrument.strings.find(s => s.number === stringNo)?.radiusM
    ?? [0.00013, 0.00017, 0.00022, 0.00033, 0.00046, 0.00058][stringNo - 1] ?? 0.00058;
  const freeHeight = x => (instrument.nutActionM ?? 0.0015)
    + (instrument.bridgeActionM ?? 0.0045) * x / scale + fretHeight;
  function target(fingering, hover = 0) {
    const fret = fingering.fretAbs;
    const right = fretX(fret), left = fretX(Math.max(capo, fret - 1));
    // Stay on wood before the crown; adapt offset in closely spaced high frets.
    const offset = Math.min(0.005, Math.max(0.001, (right - left) * 0.30));
    const x = fret > capo ? right - offset : fretX(capo);
    const y = stringY(fingering.stringNo, x);
    return [x, y, surfaceZ(x, y) + fretHeight + 2 * stringRadius(fingering.stringNo) + hover];
  }
  return {scale, count, capo, fretX, stringY, surfaceZ, stringRadius, freeHeight, target,
    profile: {nutSpacing, bridgeSpacing, radius, fretHeight}};
}

/** Linear, clamped absolute-tick expression curve, without spline overshoot. */
export function sampleCurve(curve, tick) {
  const points = curve?.points;
  if (!Array.isArray(points) || !points.length) return 0;
  if (tick <= points[0].tick) return points[0].value;
  for (let i = 1; i < points.length; i++) {
    if (tick <= points[i].tick) {
      const a = points[i - 1], b = points[i];
      return a.value + (b.value - a.value) * (tick - a.tick) / (b.tick - a.tick);
    }
  }
  return points.at(-1).value;
}

function stableKey(value) {
  // Fast identity checksum, not an integrity/security hash. Full input kept in plan.
  const json = JSON.stringify(value);
  let hash = 2166136261;
  for (let i = 0; i < json.length; i++) hash = Math.imul(hash ^ json.charCodeAt(i), 16777619);
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/** Compile all note intervals once; sampling never depends on previous frames. */
export function compilePerformance(performance, {playbackRate = 1, rigRevision = "reference-1"} = {}) {
  if (!["1.0", "1.1"].includes(performance.schemaVersion)) throw new Error("UNSUPPORTED_SCHEMA_VERSION");
  if (!finite(playbackRate) || playbackRate <= 0) throw new Error("INVALID_PLAYBACK_RATE");
  if (performance.hand?.profileId !== "adult-reference-left" || performance.hand?.profileRevision !== "1") {
    throw new Error("HAND_PROFILE_UNSUPPORTED");
  }
  if (performance.instrument?.profileId !== "six-string-648" || performance.instrument?.profileRevision !== "1"
      || performance.instrument.strings?.length !== 6 || performance.instrument.fretCount > 24) {
    throw new Error("INSTRUMENT_PROFILE_UNSUPPORTED");
  }
  const clock = makeTempoClock(performance.ppq, performance.tempoMap);
  const geometry = makeInstrumentGeometry(performance.instrument);
  const notes = performance.notes || [];
  const expressions = performance.expressions || [];
  const deadNoteIds = new Set(expressions
    .filter(expression => expression.kind === "dead_note")
    .flatMap(expression => expression.noteIds || []));
  const ids = new Set();
  const diagnostics = [...(performance.diagnostics || [])];
  const startSec = clock.tickToSeconds(performance.range.startTick);
  const endSec = clock.tickToSeconds(performance.range.endTick);
  const executions = new Map((performance.noteExecution || []).map(e => [e.occurrenceId, e]));
  const details = new Map((performance.expressionDetails || []).map(e => [e.expressionId, e]));
  const byFinger = Object.fromEntries(FINGERS.map(f => [f, []]));
  const noteMap = new Map(notes.map(n => [n.occurrenceId, n]));
  const invalid = [];
  const events = [];
  const fail = (code, message, noteIds, begin, end, finger = null) => {
    const item = diagnostic(code, message, noteIds, {startSec: begin, endSec: end}, "error");
    if (finger) item.finger = finger;
    diagnostics.push(item); invalid.push(item);
  };
  for (const item of performance.diagnostics || []) {
    if (["REPEAT_UNFOLDING_REQUIRED", "TEMPO_RAMP_UNSUPPORTED"].includes(item.code)) {
      invalid.push({...item, severity: "error", interval: {startSec, endSec}});
    }
  }
  for (const capability of performance.requiredCapabilities || []) {
    if (!MOTION_CAPABILITIES.includes(capability)) {
      fail("CAPABILITY_UNSUPPORTED", `Capacité absente : ${capability}`, [], startSec, endSec);
    }
  }
  if (performance.hand?.side !== "left") {
    fail("HAND_SIDE_UNSUPPORTED", "Actif de référence disponible pour main gauche uniquement.", [], startSec, endSec);
  }
  for (const note of notes) {
    if (!note.occurrenceId || ids.has(note.occurrenceId)) throw new Error("DUPLICATE_NOTE_ID");
    ids.add(note.occurrenceId);
    const f = note.fingering;
    if (!f || !performance.instrument.strings.some(s => s.number === f.stringNo)
        || !Number.isInteger(f.fretAbs) || f.fretAbs < geometry.capo
        || f.fretAbs > performance.instrument.fretCount) throw new Error("INVALID_FINGERING");
    if (!Number.isInteger(note.onTick) || !Number.isInteger(note.soundEndTick)
        || note.soundEndTick < note.onTick) throw new Error("INVALID_NOTE_INTERVAL");
    // A dead note is represented as X in score, Tab and lookahead.  Its
    // damping contact is not qualified by this pressing rig, so never draw
    // it as an ordinary fretted press.
    if (deadNoteIds.has(note.occurrenceId)) continue;
    if (f.finger === "open") {
      if (f.fretAbs !== geometry.capo) throw new Error("INVALID_OPEN_FINGERING");
      continue;
    }
    const execution = executions.get(note.occurrenceId);
    if (performance.schemaVersion === "1.1" && !execution) throw new Error("MISSING_NOTE_EXECUTION");
    const on = clock.tickToSeconds(note.onTick);
    const endTick = execution?.sustainRequiredUntilTick ?? note.soundEndTick;
    if (!finite(endTick) || endTick < note.onTick) throw new Error("INVALID_SUSTAIN_INTERVAL");
    const end = clock.tickToSeconds(endTick);
    if (!byFinger[f.finger]) {
      fail("FINGER_UNSUPPORTED", `Doigt frettant non qualifié : ${f.finger}`, [note.occurrenceId], on, end);
      continue;
    }
    if (!execution && note.notatedEndTick !== note.soundEndTick) {
      diagnostics.push(diagnostic("TIMING_AMBIGUOUS", "Durée de contact fondée sur la fin sonore 1.0.", [note.occurrenceId]));
    }
    const contact = {id: `contact:${note.occurrenceId}`, noteIds: [note.occurrenceId],
      finger: f.finger, stringNo: f.stringNo, fretAbs: f.fretAbs, on, end,
      target: geometry.target(f), expressionIds: note.expressionIds || [],
      attackKind: execution?.attackKind || "pick", execution};
    byFinger[f.finger].push(contact);
    events.push({kind: "pressReady", sec: on, noteIds: contact.noteIds, contactId: contact.id},
      {kind: "contactEnd", sec: end, noteIds: contact.noteIds, contactId: contact.id});
  }
  // Holds are explicit constraints; they never silently rewrite a fingering.
  for (const hold of performance.holds || []) {
    if (!byFinger[hold.finger]) continue;
    byFinger[hold.finger].push({id: `hold:${hold.finger}:${hold.startTick}`, noteIds: [],
      finger: hold.finger, stringNo: hold.stringNo, fretAbs: hold.fretAbs,
      on: clock.tickToSeconds(hold.startTick), end: clock.tickToSeconds(hold.endTick),
      target: geometry.target(hold), expressionIds: [], attackKind: "none"});
  }
  for (const expression of expressions) {
    const begin = clock.tickToSeconds(expression.startTick), end = clock.tickToSeconds(expression.endTick);
    if ((expression.noteIds || []).some(id => !noteMap.has(id))) throw new Error("UNKNOWN_EXPRESSION_NOTE");
    if (["bend", "vibrato"].includes(expression.kind)) {
      const points = expression.cents?.points;
      if (!points?.length || points.some((p, i) => !finite(p.tick) || !finite(p.value)
          || (i && p.tick <= points[i - 1].tick))
          || points[0].tick > expression.startTick || points.at(-1).tick < expression.endTick) {
        fail("EXPRESSION_CURVE_INVALID", "Courbe d’expression absente ou incomplète.", expression.noteIds, begin, end);
      } else if (!details.get(expression.id)?.lateralDisplacementM) {
        diagnostics.push(diagnostic("BEND_CALIBRATION_MISSING", "Déplacement de corde illustratif, sans calibration de tension.", expression.noteIds));
      }
      for (const other of expressions) {
        if (other === expression || other.id >= expression.id || !["bend", "vibrato"].includes(other.kind)) continue;
        if (details.get(other.id)?.pitchComposition === "additiveResidual"
            || details.get(expression.id)?.pitchComposition === "additiveResidual") continue;
        if (Math.max(other.startTick, expression.startTick) < Math.min(other.endTick, expression.endTick)
            && other.noteIds.some(id => expression.noteIds.includes(id))) {
          fail("EXPRESSION_COMPOSITION_CONFLICT", "Deux courbes absolues de hauteur se superposent.",
            expression.noteIds, begin, end);
        }
      }
    } else if (["slide", "hammer_on", "pull_off"].includes(expression.kind)) {
      const from = noteMap.get(expression.fromId), to = noteMap.get(expression.toId);
      const sameString = from && to && from.fingering.stringNo === to.fingering.stringNo;
      const ordered = sameString && (expression.kind === "slide"
        ? from.fingering.finger === to.fingering.finger
        : expression.kind === "hammer_on"
          ? from.fingering.fretAbs < to.fingering.fretAbs && from.fingering.finger !== to.fingering.finger
          : from.fingering.fretAbs > to.fingering.fretAbs && from.fingering.finger !== to.fingering.finger);
      if (!ordered) fail("TECHNIQUE_FINGERING_CONFLICT", "Expression incompatible avec corde/case/doigts transmis.", expression.noteIds, begin, end);
    } else if (expression.kind === "dead_note") {
      diagnostics.push(diagnostic("DEAD_NOTE_DAMPING_NOT_RENDERED",
        "Note étouffée marquée X ; contact d'étouffement non rendu par ce rig.", expression.noteIds));
    } else if (!["tie", "let_ring", "staccato", "pick_attack", "palm_mute", "tremolo_picking"].includes(expression.kind)) {
      fail("TECHNIQUE_UNSUPPORTED", `Animation non qualifiée : ${expression.kind}`, expression.noteIds, begin, end);
    } else if (["palm_mute", "tremolo_picking"].includes(expression.kind)) {
      diagnostics.push(diagnostic("PICKING_HAND_NOT_RENDERED", "Expression de main droite conservée, main droite non affichée.", expression.noteIds));
    }
  }
  // Pull-off destination must already be in place below the higher sounding fret.
  for (const expression of expressions.filter(e => e.kind === "pull_off")) {
    const from = noteMap.get(expression.fromId), to = noteMap.get(expression.toId);
    const contact = to && byFinger[to.fingering.finger]?.find(c => c.noteIds.includes(to.occurrenceId));
    if (contact && from && from.fingering.stringNo === to.fingering.stringNo) {
      contact.on = Math.max(clock.tickToSeconds(from.onTick), contact.on - 0.10 * playbackRate);
      contact.supportUntil = clock.tickToSeconds(to.onTick);
    }
  }
  const rootFrames = [];
  for (const onTick of [...new Set(notes.map(n => n.onTick))].sort((a, b) => a - b)) {
    const group = notes.filter(n => n.onTick === onTick && FINGERS.includes(n.fingering.finger)
      && !deadNoteIds.has(n.occurrenceId));
    if (!group.length) continue;
    const implied = group.map(n => Math.max(geometry.capo + 1,
      n.fingering.fretAbs - FINGERS.indexOf(n.fingering.finger))).sort((a, b) => a - b);
    const hints = group.map(n => n.fingering.handPositionHint).filter(finite).sort((a, b) => a - b);
    // Imported source annotations may label every finger with its own fret.
    // A hand-position hint is a preference, never a rigid translation: the
    // complete chord must first fit the relative placement of all four fingers.
    const preferred = hints.length ? hints[Math.floor(hints.length / 2)]
      : implied[Math.floor(implied.length / 2)];
    const position = clamp(preferred, implied[0], implied.at(-1));
    const x = geometry.target({fretAbs: position, stringNo: 3})[0];
    const on = clock.tickToSeconds(onTick);
    if (rootFrames.at(-1)?.x === x) continue;
    const previous = rootFrames.at(-1);
    rootFrames.push({on, start: Math.max(startSec, previous?.on ?? startSec,
      on - (0.10 + Math.abs(x - (previous?.x ?? x)) / .5) * playbackRate), x});
  }
  for (const finger of FINGERS) {
    const sorted = byFinger[finger].sort((a, b) => a.on - b.on || a.id.localeCompare(b.id));
    const merged = [];
    for (const contact of sorted) {
      const prev = merged.at(-1);
      if (prev && sameContact(prev, contact) && contact.on <= prev.end + 1e-7) {
        prev.end = Math.max(prev.end, contact.end);
        prev.noteIds.push(...contact.noteIds); prev.expressionIds.push(...contact.expressionIds);
      } else merged.push(contact);
    }
    byFinger[finger] = merged;
    for (let i = 0; i < merged.length; i++) {
      const contact = merged[i], previous = merged[i - 1];
      if (previous && contact.on < previous.end - 1e-7) {
        fail("FINGER_CONTACT_CONFLICT", "Un doigt ne peut assurer ces contacts simultanés.",
          [...previous.noteIds, ...contact.noteIds], contact.on, Math.min(contact.end, previous.end), finger);
      }
      const from = previous?.target || restTarget(finger, rootAt(rootFrames, contact.on, geometry.fretX(3)));
      const length = distance(from, contact.target);
      const realDuration = clamp(0.065 + length / 0.7, 0.065, 0.40);
      const required = realDuration * playbackRate;
      const earliestTick = contact.execution?.preparationWindow?.earliestTick;
      const earliest = Math.max(startSec, previous?.end ?? startSec,
        finite(earliestTick) ? clock.tickToSeconds(earliestTick) : startSec);
      contact.prepareStart = Math.max(earliest, contact.on - required);
      const rest = restTarget(finger, rootAt(rootFrames, contact.prepareStart, geometry.fretX(3)));
      contact.from = previous ? lerp3(previous.target, rest,
        minimumJerk((contact.prepareStart - previous.end) / (.10 * playbackRate))) : rest;
      contact.lift = Math.max(0.003, Math.min(0.012, length * 0.15 + 0.002));
      const slide = previous && expressions.find(e => e.kind === "slide"
        && previous.noteIds.includes(e.fromId) && contact.noteIds.includes(e.toId));
      if (slide) {
        contact.slideFrom = previous;
        contact.prepareStart = clock.tickToSeconds(slide.startTick);
        contact.from = previous.target.slice();
        contact.lift = 0;
      } else if (previous && contact.on - earliest < required * 0.45 && !sameContact(previous, contact)) {
        // The musical attack stays untouched. Show an explicitly invalid,
        // continuous late approach instead of teleporting at a missed deadline.
        contact.lateLanding = earliest + required;
        fail("TRANSITION_WINDOW_SHORT", "Fenêtre insuffisante dans le profil moteur de référence ; tenue conservée.",
          [...previous.noteIds, ...contact.noteIds], earliest, contact.lateLanding, finger);
      }
      // A first note at the available origin is a static initial pose, not a fake lead-in.
      contact.initial = !previous && contact.on === startSec;
    }
  }
  if ((performance.barres || []).length) {
    diagnostics.push(diagnostic("BARRE_SURFACE_UNQUALIFIED", "Barrés conservés ; contact surfacique complet non qualifié."));
  }
  const key = stableKey({performance, playbackRate, rigRevision, planner: 1});
  return {schemaVersion: "1.0", key, performance, playbackRate, clock, geometry,
    byFinger, expressions, details, diagnostics, invalid, events: events.sort((a, b) => a.sec - b.sec),
    rootFrames, startSec, endSec, status: invalid.length ? "partial" : "illustrative"};
}

/** Evaluate one complete state directly, including backward seeks and pauses. */
export function sampleMotion(plan, nominalScoreSec) {
  if (!finite(nominalScoreSec)) throw new Error("INVALID_SECONDS");
  const sec = clamp(nominalScoreSec, plan.startSec, plan.endSec);
  const tick = plan.clock.secondsToTick(sec);
  const centerX = rootAt(plan.rootFrames, sec, plan.geometry.fretX(3));
  const fingers = {};
  const activeContactIds = [];
  const activeDiagnostics = plan.invalid.filter(d => sec >= d.interval.startSec && sec < d.interval.endSec);
  for (const finger of FINGERS) {
    const contacts = plan.byFinger[finger];
    // Transition trajectories take precedence over a preceding slide contact.
    const next = contacts.find(c => sec >= c.prepareStart && sec < (c.lateLanding ?? c.on)
      && sec < c.end);
    const current = contacts.find(c => sec >= c.on && sec < c.end);
    let state = "REST", target, selected, pressure = 0;
    if (next && (!current || next === current || next.slideFrom === current)) {
      const t = clamp((sec - next.prepareStart)
        / Math.max(1e-9, (next.lateLanding ?? next.on) - next.prepareStart), 0, 1);
      const eased = minimumJerk(t);
      target = lerp3(next.from, next.target, eased);
      target[2] += next.lift * 64 * t ** 3 * (1 - t) ** 3;
      state = next.slideFrom ? "EXPRESS" : t < 0.2 ? "PREPARE" : t > 0.8 ? "LAND" : "TRANSFER";
      pressure = next.slideFrom ? 1 : 0;
      selected = next;
    } else if (current) {
      selected = current; target = current.target.slice(); state = "HOLD"; pressure = 1;
      activeContactIds.push(current.id);
    } else {
      const future = contacts.find(c => c.on > sec);
      const past = contacts.filter(c => c.end <= sec).at(-1);
      selected = past || future;
      target = restTarget(finger, centerX);
      if (past && sec - past.end < .10 * plan.playbackRate) {
        state = "RELEASE";
        target = lerp3(past.target, target, minimumJerk((sec - past.end) / (.10 * plan.playbackRate)));
      }
    }
    const pitch = [];
    for (const expression of plan.expressions) {
      if (tick < expression.startTick || tick > expression.endTick || !selected
          || !expression.noteIds?.some(id => selected.noteIds.includes(id))) continue;
      if (["bend", "vibrato"].includes(expression.kind)) {
        const cents = sampleCurve(expression.cents, tick);
        const detail = plan.details.get(expression.id);
        // Illustrative string-specific geometric mapping; flagged without calibration.
        const lateral = detail?.lateralDisplacementM
          ? sampleCurve(detail.lateralDisplacementM, tick)
          : Math.sqrt(Math.abs(cents) / 100) * (0.0024 + selected.stringNo * 0.00025)
            * (expression.kind === "vibrato" ? Math.sign(cents) : 1);
        const sign = expression.direction === "toward_treble" ? 1 : -1;
        if (expression.kind === "vibrato" && expression.mechanism === "longitudinal") {
          target[0] += lateral * .2;
        } else target[1] += lateral * sign;
        state = "EXPRESS"; pitch.push({expressionId: expression.id, cents});
      }
      if (expression.kind === "pull_off" && selected.noteIds.includes(expression.fromId)) {
        const to = plan.performance.notes.find(n => n.occurrenceId === expression.toId);
        const attack = to ? plan.clock.tickToSeconds(to.onTick) : plan.clock.tickToSeconds(expression.endTick);
        const approach = clamp((sec - (attack - 0.04 * plan.playbackRate)) / (0.04 * plan.playbackRate), 0, 1);
        target[1] -= 0.0018 * minimumJerk(approach); state = "EXPRESS";
      }
    }
    fingers[finger] = {finger, state, targetM: target, pressure01: pressure,
      noteIds: state === "REST" ? [] : selected?.noteIds || [], contactId: pressure ? selected?.id : null,
      stringNo: selected?.stringNo ?? null, fretAbs: selected?.fretAbs ?? null, pitch,
      valid: !activeDiagnostics.some(d => !d.finger || d.finger === finger)};
  }
  return {nominalScoreSec: sec, tick, fingers, activeContactIds,
    rootPositionM: [centerX, 0.047, -0.027], rootOrientation: [0, 0, 0, 1],
    valid: activeDiagnostics.length === 0, diagnostics: activeDiagnostics};
}
