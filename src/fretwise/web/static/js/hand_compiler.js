/* Cancellable, latest-request-wins worker owner. */
import {makeTempoClock, makeInstrumentGeometry} from "./hand_motion.js";

const aborted = () => Object.assign(new Error("Compilation remplacée ou annulée."), {name: "AbortError"});

export class HandPlanCompiler {
  constructor({workerFactory = url => new Worker(url, {type: "module"}), timeoutMs = 45000} = {}) {
    this.workerFactory = workerFactory; this.timeoutMs = timeoutMs;
    this.sequence = 0; this.pending = null; this.disposed = false;
  }

  cancel() {
    const pending = this.pending;
    if (!pending) return;
    this.pending = null; clearTimeout(pending.timer); pending.worker.terminate();
    pending.signal?.removeEventListener("abort", pending.onAbort);
    pending.reject(aborted());
  }

  compile(performance, {playbackRate = 1, rigRevision = "reference-1", signal} = {}) {
    this.cancel();
    if (this.disposed || signal?.aborted) return Promise.reject(aborted());
    const requestId = ++this.sequence;
    return new Promise((resolve, reject) => {
      let worker;
      try { worker = this.workerFactory(new URL("./hand_motion_worker.js", import.meta.url)); }
      catch (error) { reject(new Error(`WORKER_UNAVAILABLE: ${error.message}`)); return; }
      const pending = {requestId, worker, reject, signal, timer: null, onAbort: () => this.cancel()};
      const finish = (error, plan) => {
        if (this.pending !== pending) return;
        this.pending = null; clearTimeout(pending.timer); worker.terminate();
        signal?.removeEventListener("abort", pending.onAbort);
        if (error) reject(error); else resolve(plan);
      };
      this.pending = pending;
      worker.onmessage = event => {
        const response = event.data;
        if (this.pending !== pending || response?.requestId !== requestId) return;
        if (response.type === "failed") { finish(new Error(response.code)); return; }
        if (response.type !== "result") return;
        try {
          const plan = response.plan;
          plan.clock = makeTempoClock(performance.ppq, performance.tempoMap);
          plan.geometry = makeInstrumentGeometry(performance.instrument);
          finish(null, plan);
        } catch (error) { finish(error); }
      };
      worker.onerror = event => finish(new Error(`WORKER_FAILED: ${event.message || "unknown"}`));
      worker.onmessageerror = () => finish(new Error("WORKER_PAYLOAD_INVALID"));
      pending.timer = setTimeout(() => finish(new Error("COMPILATION_TIMEOUT")), this.timeoutMs);
      signal?.addEventListener("abort", pending.onAbort, {once: true});
      try { worker.postMessage({requestId, performance, playbackRate, rigRevision}); }
      catch (error) { finish(error); }
    });
  }

  dispose() { this.disposed = true; this.cancel(); }
}
