/* Temporal compilation runs off the rendering thread; no DOM/WebGL dependency. */
import {compilePerformance} from "./hand_motion.js";

export function compileWorkerMessage(message) {
  const {requestId, performance, playbackRate, rigRevision} = message;
  try {
    const {clock, geometry, ...plan} = compilePerformance(performance, {playbackRate, rigRevision});
    // Functions are reconstructed on the host; all actual planning stays here.
    return {type: "result", requestId, plan};
  } catch (error) {
    return {type: "failed", requestId, code: error.message || "COMPILATION_FAILED"};
  }
}

if (typeof self !== "undefined" && typeof self.document === "undefined") {
  self.onmessage = event => self.postMessage(compileWorkerMessage(event.data));
}
