# Private CPU model artifact. Build only from the validated handoff directory:
# docker build -f docker/models.Dockerfile -t fretwise-models:local .
FROM scratch

LABEL org.opencontainers.image.title="FretWise production fingering models"
LABEL org.opencontainers.image.version="fingering-production-2026-08-20"

COPY data/models/runtime_bundle.json /models/runtime_bundle.json
COPY data/models/finger_classifier.onnx /models/finger_classifier.onnx
COPY data/models/transition_cost_v3.onnx /models/transition_cost_v3.onnx
COPY data/models/phrase_window_v2_anchor_head.onnx /models/phrase_window_v2_anchor_head.onnx
COPY data/models/phrase_window_v2_slot0_finger.onnx /models/phrase_window_v2_slot0_finger.onnx
COPY data/models/phrase_window_v2_slot1_finger.onnx /models/phrase_window_v2_slot1_finger.onnx
COPY data/models/phrase_window_v2_slot2_finger.onnx /models/phrase_window_v2_slot2_finger.onnx
COPY data/models/phrase_window_v2_slot3_finger.onnx /models/phrase_window_v2_slot3_finger.onnx
COPY data/models/phrase_window_v2_slot4_finger.onnx /models/phrase_window_v2_slot4_finger.onnx
