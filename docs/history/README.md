# History: the removed RunPod/ComfyUI LoRA route

PRD v6 R5 (2026-10-20) removed the RunPod Serverless / ComfyUI image route and Roman's LoRA
(provider code, `ca lora`, `config/comfyui.json`, `config/lora.json`, the RUNPOD_* settings).
Roman's images are made with Higgsfield Soul 2.0 only; every other image with OpenRouter.

These files are kept as a record of what was tried, never as instructions:

- `runpod-comfyui.md`, `runpod-zimage-setup.md`: the old endpoint and Pod setup.
- `kaggle-lora.md`, `lora-training-results.md`: the LoRA training runs and their results.
- `notebooks/kaggle_train_lora.ipynb`, `notebooks/kaggle_test_lora.ipynb` (left in place): the
  free Kaggle training and test notebooks.

The archived prompt pools and Roman post formats are in `config/_archive/`.
